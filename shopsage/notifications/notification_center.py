"""
Notification Center — Persistent in-app notifications for tenants.

Stores notifications in SQLite and exposes them via API so
the dashboard or mobile clients can display alerts.

Notifications are created by event handlers and marked as
read/dismissed by the user.

Schema:
    notifications: id, tenant_id, type, title, message, priority,
                   is_read, action_url, created_at
"""

import sqlite3
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.notifications.center")


class NotificationCenter:
    """
    SQLite-backed notification store for tenant-scoped alerts.

    Supports:
    - Priority levels (info, warning, critical)
    - Read/unread tracking
    - Batch operations (mark all read, purge old)
    - Action URLs for deep-linking
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create notifications table."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS notifications (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        message TEXT NOT NULL,
                        priority TEXT DEFAULT 'info',
                        is_read INTEGER DEFAULT 0,
                        action_url TEXT DEFAULT '',
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_notif_tenant
                    ON notifications(tenant_id, is_read, created_at)
                """)
                conn.commit()
            logger.info("[NotificationCenter] Initialized")
        except sqlite3.Error as e:
            logger.error(f"[NotificationCenter] Init error: {e}")
            raise

    # ─── Create ────────────────────────────────────────────────────

    def create(
        self,
        tenant_id: str,
        notification_type: str,
        title: str,
        message: str,
        priority: str = "info",
        action_url: str = "",
    ) -> Dict[str, Any]:
        """
        Create a new notification for a tenant.

        Args:
            tenant_id: Target tenant.
            notification_type: Category (e.g. "price_alert", "billing", "system").
            title: Short headline.
            message: Full notification body.
            priority: "info", "warning", or "critical".
            action_url: Optional deep-link URL.

        Returns:
            The created notification dict.
        """
        notif = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "type": notification_type,
            "title": title,
            "message": message,
            "priority": priority,
            "is_read": False,
            "action_url": action_url,
            "created_at": datetime.utcnow().isoformat(),
        }

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO notifications
                       (id, tenant_id, type, title, message, priority,
                        is_read, action_url, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                    (notif["id"], tenant_id, notification_type, title,
                     message, priority, action_url, notif["created_at"]),
                )
                conn.commit()

            logger.info(
                f"[Notification] {priority.upper()} for {tenant_id[:8]}: {title}"
            )
            return notif

        except sqlite3.Error as e:
            logger.error(f"[NotificationCenter] Create error: {e}")
            raise

    # ─── Read ──────────────────────────────────────────────────────

    def get_unread(
        self, tenant_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get unread notifications for a tenant, newest first."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM notifications
                       WHERE tenant_id = ? AND is_read = 0
                       ORDER BY created_at DESC LIMIT ?""",
                    (tenant_id, limit),
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[NotificationCenter] Get unread error: {e}")
            return []

    def get_all(
        self, tenant_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get all notifications for a tenant."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM notifications
                       WHERE tenant_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (tenant_id, limit),
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[NotificationCenter] Get all error: {e}")
            return []

    def get_unread_count(self, tenant_id: str) -> int:
        """Get the count of unread notifications."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM notifications WHERE tenant_id = ? AND is_read = 0",
                    (tenant_id,),
                ).fetchone()
                return row["cnt"]
        except sqlite3.Error as e:
            logger.error(f"[NotificationCenter] Count error: {e}")
            return 0

    # ─── Update ────────────────────────────────────────────────────

    def mark_read(self, notification_id: str, tenant_id: str) -> bool:
        """Mark a single notification as read."""
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "UPDATE notifications SET is_read = 1 WHERE id = ? AND tenant_id = ?",
                    (notification_id, tenant_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"[NotificationCenter] Mark read error: {e}")
            return False

    def mark_all_read(self, tenant_id: str) -> int:
        """Mark all notifications as read for a tenant. Returns count updated."""
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "UPDATE notifications SET is_read = 1 WHERE tenant_id = ? AND is_read = 0",
                    (tenant_id,),
                )
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as e:
            logger.error(f"[NotificationCenter] Mark all read error: {e}")
            return 0

    # ─── Cleanup ───────────────────────────────────────────────────

    def purge_old(self, days: int = 30) -> int:
        """Delete notifications older than N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "DELETE FROM notifications WHERE created_at < ? AND is_read = 1",
                    (cutoff,),
                )
                conn.commit()
                deleted = cursor.rowcount
                if deleted:
                    logger.info(f"[NotificationCenter] Purged {deleted} old notifications")
                return deleted
        except sqlite3.Error as e:
            logger.error(f"[NotificationCenter] Purge error: {e}")
            return 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["is_read"] = bool(d.get("is_read", 0))
        return d
