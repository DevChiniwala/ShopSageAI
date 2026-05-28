"""
Tenant Onboarding — Self-service registration and provisioning pipeline.

Handles tenant registration, welcome workflows, API key provisioning,
usage quota setup, onboarding checklists, and status tracking.
"""

import sqlite3
import time
import threading
import logging
import hashlib
import secrets
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

logger = logging.getLogger("shopsage.onboarding")


# ─── Enums & Data Classes ─────────────────────────────────────────────


class OnboardingStatus(str, Enum):
    """Stages in the tenant onboarding lifecycle."""
    PENDING = "pending"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class PlanTier(str, Enum):
    """Available subscription tiers."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


@dataclass
class TenantRegistration:
    """Represents a tenant registration request."""
    tenant_id: str
    company_name: str
    email: str
    plan: str = PlanTier.FREE
    status: str = OnboardingStatus.PENDING
    api_key: str = ""
    created_at: float = field(default_factory=time.time)
    activated_at: float = 0.0
    metadata: str = "{}"

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class OnboardingChecklistItem:
    """A single step in the onboarding checklist."""
    step_id: str
    tenant_id: str
    title: str
    description: str
    completed: bool = False
    completed_at: float = 0.0
    order: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Plan Quotas ───────────────────────────────────────────────────────

PLAN_QUOTAS = {
    PlanTier.FREE: {
        "requests_per_day": 100,
        "requests_per_minute": 10,
        "max_api_keys": 1,
        "max_webhooks": 2,
        "max_conversations_stored": 100,
        "features": ["chat", "search"],
    },
    PlanTier.STARTER: {
        "requests_per_day": 5000,
        "requests_per_minute": 50,
        "max_api_keys": 3,
        "max_webhooks": 5,
        "max_conversations_stored": 1000,
        "features": ["chat", "search", "analytics", "deal_alerts"],
    },
    PlanTier.PROFESSIONAL: {
        "requests_per_day": 50000,
        "requests_per_minute": 200,
        "max_api_keys": 10,
        "max_webhooks": 20,
        "max_conversations_stored": 10000,
        "features": [
            "chat", "search", "analytics", "deal_alerts",
            "visual_search", "export", "webhooks", "plugins",
        ],
    },
    PlanTier.ENTERPRISE: {
        "requests_per_day": 500000,
        "requests_per_minute": 1000,
        "max_api_keys": 50,
        "max_webhooks": 100,
        "max_conversations_stored": -1,  # unlimited
        "features": [
            "chat", "search", "analytics", "deal_alerts",
            "visual_search", "export", "webhooks", "plugins",
            "custom_models", "dedicated_support", "sla",
        ],
    },
}

DEFAULT_CHECKLIST = [
    ("verify_email", "Verify Email", "Confirm your email address to activate your account"),
    ("generate_api_key", "Generate API Key", "Create your first API key to start making requests"),
    ("first_api_call", "Make First API Call", "Send your first request to the ShopSage API"),
    ("configure_webhooks", "Set Up Webhooks", "Configure webhooks to receive real-time notifications"),
    ("explore_dashboard", "Explore Dashboard", "Visit the admin dashboard to view analytics"),
]


# ─── Onboarding Manager ───────────────────────────────────────────────


class OnboardingManager:
    """
    Manages the full tenant onboarding lifecycle: registration,
    provisioning, API key issuance, quota setup, and checklist tracking.
    """

    def __init__(self, db_path: str = "shopsage.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        logger.info("[Onboarding] Manager initialised")

    # ── Database Setup ─────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tenant_registrations (
                    tenant_id     TEXT PRIMARY KEY,
                    company_name  TEXT NOT NULL,
                    email         TEXT NOT NULL UNIQUE,
                    plan          TEXT NOT NULL DEFAULT 'free',
                    status        TEXT NOT NULL DEFAULT 'pending',
                    api_key       TEXT DEFAULT '',
                    created_at    REAL NOT NULL,
                    activated_at  REAL DEFAULT 0,
                    metadata      TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS onboarding_checklist (
                    step_id       TEXT NOT NULL,
                    tenant_id     TEXT NOT NULL,
                    title         TEXT NOT NULL,
                    description   TEXT DEFAULT '',
                    completed     INTEGER NOT NULL DEFAULT 0,
                    completed_at  REAL DEFAULT 0,
                    sort_order    INTEGER DEFAULT 0,
                    PRIMARY KEY (step_id, tenant_id)
                );

                CREATE TABLE IF NOT EXISTS onboarding_events (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id     TEXT NOT NULL,
                    event_type    TEXT NOT NULL,
                    details       TEXT DEFAULT '',
                    created_at    REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_onb_tenant
                    ON onboarding_events(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_onb_status
                    ON tenant_registrations(status);
            """)

    # ── Registration ───────────────────────────────────────────────────

    def register_tenant(
        self,
        company_name: str,
        email: str,
        plan: str = "free",
        metadata: Optional[dict] = None,
    ) -> TenantRegistration:
        """
        Register a new tenant. Generates a unique tenant ID, creates
        a provisional API key, and initialises the onboarding checklist.
        """
        # Generate deterministic tenant ID from email
        tenant_id = "tn_" + hashlib.sha256(email.encode()).hexdigest()[:12]
        api_key = "sk_" + secrets.token_urlsafe(32)
        now = time.time()
        meta_str = "{}" if metadata is None else __import__("json").dumps(metadata)

        with self._lock, self._conn() as conn:
            # Check for existing registration
            existing = conn.execute(
                "SELECT tenant_id FROM tenant_registrations WHERE email = ?",
                (email,),
            ).fetchone()
            if existing:
                raise ValueError(f"Email already registered: {email}")

            conn.execute(
                """INSERT INTO tenant_registrations
                   (tenant_id, company_name, email, plan, status,
                    api_key, created_at, activated_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (tenant_id, company_name, email, plan,
                 OnboardingStatus.PENDING, api_key, now, meta_str),
            )

            # Create onboarding checklist
            for i, (step_id, title, desc) in enumerate(DEFAULT_CHECKLIST):
                conn.execute(
                    """INSERT INTO onboarding_checklist
                       (step_id, tenant_id, title, description, completed,
                        completed_at, sort_order)
                       VALUES (?, ?, ?, ?, 0, 0, ?)""",
                    (step_id, tenant_id, title, desc, i),
                )

            # Log event
            conn.execute(
                """INSERT INTO onboarding_events
                   (tenant_id, event_type, details, created_at)
                   VALUES (?, 'registered', ?, ?)""",
                (tenant_id, f"Company: {company_name}, Plan: {plan}", now),
            )

        reg = TenantRegistration(
            tenant_id=tenant_id,
            company_name=company_name,
            email=email,
            plan=plan,
            status=OnboardingStatus.PENDING,
            api_key=api_key,
            created_at=now,
            metadata=meta_str,
        )
        logger.info("[Onboarding] Registered tenant %s (%s)", tenant_id, company_name)
        return reg

    def get_tenant(self, tenant_id: str) -> Optional[TenantRegistration]:
        """Retrieve a tenant registration by ID."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tenant_registrations WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
        return self._row_to_registration(row) if row else None

    def get_tenant_by_email(self, email: str) -> Optional[TenantRegistration]:
        """Retrieve a tenant registration by email."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tenant_registrations WHERE email = ?",
                (email,),
            ).fetchone()
        return self._row_to_registration(row) if row else None

    def list_tenants(
        self, status: str = "", plan: str = "", limit: int = 50
    ) -> list[dict]:
        """List tenants with optional filters."""
        clauses = []
        params: list = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if plan:
            clauses.append("plan = ?")
            params.append(plan)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM tenant_registrations{where} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [self._row_to_registration(r).to_dict() for r in rows]

    # ── Provisioning Pipeline ──────────────────────────────────────────

    def activate_tenant(self, tenant_id: str) -> TenantRegistration:
        """
        Activate a tenant, moving them from PENDING → ACTIVE.
        Also marks the verify_email checklist step as complete.
        """
        now = time.time()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tenant_registrations WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Tenant not found: {tenant_id}")
            if row["status"] == OnboardingStatus.ACTIVE:
                return self._row_to_registration(row)

            conn.execute(
                """UPDATE tenant_registrations
                   SET status = ?, activated_at = ?
                   WHERE tenant_id = ?""",
                (OnboardingStatus.ACTIVE, now, tenant_id),
            )

            # Auto-complete the verify_email step
            conn.execute(
                """UPDATE onboarding_checklist
                   SET completed = 1, completed_at = ?
                   WHERE tenant_id = ? AND step_id = 'verify_email'""",
                (now, tenant_id),
            )

            conn.execute(
                """INSERT INTO onboarding_events
                   (tenant_id, event_type, details, created_at)
                   VALUES (?, 'activated', 'Tenant activated', ?)""",
                (tenant_id, now),
            )

        tenant = self.get_tenant(tenant_id)
        logger.info("[Onboarding] Activated tenant %s", tenant_id)
        return tenant

    def suspend_tenant(self, tenant_id: str, reason: str = "") -> bool:
        """Suspend a tenant's access."""
        now = time.time()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "UPDATE tenant_registrations SET status = ? WHERE tenant_id = ?",
                (OnboardingStatus.SUSPENDED, tenant_id),
            )
            if cur.rowcount:
                conn.execute(
                    """INSERT INTO onboarding_events
                       (tenant_id, event_type, details, created_at)
                       VALUES (?, 'suspended', ?, ?)""",
                    (tenant_id, reason, now),
                )
        logger.info("[Onboarding] Suspended tenant %s: %s", tenant_id, reason)
        return cur.rowcount > 0

    def change_plan(self, tenant_id: str, new_plan: str) -> TenantRegistration:
        """Change a tenant's subscription plan."""
        now = time.time()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tenant_registrations WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Tenant not found: {tenant_id}")
            old_plan = row["plan"]
            conn.execute(
                "UPDATE tenant_registrations SET plan = ? WHERE tenant_id = ?",
                (new_plan, tenant_id),
            )
            conn.execute(
                """INSERT INTO onboarding_events
                   (tenant_id, event_type, details, created_at)
                   VALUES (?, 'plan_changed', ?, ?)""",
                (tenant_id, f"{old_plan} → {new_plan}", now),
            )
        logger.info("[Onboarding] Plan changed for %s: %s → %s",
                     tenant_id, old_plan, new_plan)
        return self.get_tenant(tenant_id)

    # ── Onboarding Checklist ──────────────────────────────────────────

    def get_checklist(self, tenant_id: str) -> list[dict]:
        """Get the onboarding checklist for a tenant."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM onboarding_checklist
                   WHERE tenant_id = ? ORDER BY sort_order""",
                (tenant_id,),
            ).fetchall()
        return [
            OnboardingChecklistItem(
                step_id=r["step_id"],
                tenant_id=r["tenant_id"],
                title=r["title"],
                description=r["description"],
                completed=bool(r["completed"]),
                completed_at=r["completed_at"],
                order=r["sort_order"],
            ).to_dict()
            for r in rows
        ]

    def complete_step(self, tenant_id: str, step_id: str) -> bool:
        """Mark a checklist step as completed."""
        now = time.time()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """UPDATE onboarding_checklist
                   SET completed = 1, completed_at = ?
                   WHERE tenant_id = ? AND step_id = ? AND completed = 0""",
                (now, tenant_id, step_id),
            )
            if cur.rowcount:
                conn.execute(
                    """INSERT INTO onboarding_events
                       (tenant_id, event_type, details, created_at)
                       VALUES (?, 'step_completed', ?, ?)""",
                    (tenant_id, step_id, now),
                )
        return cur.rowcount > 0

    def get_progress(self, tenant_id: str) -> dict:
        """Get the onboarding progress for a tenant."""
        checklist = self.get_checklist(tenant_id)
        total = len(checklist)
        completed = sum(1 for item in checklist if item["completed"])
        return {
            "tenant_id": tenant_id,
            "total_steps": total,
            "completed_steps": completed,
            "progress_pct": round(completed / max(total, 1) * 100, 1),
            "remaining": [
                item["step_id"] for item in checklist if not item["completed"]
            ],
            "checklist": checklist,
        }

    # ── Quota Lookup ───────────────────────────────────────────────────

    def get_quotas(self, tenant_id: str) -> dict:
        """Get the usage quotas for a tenant based on their plan."""
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return {"error": "Tenant not found"}
        plan_key = tenant.plan
        try:
            tier = PlanTier(plan_key)
        except ValueError:
            tier = PlanTier.FREE
        quotas = PLAN_QUOTAS.get(tier, PLAN_QUOTAS[PlanTier.FREE])
        return {
            "tenant_id": tenant_id,
            "plan": plan_key,
            "quotas": quotas,
        }

    # ── Event History ──────────────────────────────────────────────────

    def get_events(self, tenant_id: str, limit: int = 50) -> list[dict]:
        """Get onboarding event history for a tenant."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM onboarding_events
                   WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?""",
                (tenant_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Stats ──────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get system-wide onboarding statistics."""
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as c FROM tenant_registrations"
            ).fetchone()["c"]
            by_status = conn.execute(
                """SELECT status, COUNT(*) as c
                   FROM tenant_registrations GROUP BY status"""
            ).fetchall()
            by_plan = conn.execute(
                """SELECT plan, COUNT(*) as c
                   FROM tenant_registrations GROUP BY plan"""
            ).fetchall()
            recent = conn.execute(
                """SELECT COUNT(*) as c FROM tenant_registrations
                   WHERE created_at > ?""",
                (time.time() - 86400 * 7,),
            ).fetchone()["c"]

        return {
            "total_tenants": total,
            "by_status": {r["status"]: r["c"] for r in by_status},
            "by_plan": {r["plan"]: r["c"] for r in by_plan},
            "registered_last_7_days": recent,
            "generated_at": time.time(),
        }

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_registration(row: sqlite3.Row) -> TenantRegistration:
        return TenantRegistration(
            tenant_id=row["tenant_id"],
            company_name=row["company_name"],
            email=row["email"],
            plan=row["plan"],
            status=row["status"],
            api_key=row["api_key"],
            created_at=row["created_at"],
            activated_at=row["activated_at"],
            metadata=row["metadata"],
        )
