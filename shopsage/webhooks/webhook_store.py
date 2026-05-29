"""
Webhook Store — SQLite-backed registration for tenant webhook endpoints.

Tenants can register URLs to receive POST callbacks when events occur
(price alerts, order updates, system notifications). Each webhook
has an optional secret for HMAC signature verification.

Schema:
    webhooks: id, tenant_id, url, events (JSON list), secret, is_active, created_at
    webhook_logs: id, webhook_id, event_type, status_code, response_time_ms, created_at
"""

import sqlite3
import uuid
import json
import secrets
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.webhooks.store")


@dataclass
class Webhook:
    """A registered webhook endpoint."""
    id: str
    tenant_id: str
    url: str
    events: List[str]         # e.g. ["price_alert", "order_update"]
    secret: str               # HMAC signing secret
    is_active: bool = True
    created_at: str = ""
    delivery_count: int = 0
    failure_count: int = 0


class WebhookStore:
    """
    SQLite store for webhook registrations and delivery logs.

    Supports:
    - Tenant-scoped webhook CRUD
    - Event type filtering (subscribe to specific events)
    - HMAC secret auto-generation
    - Delivery logging with status codes
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create webhooks and webhook_logs tables."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS webhooks (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        url TEXT NOT NULL,
                        events TEXT NOT NULL DEFAULT '[]',
                        secret TEXT NOT NULL,
                        is_active INTEGER DEFAULT 1,
                        delivery_count INTEGER DEFAULT 0,
                        failure_count INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS webhook_logs (
                        id TEXT PRIMARY KEY,
                        webhook_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload TEXT,
                        status_code INTEGER,
                        response_time_ms REAL,
                        error TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (webhook_id) REFERENCES webhooks(id)
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_wh_tenant
                    ON webhooks(tenant_id, is_active)
                """)
                conn.commit()
            logger.info("[WebhookStore] Initialized")
        except sqlite3.Error as e:
            logger.error(f"[WebhookStore] Init error: {e}")
            raise

    # ─── CRUD ──────────────────────────────────────────────────────

    def register(
        self,
        tenant_id: str,
        url: str,
        events: Optional[List[str]] = None,
    ) -> Webhook:
        """
        Register a new webhook endpoint for a tenant.

        Args:
            tenant_id: Owning tenant's ID.
            url: The HTTPS endpoint to POST events to.
            events: List of event types to subscribe to.
                    None = subscribe to all events.

        Returns:
            The created Webhook with auto-generated ID and secret.
        """
        webhook = Webhook(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            url=url,
            events=events or ["*"],
            secret=secrets.token_hex(32),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO webhooks
                       (id, tenant_id, url, events, secret, is_active, delivery_count, failure_count, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (webhook.id, webhook.tenant_id, webhook.url,
                     json.dumps(webhook.events), webhook.secret,
                     1, 0, 0, webhook.created_at),
                )
                conn.commit()

            logger.info(
                f"[WebhookStore] Registered webhook {webhook.id[:8]} "
                f"for tenant {tenant_id[:8]} → {url}"
            )
            return webhook

        except sqlite3.Error as e:
            logger.error(f"[WebhookStore] Register error: {e}")
            raise

    def get_by_tenant(self, tenant_id: str, active_only: bool = True) -> List[Webhook]:
        """Get all webhooks for a tenant."""
        try:
            with self._conn() as conn:
                query = "SELECT * FROM webhooks WHERE tenant_id = ?"
                params: list = [tenant_id]
                if active_only:
                    query += " AND is_active = 1"
                rows = conn.execute(query, params).fetchall()
                return [self._row_to_webhook(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[WebhookStore] Get error: {e}")
            return []

    def get_subscribers(self, event_type: str) -> List[Webhook]:
        """
        Get all active webhooks subscribed to a specific event type.

        Webhooks with events=["*"] match all events.
        """
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM webhooks WHERE is_active = 1"
                ).fetchall()

                subscribers = []
                for r in rows:
                    wh = self._row_to_webhook(r)
                    if "*" in wh.events or event_type in wh.events:
                        subscribers.append(wh)
                return subscribers

        except sqlite3.Error as e:
            logger.error(f"[WebhookStore] Subscribers error: {e}")
            return []

    def deactivate(self, webhook_id: str, tenant_id: str) -> bool:
        """Deactivate a webhook. Returns True if found and updated."""
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "UPDATE webhooks SET is_active = 0 WHERE id = ? AND tenant_id = ?",
                    (webhook_id, tenant_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"[WebhookStore] Deactivate error: {e}")
            return False

    def log_delivery(
        self,
        webhook_id: str,
        event_type: str,
        payload: str,
        status_code: Optional[int],
        response_time_ms: float,
        error: Optional[str] = None,
    ) -> None:
        """Log a webhook delivery attempt."""
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO webhook_logs
                       (id, webhook_id, event_type, payload, status_code, response_time_ms, error, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), webhook_id, event_type,
                     payload[:2000], status_code, response_time_ms,
                     error, datetime.now(timezone.utc).isoformat()),
                )

                # Update counters
                if status_code and 200 <= status_code < 300:
                    conn.execute(
                        "UPDATE webhooks SET delivery_count = delivery_count + 1 WHERE id = ?",
                        (webhook_id,),
                    )
                else:
                    conn.execute(
                        "UPDATE webhooks SET failure_count = failure_count + 1 WHERE id = ?",
                        (webhook_id,),
                    )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"[WebhookStore] Log delivery error: {e}")

    def get_delivery_logs(
        self, webhook_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get recent delivery logs for a webhook."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM webhook_logs
                       WHERE webhook_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (webhook_id, limit),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[WebhookStore] Get logs error: {e}")
            return []

    def _row_to_webhook(self, row: sqlite3.Row) -> Webhook:
        """Convert a database row to a Webhook dataclass."""
        d = dict(row)
        d["events"] = json.loads(d.get("events", "[]"))
        d["is_active"] = bool(d.get("is_active", 1))
        return Webhook(**{k: d[k] for k in Webhook.__dataclass_fields__})
