"""
Audit Log — Immutable compliance trail for ShopSage AI.

Records every sensitive action (tenant CRUD, plan changes, API key
rotations, webhook modifications, billing events) with actor identity,
IP address, and request metadata.

Schema:
    audit_log: id, timestamp, actor_id, actor_type, action, resource_type,
               resource_id, details, ip_address, user_agent
"""

import sqlite3
import uuid
import json
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.security.audit")


@dataclass
class AuditEntry:
    """A single audit log entry."""
    id: str
    timestamp: str
    actor_id: str           # tenant_id or "system"
    actor_type: str         # "tenant", "admin", "system", "api_key"
    action: str             # "create", "update", "delete", "login", "export"
    resource_type: str      # "tenant", "webhook", "api_key", "billing"
    resource_id: str        # ID of the affected resource
    details: str            # JSON string with additional context
    ip_address: str
    user_agent: str


class AuditLog:
    """
    Append-only audit trail for compliance and forensics.

    All entries are immutable once written — there is no update
    or delete operation by design.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create audit_log table (append-only)."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        actor_type TEXT NOT NULL,
                        action TEXT NOT NULL,
                        resource_type TEXT NOT NULL,
                        resource_id TEXT DEFAULT '',
                        details TEXT DEFAULT '{}',
                        ip_address TEXT DEFAULT '',
                        user_agent TEXT DEFAULT ''
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_actor
                    ON audit_log(actor_id, timestamp)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_action
                    ON audit_log(action, resource_type, timestamp)
                """)
                conn.commit()
            logger.info("[AuditLog] Initialized")
        except sqlite3.Error as e:
            logger.error(f"[AuditLog] Init error: {e}")
            raise

    # ─── Write ─────────────────────────────────────────────────────

    def record(
        self,
        actor_id: str,
        actor_type: str,
        action: str,
        resource_type: str,
        resource_id: str = "",
        details: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
        user_agent: str = "",
    ) -> AuditEntry:
        """
        Record an audit event.

        Args:
            actor_id: Who performed the action (tenant ID, admin ID, or "system").
            actor_type: Category of actor ("tenant", "admin", "system").
            action: What happened ("create", "update", "delete", "login", "export").
            resource_type: Type of resource affected ("tenant", "webhook", "api_key").
            resource_id: ID of the specific resource.
            details: Additional JSON-serializable context.
            ip_address: Client IP address.
            user_agent: Client User-Agent string.

        Returns:
            The created AuditEntry.
        """
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details or {}, default=str),
            ip_address=ip_address,
            user_agent=user_agent,
        )

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO audit_log
                       (id, timestamp, actor_id, actor_type, action,
                        resource_type, resource_id, details, ip_address, user_agent)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (entry.id, entry.timestamp, entry.actor_id,
                     entry.actor_type, entry.action, entry.resource_type,
                     entry.resource_id, entry.details, entry.ip_address,
                     entry.user_agent),
                )
                conn.commit()

            logger.info(
                f"[Audit] {entry.actor_type}:{entry.actor_id[:8]} "
                f"{entry.action} {entry.resource_type}:{entry.resource_id[:8]}"
            )
            return entry

        except sqlite3.Error as e:
            logger.error(f"[AuditLog] Record error: {e}")
            raise

    # ─── Read ──────────────────────────────────────────────────────

    def get_by_actor(
        self, actor_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get audit entries for a specific actor."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM audit_log
                       WHERE actor_id = ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (actor_id, limit),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[AuditLog] Get by actor error: {e}")
            return []

    def get_by_resource(
        self, resource_type: str, resource_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get audit entries for a specific resource."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM audit_log
                       WHERE resource_type = ? AND resource_id = ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (resource_type, resource_id, limit),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[AuditLog] Get by resource error: {e}")
            return []

    def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get the most recent audit entries (admin view)."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[AuditLog] Get recent error: {e}")
            return []

    def search(
        self,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search audit log by action and/or resource type."""
        try:
            conditions = []
            params: list = []

            if action:
                conditions.append("action = ?")
                params.append(action)
            if resource_type:
                conditions.append("resource_type = ?")
                params.append(resource_type)

            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            params.append(limit)

            with self._conn() as conn:
                rows = conn.execute(
                    f"SELECT * FROM audit_log {where} ORDER BY timestamp DESC LIMIT ?",
                    params,
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[AuditLog] Search error: {e}")
            return []

    def count_actions(self, hours: int = 24) -> Dict[str, int]:
        """Count actions by type in the last N hours."""
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT action, COUNT(*) as count
                       FROM audit_log WHERE timestamp > ?
                       GROUP BY action ORDER BY count DESC""",
                    (cutoff,),
                ).fetchall()
                return {r["action"]: r["count"] for r in rows}
        except sqlite3.Error as e:
            logger.error(f"[AuditLog] Count error: {e}")
            return {}
