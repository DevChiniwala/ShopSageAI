"""
API Key Manager — Secure key lifecycle management for ShopSage AI.

Handles key rotation with grace periods, key revocation,
and key metadata (last used, usage count, expiry).

Schema:
    api_keys: id, tenant_id, key_hash, key_prefix, label,
              is_active, expires_at, last_used_at, usage_count, created_at
"""

import sqlite3
import uuid
import secrets
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.auth.key_manager")


def _hash_key(key: str) -> str:
    """SHA-256 hash for secure key storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def _key_prefix(key: str) -> str:
    """Extract visible prefix: sk-abc...xyz"""
    if len(key) > 12:
        return f"{key[:6]}...{key[-4:]}"
    return key[:4] + "..."


class APIKeyManager:
    """
    Manages API key lifecycle with rotation and grace periods.

    Supports:
    - Multiple active keys per tenant (for zero-downtime rotation)
    - Grace periods during rotation (old key stays valid)
    - Key expiration dates
    - Last-used tracking
    - Revocation
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create api_keys table."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        key_hash TEXT NOT NULL,
                        key_prefix TEXT NOT NULL,
                        label TEXT DEFAULT 'default',
                        is_active INTEGER DEFAULT 1,
                        expires_at TEXT,
                        last_used_at TEXT,
                        usage_count INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_apikey_hash
                    ON api_keys(key_hash, is_active)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_apikey_tenant
                    ON api_keys(tenant_id, is_active)
                """)
                conn.commit()
            logger.info("[APIKeyManager] Initialized")
        except sqlite3.Error as e:
            logger.error(f"[APIKeyManager] Init error: {e}")
            raise

    # ─── Key Generation ────────────────────────────────────────────

    def create_key(
        self,
        tenant_id: str,
        label: str = "default",
        expires_in_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generate a new API key for a tenant.

        Args:
            tenant_id: Owning tenant.
            label: Human-readable label (e.g. "production", "staging").
            expires_in_days: Optional expiration. None = never expires.

        Returns:
            Dict with the raw key (only shown once!) and metadata.
        """
        raw_key = f"sk-{secrets.token_urlsafe(40)}"
        key_hash = _hash_key(raw_key)
        prefix = _key_prefix(raw_key)
        now = datetime.now(timezone.utc).isoformat()

        expires_at = None
        if expires_in_days:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()

        key_id = str(uuid.uuid4())

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO api_keys
                       (id, tenant_id, key_hash, key_prefix, label,
                        is_active, expires_at, usage_count, created_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, 0, ?)""",
                    (key_id, tenant_id, key_hash, prefix, label, expires_at, now),
                )
                conn.commit()

            logger.info(
                f"[APIKeyManager] Created key {prefix} for tenant {tenant_id[:8]} "
                f"(label={label})"
            )

            return {
                "id": key_id,
                "key": raw_key,           # Only returned on creation!
                "prefix": prefix,
                "label": label,
                "tenant_id": tenant_id,
                "expires_at": expires_at,
                "created_at": now,
            }

        except sqlite3.Error as e:
            logger.error(f"[APIKeyManager] Create error: {e}")
            raise

    # ─── Key Rotation ──────────────────────────────────────────────

    def rotate_key(
        self,
        tenant_id: str,
        old_key_id: str,
        grace_period_hours: int = 24,
        label: str = "rotated",
    ) -> Dict[str, Any]:
        """
        Rotate an API key with a grace period.

        1. Creates a new key
        2. Sets the old key to expire after grace_period_hours
        3. Both keys are valid during the grace period

        Args:
            tenant_id: Owning tenant.
            old_key_id: ID of the key being rotated.
            grace_period_hours: Hours the old key remains valid.
            label: Label for the new key.

        Returns:
            The new key dict.
        """
        # Set old key expiration
        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=grace_period_hours)
        ).isoformat()

        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE api_keys SET expires_at = ? WHERE id = ? AND tenant_id = ?",
                    (expires_at, old_key_id, tenant_id),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"[APIKeyManager] Rotation expire error: {e}")
            raise

        # Create new key
        new_key = self.create_key(tenant_id, label=label)

        logger.info(
            f"[APIKeyManager] Rotated key for tenant {tenant_id[:8]}: "
            f"old expires in {grace_period_hours}h"
        )

        return new_key

    # ─── Validation ────────────────────────────────────────────────

    def validate_key(self, raw_key: str) -> Optional[Dict[str, Any]]:
        """
        Validate an API key and return its metadata if valid.

        Checks:
        - Key exists and is active
        - Key has not expired
        - Updates last_used_at and usage_count
        """
        key_hash = _hash_key(raw_key)
        now = datetime.now(timezone.utc).isoformat()

        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM api_keys WHERE key_hash = ? AND is_active = 1",
                    (key_hash,),
                ).fetchone()

                if not row:
                    return None

                data = dict(row)

                # Check expiration
                if data["expires_at"] and data["expires_at"] < now:
                    # Expired — deactivate
                    conn.execute(
                        "UPDATE api_keys SET is_active = 0 WHERE id = ?",
                        (data["id"],),
                    )
                    conn.commit()
                    logger.info(f"[APIKeyManager] Key {data['key_prefix']} expired")
                    return None

                # Update usage tracking
                conn.execute(
                    """UPDATE api_keys SET
                       last_used_at = ?, usage_count = usage_count + 1
                       WHERE id = ?""",
                    (now, data["id"]),
                )
                conn.commit()

                return {
                    "id": data["id"],
                    "tenant_id": data["tenant_id"],
                    "prefix": data["key_prefix"],
                    "label": data["label"],
                    "expires_at": data["expires_at"],
                    "usage_count": data["usage_count"] + 1,
                }

        except sqlite3.Error as e:
            logger.error(f"[APIKeyManager] Validate error: {e}")
            return None

    # ─── Management ────────────────────────────────────────────────

    def revoke_key(self, key_id: str, tenant_id: str) -> bool:
        """Immediately revoke an API key."""
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "UPDATE api_keys SET is_active = 0 WHERE id = ? AND tenant_id = ?",
                    (key_id, tenant_id),
                )
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"[APIKeyManager] Revoked key {key_id[:8]}")
                    return True
                return False
        except sqlite3.Error as e:
            logger.error(f"[APIKeyManager] Revoke error: {e}")
            return False

    def list_keys(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List all keys for a tenant (never exposes the actual key)."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT id, tenant_id, key_prefix, label, is_active,
                              expires_at, last_used_at, usage_count, created_at
                       FROM api_keys WHERE tenant_id = ?
                       ORDER BY created_at DESC""",
                    (tenant_id,),
                ).fetchall()
                return [
                    {**dict(r), "is_active": bool(r["is_active"])}
                    for r in rows
                ]
        except sqlite3.Error as e:
            logger.error(f"[APIKeyManager] List error: {e}")
            return []

    def get_active_count(self, tenant_id: str) -> int:
        """Count active keys for a tenant."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM api_keys WHERE tenant_id = ? AND is_active = 1",
                    (tenant_id,),
                ).fetchone()
                return row["cnt"]
        except sqlite3.Error:
            return 0
