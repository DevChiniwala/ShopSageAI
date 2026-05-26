"""
Feature Flags — Per-tenant feature toggling for ShopSage AI.

Enables gradual rollouts, A/B experiments, and plan-gated features
without redeployments.

Schema:
    feature_flags: id, flag_key, description, default_enabled, created_at
    tenant_flags: tenant_id, flag_key, enabled, updated_at

Design:
    - Each flag has a global default (on/off).
    - Per-tenant overrides take precedence over defaults.
    - Plan-based rules: e.g. 'visual_search' only for pro+.
    - Thread-safe with in-memory cache for hot-path lookups.
"""

import sqlite3
import uuid
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Set

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.config.feature_flags")

# Built-in plan-gated flags: flag_key -> minimum required plan
PLAN_GATED_FLAGS = {
    "visual_search": "pro",
    "webhook_integrations": "pro",
    "advanced_analytics": "pro",
    "custom_branding": "enterprise",
    "priority_support": "enterprise",
    "bulk_export": "pro",
    "api_access": "pro",
    "multi_language": "free",       # available to all
    "price_alerts": "free",        # available to all
    "conversation_history": "free", # available to all
}

PLAN_HIERARCHY = {"free": 0, "pro": 1, "enterprise": 2}


class FeatureFlagStore:
    """
    SQLite-backed feature flag system with per-tenant overrides.

    Supports:
    - Global flags with defaults
    - Per-tenant overrides
    - Plan-gated features
    - In-memory cache for performance
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._cache: Dict[str, Dict[str, bool]] = {}  # tenant_id -> {flag: enabled}
        self._global_cache: Dict[str, bool] = {}
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables and seed default flags."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS feature_flags (
                        flag_key TEXT PRIMARY KEY,
                        description TEXT DEFAULT '',
                        default_enabled INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tenant_flags (
                        tenant_id TEXT NOT NULL,
                        flag_key TEXT NOT NULL,
                        enabled INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, flag_key)
                    )
                """)
                conn.commit()

            # Seed built-in flags
            self._seed_defaults()
            self._refresh_global_cache()

            logger.info("[FeatureFlags] Initialized")
        except sqlite3.Error as e:
            logger.error(f"[FeatureFlags] Init error: {e}")
            raise

    def _seed_defaults(self) -> None:
        """Insert default flags if they don't exist."""
        now = datetime.utcnow().isoformat()
        try:
            with self._conn() as conn:
                for key in PLAN_GATED_FLAGS:
                    conn.execute(
                        """INSERT OR IGNORE INTO feature_flags
                           (flag_key, description, default_enabled, created_at)
                           VALUES (?, ?, 1, ?)""",
                        (key, f"Plan-gated: {key.replace('_', ' ').title()}", now),
                    )
                conn.commit()
        except sqlite3.Error:
            pass

    def _refresh_global_cache(self) -> None:
        """Reload global defaults into memory."""
        with self._lock:
            try:
                with self._conn() as conn:
                    rows = conn.execute("SELECT flag_key, default_enabled FROM feature_flags").fetchall()
                    self._global_cache = {
                        r["flag_key"]: bool(r["default_enabled"]) for r in rows
                    }
            except sqlite3.Error:
                pass

    # ─── Core API ──────────────────────────────────────────────────

    def is_enabled(
        self,
        flag_key: str,
        tenant_id: str = "",
        tenant_plan: str = "free",
    ) -> bool:
        """
        Check if a feature flag is enabled for a tenant.

        Resolution order:
            1. Per-tenant override (if set)
            2. Plan-gated check (if flag is plan-gated)
            3. Global default

        Args:
            flag_key: The feature flag key.
            tenant_id: The tenant to check (empty = global default).
            tenant_plan: The tenant's billing plan.

        Returns:
            True if the feature is enabled.
        """
        # 1. Check tenant override
        if tenant_id:
            override = self._get_tenant_override(tenant_id, flag_key)
            if override is not None:
                return override

        # 2. Check plan gate
        if flag_key in PLAN_GATED_FLAGS:
            required_plan = PLAN_GATED_FLAGS[flag_key]
            if PLAN_HIERARCHY.get(tenant_plan, 0) < PLAN_HIERARCHY.get(required_plan, 0):
                return False

        # 3. Global default
        return self._global_cache.get(flag_key, False)

    def set_tenant_override(
        self, tenant_id: str, flag_key: str, enabled: bool
    ) -> None:
        """Set a per-tenant flag override."""
        now = datetime.utcnow().isoformat()
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO tenant_flags (tenant_id, flag_key, enabled, updated_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(tenant_id, flag_key) DO UPDATE SET
                       enabled = excluded.enabled, updated_at = excluded.updated_at""",
                    (tenant_id, flag_key, int(enabled), now),
                )
                conn.commit()

            # Invalidate cache
            with self._lock:
                self._cache.pop(tenant_id, None)

            logger.info(
                f"[FeatureFlags] Set {flag_key}={enabled} for tenant {tenant_id[:8]}"
            )
        except sqlite3.Error as e:
            logger.error(f"[FeatureFlags] Set override error: {e}")

    def remove_tenant_override(self, tenant_id: str, flag_key: str) -> bool:
        """Remove a per-tenant override (fall back to defaults)."""
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "DELETE FROM tenant_flags WHERE tenant_id = ? AND flag_key = ?",
                    (tenant_id, flag_key),
                )
                conn.commit()

            with self._lock:
                self._cache.pop(tenant_id, None)

            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"[FeatureFlags] Remove override error: {e}")
            return False

    def get_tenant_flags(
        self, tenant_id: str, tenant_plan: str = "free"
    ) -> Dict[str, bool]:
        """Get all flags resolved for a specific tenant."""
        result = {}
        for flag_key in self._global_cache:
            result[flag_key] = self.is_enabled(flag_key, tenant_id, tenant_plan)
        return result

    def create_flag(
        self, flag_key: str, description: str = "", default_enabled: bool = False
    ) -> bool:
        """Create a new global feature flag."""
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO feature_flags (flag_key, description, default_enabled, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (flag_key, description, int(default_enabled),
                     datetime.utcnow().isoformat()),
                )
                conn.commit()
            self._refresh_global_cache()
            return True
        except sqlite3.IntegrityError:
            return False  # Already exists
        except sqlite3.Error as e:
            logger.error(f"[FeatureFlags] Create flag error: {e}")
            return False

    def list_flags(self) -> List[Dict[str, Any]]:
        """List all global feature flags."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM feature_flags ORDER BY flag_key"
                ).fetchall()
                return [
                    {**dict(r), "plan_gate": PLAN_GATED_FLAGS.get(r["flag_key"])}
                    for r in rows
                ]
        except sqlite3.Error as e:
            logger.error(f"[FeatureFlags] List error: {e}")
            return []

    # ─── Internal ──────────────────────────────────────────────────

    def _get_tenant_override(self, tenant_id: str, flag_key: str) -> Optional[bool]:
        """Check if a tenant has a specific override."""
        # Check cache first
        with self._lock:
            if tenant_id in self._cache:
                cached = self._cache[tenant_id]
                if flag_key in cached:
                    return cached[flag_key]

        # Query DB
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT enabled FROM tenant_flags WHERE tenant_id = ? AND flag_key = ?",
                    (tenant_id, flag_key),
                ).fetchone()

                if row is not None:
                    enabled = bool(row["enabled"])
                    # Update cache
                    with self._lock:
                        if tenant_id not in self._cache:
                            self._cache[tenant_id] = {}
                        self._cache[tenant_id][flag_key] = enabled
                    return enabled
        except sqlite3.Error:
            pass

        return None
