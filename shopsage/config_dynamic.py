"""
Dynamic Configuration — Runtime-mutable config store for ShopSage AI.

Allows changing operational parameters without redeployment:
- Rate limits, cache TTLs, model parameters
- Feature toggles, thresholds, timeouts
- Per-tenant overrides

Schema:
    dynamic_config: key, value, value_type, description,
                    tenant_id, updated_at, updated_by

Changes are persisted in SQLite and cached in memory
for high-performance reads.
"""

import sqlite3
import json
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.config.dynamic")

# Default runtime configuration values
DEFAULTS = {
    # Rate limiting
    "rate_limit.free.requests_per_minute": {"value": 30, "type": "int", "desc": "Free tier rate limit (req/min)"},
    "rate_limit.pro.requests_per_minute": {"value": 120, "type": "int", "desc": "Pro tier rate limit (req/min)"},
    "rate_limit.enterprise.requests_per_minute": {"value": 1000, "type": "int", "desc": "Enterprise rate limit (req/min)"},

    # Cache
    "cache.price_ttl_seconds": {"value": 300, "type": "int", "desc": "Price cache TTL in seconds"},
    "cache.review_ttl_seconds": {"value": 600, "type": "int", "desc": "Review cache TTL in seconds"},
    "cache.embedding_ttl_seconds": {"value": 3600, "type": "int", "desc": "Embedding cache TTL in seconds"},

    # Agent
    "agent.max_response_length": {"value": 2000, "type": "int", "desc": "Max characters in agent response"},
    "agent.temperature": {"value": 0.7, "type": "float", "desc": "LLM temperature for responses"},
    "agent.timeout_seconds": {"value": 30, "type": "int", "desc": "Agent response timeout"},

    # Jobs
    "jobs.max_retries": {"value": 3, "type": "int", "desc": "Default max retries for background jobs"},
    "jobs.worker_poll_interval": {"value": 3.0, "type": "float", "desc": "Worker poll interval in seconds"},

    # Security
    "security.max_message_length": {"value": 2000, "type": "int", "desc": "Max chat message length"},
    "security.enable_prompt_injection_check": {"value": True, "type": "bool", "desc": "Enable prompt injection detection"},

    # Notifications
    "notifications.purge_after_days": {"value": 30, "type": "int", "desc": "Auto-purge notifications after N days"},
    "notifications.max_per_tenant": {"value": 500, "type": "int", "desc": "Max stored notifications per tenant"},
}


class DynamicConfig:
    """
    SQLite-backed runtime configuration with in-memory caching.

    Supports:
    - Typed values (int, float, str, bool, json)
    - Global and per-tenant overrides
    - Thread-safe cached reads
    - Audit trail (who changed what, when)
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._cache: Dict[str, Any] = {}
        self._tenant_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._init_db()
        self._seed_defaults()
        self._refresh_cache()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create dynamic_config table."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS dynamic_config (
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        value_type TEXT DEFAULT 'str',
                        description TEXT DEFAULT '',
                        tenant_id TEXT DEFAULT '',
                        updated_at TEXT NOT NULL,
                        updated_by TEXT DEFAULT 'system',
                        PRIMARY KEY (key, tenant_id)
                    )
                """)
                conn.commit()
            logger.info("[DynamicConfig] Initialized")
        except sqlite3.Error as e:
            logger.error(f"[DynamicConfig] Init error: {e}")
            raise

    def _seed_defaults(self) -> None:
        """Insert default values if they don't exist."""
        now = datetime.utcnow().isoformat()
        try:
            with self._conn() as conn:
                for key, info in DEFAULTS.items():
                    conn.execute(
                        """INSERT OR IGNORE INTO dynamic_config
                           (key, value, value_type, description, tenant_id, updated_at)
                           VALUES (?, ?, ?, ?, '', ?)""",
                        (key, json.dumps(info["value"]), info["type"],
                         info["desc"], now),
                    )
                conn.commit()
        except sqlite3.Error:
            pass

    def _refresh_cache(self) -> None:
        """Reload global config into memory."""
        with self._lock:
            try:
                with self._conn() as conn:
                    rows = conn.execute(
                        "SELECT key, value, value_type FROM dynamic_config WHERE tenant_id = ''"
                    ).fetchall()
                    self._cache = {
                        r["key"]: self._cast(r["value"], r["value_type"])
                        for r in rows
                    }
            except sqlite3.Error:
                pass

    # ─── Read ──────────────────────────────────────────────────────

    def get(self, key: str, tenant_id: str = "", default: Any = None) -> Any:
        """
        Get a config value. Checks tenant override first, then global.

        Args:
            key: Config key (e.g. "rate_limit.free.requests_per_minute").
            tenant_id: Optional tenant for per-tenant override.
            default: Fallback if key not found.

        Returns:
            The config value, cast to its stored type.
        """
        # Check tenant override
        if tenant_id:
            tenant_val = self._get_tenant_value(key, tenant_id)
            if tenant_val is not None:
                return tenant_val

        # Check global cache
        with self._lock:
            return self._cache.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        """Get all global config values."""
        with self._lock:
            return dict(self._cache)

    def get_tenant_overrides(self, tenant_id: str) -> Dict[str, Any]:
        """Get all config overrides for a specific tenant."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT key, value, value_type FROM dynamic_config WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchall()
                return {
                    r["key"]: self._cast(r["value"], r["value_type"])
                    for r in rows
                }
        except sqlite3.Error:
            return {}

    # ─── Write ─────────────────────────────────────────────────────

    def set(
        self,
        key: str,
        value: Any,
        value_type: str = "str",
        tenant_id: str = "",
        updated_by: str = "system",
        description: str = "",
    ) -> None:
        """
        Set a config value.

        Args:
            key: Config key.
            value: New value.
            value_type: Type hint ("int", "float", "str", "bool", "json").
            tenant_id: Empty for global, or tenant ID for override.
            updated_by: Who made the change (for audit).
            description: Optional description update.
        """
        now = datetime.utcnow().isoformat()
        serialized = json.dumps(value)

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO dynamic_config
                       (key, value, value_type, description, tenant_id, updated_at, updated_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(key, tenant_id) DO UPDATE SET
                       value = excluded.value, value_type = excluded.value_type,
                       updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
                    (key, serialized, value_type, description, tenant_id, now, updated_by),
                )
                conn.commit()

            # Invalidate cache
            if not tenant_id:
                self._refresh_cache()
            else:
                with self._lock:
                    self._tenant_cache.pop(tenant_id, None)

            logger.info(
                f"[DynamicConfig] Set {key}={value} "
                f"(tenant={tenant_id or 'global'}, by={updated_by})"
            )

        except sqlite3.Error as e:
            logger.error(f"[DynamicConfig] Set error: {e}")
            raise

    def delete(self, key: str, tenant_id: str = "") -> bool:
        """Delete a config entry (only per-tenant overrides can be deleted)."""
        if not tenant_id:
            return False  # Don't allow deleting globals

        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "DELETE FROM dynamic_config WHERE key = ? AND tenant_id = ?",
                    (key, tenant_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error:
            return False

    # ─── History ───────────────────────────────────────────────────

    def list_config(self, tenant_id: str = "") -> List[Dict[str, Any]]:
        """List all config entries with metadata."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT key, value, value_type, description,
                              tenant_id, updated_at, updated_by
                       FROM dynamic_config
                       WHERE tenant_id = ?
                       ORDER BY key""",
                    (tenant_id,),
                ).fetchall()
                return [
                    {
                        **dict(r),
                        "value": self._cast(r["value"], r["value_type"]),
                    }
                    for r in rows
                ]
        except sqlite3.Error:
            return []

    # ─── Internal ──────────────────────────────────────────────────

    def _get_tenant_value(self, key: str, tenant_id: str) -> Optional[Any]:
        """Check for a tenant-specific override."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT value, value_type FROM dynamic_config WHERE key = ? AND tenant_id = ?",
                    (key, tenant_id),
                ).fetchone()
                if row:
                    return self._cast(row["value"], row["value_type"])
        except sqlite3.Error:
            pass
        return None

    @staticmethod
    def _cast(value: str, value_type: str) -> Any:
        """Cast a stored JSON string to the correct Python type."""
        parsed = json.loads(value)
        if value_type == "int":
            return int(parsed)
        elif value_type == "float":
            return float(parsed)
        elif value_type == "bool":
            return bool(parsed)
        elif value_type == "json":
            return parsed  # Already parsed
        return str(parsed)
