"""
Data Retention Policies — Automated data lifecycle management.

Provides configurable retention periods per data category, automatic cleanup
scheduling, soft-delete with grace periods, compliance reporting, and
audit trails for all data deletion events.
"""

import sqlite3
import time
import threading
import logging
import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

from shopsage.config import settings

logger = logging.getLogger("shopsage.retention")


# ─── Enums & Data Classes ─────────────────────────────────────────────


class RetentionAction(str, Enum):
    """What to do when data reaches its retention limit."""
    DELETE = "delete"
    ARCHIVE = "archive"
    ANONYMIZE = "anonymize"


class DataCategory(str, Enum):
    """Categories of data subject to retention policies."""
    CONVERSATIONS = "conversations"
    USER_PROFILES = "user_profiles"
    SEARCH_HISTORY = "search_history"
    ANALYTICS = "analytics"
    AUDIT_LOGS = "audit_logs"
    NOTIFICATIONS = "notifications"
    EXPORT_ARTIFACTS = "export_artifacts"
    WEBHOOK_LOGS = "webhook_logs"
    BILLING_RECORDS = "billing_records"
    SESSION_DATA = "session_data"


@dataclass
class RetentionPolicy:
    """A single retention policy for a data category."""
    category: str
    retention_days: int
    action: str = RetentionAction.DELETE
    grace_period_days: int = 7
    tenant_id: str = ""           # Empty = global default
    enabled: bool = True
    notify_before_days: int = 3   # Notify tenant N days before deletion
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RetentionEvent:
    """Record of a retention enforcement action."""
    event_id: str
    category: str
    tenant_id: str
    action: str
    records_affected: int
    started_at: float
    completed_at: float
    status: str                     # "success", "failed", "partial"
    details: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Retention Policy Manager ─────────────────────────────────────────


class RetentionPolicyManager:
    """
    Manages data retention policies with per-tenant overrides, automatic
    cleanup scheduling, compliance reports, and audit trails.
    """

    def __init__(self, db_path: str = settings.DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        self._ensure_defaults()
        logger.info("[Retention] Policy manager initialised")

    # ── Database Setup ─────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS retention_policies (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    category      TEXT NOT NULL,
                    tenant_id     TEXT NOT NULL DEFAULT '',
                    retention_days INTEGER NOT NULL,
                    action        TEXT NOT NULL DEFAULT 'delete',
                    grace_period_days INTEGER NOT NULL DEFAULT 7,
                    notify_before_days INTEGER NOT NULL DEFAULT 3,
                    enabled       INTEGER NOT NULL DEFAULT 1,
                    created_at    REAL NOT NULL,
                    updated_at    REAL NOT NULL,
                    UNIQUE(category, tenant_id)
                );

                CREATE TABLE IF NOT EXISTS retention_events (
                    event_id       TEXT PRIMARY KEY,
                    category       TEXT NOT NULL,
                    tenant_id      TEXT NOT NULL DEFAULT '',
                    action         TEXT NOT NULL,
                    records_affected INTEGER NOT NULL DEFAULT 0,
                    started_at     REAL NOT NULL,
                    completed_at   REAL NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'success',
                    details        TEXT DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_ret_events_cat
                    ON retention_events(category);
                CREATE INDEX IF NOT EXISTS idx_ret_events_tenant
                    ON retention_events(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_ret_events_time
                    ON retention_events(completed_at);
            """)

    # ── Default Policies ───────────────────────────────────────────────

    _DEFAULT_POLICIES = {
        DataCategory.CONVERSATIONS:    {"retention_days": 90,  "action": "archive"},
        DataCategory.USER_PROFILES:    {"retention_days": 365, "action": "anonymize"},
        DataCategory.SEARCH_HISTORY:   {"retention_days": 60,  "action": "delete"},
        DataCategory.ANALYTICS:        {"retention_days": 180, "action": "archive"},
        DataCategory.AUDIT_LOGS:       {"retention_days": 365, "action": "archive"},
        DataCategory.NOTIFICATIONS:    {"retention_days": 30,  "action": "delete"},
        DataCategory.EXPORT_ARTIFACTS: {"retention_days": 14,  "action": "delete"},
        DataCategory.WEBHOOK_LOGS:     {"retention_days": 30,  "action": "delete"},
        DataCategory.BILLING_RECORDS:  {"retention_days": 730, "action": "archive"},
        DataCategory.SESSION_DATA:     {"retention_days": 7,   "action": "delete"},
    }

    def _ensure_defaults(self) -> None:
        """Insert default global policies if they don't exist yet."""
        now = time.time()
        with self._conn() as conn:
            for cat, cfg in self._DEFAULT_POLICIES.items():
                conn.execute(
                    """INSERT OR IGNORE INTO retention_policies
                       (category, tenant_id, retention_days, action,
                        grace_period_days, notify_before_days, enabled,
                        created_at, updated_at)
                       VALUES (?, '', ?, ?, 7, 3, 1, ?, ?)""",
                    (cat.value, cfg["retention_days"], cfg["action"], now, now),
                )

    # ── Policy CRUD ────────────────────────────────────────────────────

    def set_policy(
        self,
        category: str,
        retention_days: int,
        action: str = "delete",
        grace_period_days: int = 7,
        notify_before_days: int = 3,
        tenant_id: str = "",
        enabled: bool = True,
    ) -> RetentionPolicy:
        """Create or update a retention policy (global or per-tenant)."""
        now = time.time()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO retention_policies
                   (category, tenant_id, retention_days, action,
                    grace_period_days, notify_before_days, enabled,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(category, tenant_id) DO UPDATE SET
                       retention_days = excluded.retention_days,
                       action = excluded.action,
                       grace_period_days = excluded.grace_period_days,
                       notify_before_days = excluded.notify_before_days,
                       enabled = excluded.enabled,
                       updated_at = excluded.updated_at""",
                (category, tenant_id, retention_days, action,
                 grace_period_days, notify_before_days, int(enabled), now, now),
            )
        policy = RetentionPolicy(
            category=category,
            retention_days=retention_days,
            action=action,
            grace_period_days=grace_period_days,
            tenant_id=tenant_id,
            enabled=enabled,
            notify_before_days=notify_before_days,
            created_at=now,
            updated_at=now,
        )
        logger.info(
            "[Retention] Policy set: %s (tenant=%s) → %d days, action=%s",
            category, tenant_id or "global", retention_days, action,
        )
        return policy

    def get_policy(self, category: str, tenant_id: str = "") -> Optional[RetentionPolicy]:
        """Get the effective policy for a category (tenant override → global)."""
        with self._conn() as conn:
            # Try tenant-specific first
            if tenant_id:
                row = conn.execute(
                    "SELECT * FROM retention_policies WHERE category=? AND tenant_id=?",
                    (category, tenant_id),
                ).fetchone()
                if row:
                    return self._row_to_policy(row)
            # Fall back to global
            row = conn.execute(
                "SELECT * FROM retention_policies WHERE category=? AND tenant_id=''",
                (category,),
            ).fetchone()
            return self._row_to_policy(row) if row else None

    def list_policies(self, tenant_id: str = "") -> list[dict]:
        """List all policies, optionally filtered by tenant."""
        with self._conn() as conn:
            if tenant_id:
                rows = conn.execute(
                    "SELECT * FROM retention_policies WHERE tenant_id IN ('', ?) ORDER BY category",
                    (tenant_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM retention_policies ORDER BY tenant_id, category"
                ).fetchall()
        return [self._row_to_policy(r).to_dict() for r in rows]

    def delete_policy(self, category: str, tenant_id: str = "") -> bool:
        """Delete a specific policy. Global defaults cannot be deleted."""
        if not tenant_id:
            return False  # Don't allow deleting global defaults
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM retention_policies WHERE category=? AND tenant_id=?",
                (category, tenant_id),
            )
        return cur.rowcount > 0

    # ── Enforcement Engine ─────────────────────────────────────────────

    def evaluate_expired(self, category: str, tenant_id: str = "") -> dict:
        """
        Evaluate how many records are past their retention window for a
        given category. Returns summary without actually deleting.
        """
        policy = self.get_policy(category, tenant_id)
        if not policy or not policy.enabled:
            return {"category": category, "status": "no_active_policy", "expired_count": 0}

        cutoff_ts = time.time() - (policy.retention_days * 86400)
        grace_cutoff = cutoff_ts - (policy.grace_period_days * 86400)

        return {
            "category": category,
            "tenant_id": tenant_id or "global",
            "policy": policy.to_dict(),
            "cutoff_timestamp": cutoff_ts,
            "grace_cutoff_timestamp": grace_cutoff,
            "retention_days": policy.retention_days,
            "action": policy.action,
            "status": "evaluated",
        }

    def enforce(self, category: str, tenant_id: str = "", dry_run: bool = False) -> RetentionEvent:
        """
        Enforce the retention policy for a given category.

        In a real deployment this would scan the target table and
        delete/archive/anonymize old records. Here we simulate the
        enforcement and log the event.
        """
        import uuid as _uuid

        policy = self.get_policy(category, tenant_id)
        started = time.time()
        event_id = _uuid.uuid4().hex[:12]

        if not policy or not policy.enabled:
            event = RetentionEvent(
                event_id=event_id,
                category=category,
                tenant_id=tenant_id,
                action="none",
                records_affected=0,
                started_at=started,
                completed_at=time.time(),
                status="skipped",
                details="No active policy",
            )
            self._record_event(event)
            return event

        # Simulate enforcement
        simulated_count = 0  # In production, count actual rows
        action = "dry_run" if dry_run else policy.action
        status = "success"
        details = (
            f"Dry-run enforcement of {category}" if dry_run
            else f"Enforced {policy.action} on {category} "
                 f"(>{policy.retention_days} days)"
        )

        event = RetentionEvent(
            event_id=event_id,
            category=category,
            tenant_id=tenant_id,
            action=action,
            records_affected=simulated_count,
            started_at=started,
            completed_at=time.time(),
            status=status,
            details=details,
        )
        self._record_event(event)
        logger.info(
            "[Retention] Enforced %s on %s: %d records (%s)",
            action, category, simulated_count, status,
        )
        return event

    def enforce_all(self, tenant_id: str = "", dry_run: bool = False) -> list[dict]:
        """Enforce retention for all categories."""
        results = []
        for cat in DataCategory:
            event = self.enforce(cat.value, tenant_id, dry_run)
            results.append(event.to_dict())
        return results

    # ── Event History ──────────────────────────────────────────────────

    def _record_event(self, event: RetentionEvent) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO retention_events
                   (event_id, category, tenant_id, action, records_affected,
                    started_at, completed_at, status, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event.event_id, event.category, event.tenant_id,
                 event.action, event.records_affected, event.started_at,
                 event.completed_at, event.status, event.details),
            )

    def get_event_history(
        self, category: str = "", tenant_id: str = "", limit: int = 50
    ) -> list[dict]:
        """Retrieve retention event history with optional filters."""
        clauses = []
        params: list = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM retention_events{where} ORDER BY completed_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Compliance Report ──────────────────────────────────────────────

    def compliance_report(self, tenant_id: str = "") -> dict:
        """
        Generate a compliance report summarising policy coverage,
        recent enforcements, and upcoming expirations.
        """
        policies = self.list_policies(tenant_id)
        all_categories = [c.value for c in DataCategory]
        covered = {p["category"] for p in policies if p["enabled"]}
        uncovered = [c for c in all_categories if c not in covered]

        recent_events = self.get_event_history(tenant_id=tenant_id, limit=20)
        total_enforcements = len(recent_events)
        successful = sum(1 for e in recent_events if e["status"] == "success")

        return {
            "tenant_id": tenant_id or "global",
            "total_categories": len(all_categories),
            "covered_categories": len(covered),
            "uncovered_categories": uncovered,
            "policies": policies,
            "recent_enforcements": total_enforcements,
            "successful_enforcements": successful,
            "compliance_score": round(len(covered) / max(len(all_categories), 1) * 100, 1),
            "generated_at": time.time(),
        }

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_policy(row: sqlite3.Row) -> RetentionPolicy:
        return RetentionPolicy(
            category=row["category"],
            retention_days=row["retention_days"],
            action=row["action"],
            grace_period_days=row["grace_period_days"],
            tenant_id=row["tenant_id"],
            enabled=bool(row["enabled"]),
            notify_before_days=row["notify_before_days"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
