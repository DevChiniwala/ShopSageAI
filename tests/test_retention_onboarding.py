"""
Tests for Day 30 — Data Retention Policies & Tenant Onboarding.

Covers:
  • RetentionPolicyManager: CRUD, enforcement, compliance reports, event history
  • OnboardingManager: registration, activation, plan changes, checklists, quotas
"""

import os
import time
import pytest
import tempfile

from shopsage.retention.policy_manager import (
    RetentionPolicyManager,
    RetentionPolicy,
    RetentionAction,
    DataCategory,
    RetentionEvent,
)
from shopsage.onboarding.manager import (
    OnboardingManager,
    OnboardingStatus,
    PlanTier,
    TenantRegistration,
    PLAN_QUOTAS,
    DEFAULT_CHECKLIST,
)


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def retention_mgr(tmp_path):
    db = str(tmp_path / "retention_test.db")
    return RetentionPolicyManager(db_path=db)


@pytest.fixture
def onboarding_mgr(tmp_path):
    db = str(tmp_path / "onboarding_test.db")
    return OnboardingManager(db_path=db)


# ═══════════════════════════════════════════════════════════════════════
# Retention Policy Tests
# ═══════════════════════════════════════════════════════════════════════


class TestRetentionDefaults:
    """Default policies are auto-created on init."""

    def test_defaults_exist(self, retention_mgr):
        policies = retention_mgr.list_policies()
        # Should have one global policy per DataCategory
        assert len(policies) >= len(DataCategory)

    def test_default_conversations_policy(self, retention_mgr):
        policy = retention_mgr.get_policy("conversations")
        assert policy is not None
        assert policy.retention_days == 90
        assert policy.action == "archive"

    def test_default_session_data_policy(self, retention_mgr):
        policy = retention_mgr.get_policy("session_data")
        assert policy is not None
        assert policy.retention_days == 7
        assert policy.action == "delete"


class TestRetentionPolicyCRUD:
    """Create, read, update, delete policies."""

    def test_set_global_policy(self, retention_mgr):
        policy = retention_mgr.set_policy("conversations", 180, action="delete")
        assert policy.retention_days == 180
        assert policy.action == "delete"

    def test_set_tenant_override(self, retention_mgr):
        policy = retention_mgr.set_policy(
            "conversations", 30, tenant_id="tn_abc", action="delete"
        )
        assert policy.tenant_id == "tn_abc"
        assert policy.retention_days == 30

    def test_tenant_override_takes_priority(self, retention_mgr):
        retention_mgr.set_policy("analytics", 365, tenant_id="tn_xyz")
        policy = retention_mgr.get_policy("analytics", tenant_id="tn_xyz")
        assert policy.retention_days == 365  # Override, not the default 180

    def test_fallback_to_global(self, retention_mgr):
        # No tenant override for search_history
        policy = retention_mgr.get_policy("search_history", tenant_id="tn_nope")
        assert policy is not None
        assert policy.tenant_id == ""  # Global fallback

    def test_delete_tenant_override(self, retention_mgr):
        retention_mgr.set_policy("notifications", 15, tenant_id="tn_del")
        assert retention_mgr.delete_policy("notifications", tenant_id="tn_del")

    def test_cannot_delete_global_default(self, retention_mgr):
        assert not retention_mgr.delete_policy("notifications")  # tenant_id=""

    def test_policy_to_dict(self, retention_mgr):
        policy = retention_mgr.get_policy("audit_logs")
        d = policy.to_dict()
        assert d["category"] == "audit_logs"
        assert "retention_days" in d


class TestRetentionEnforcement:
    """Enforcement engine: dry-run and real."""

    def test_enforce_single_category(self, retention_mgr):
        event = retention_mgr.enforce("conversations")
        assert isinstance(event, RetentionEvent)
        assert event.status == "success"
        assert event.category == "conversations"

    def test_enforce_dry_run(self, retention_mgr):
        event = retention_mgr.enforce("analytics", dry_run=True)
        assert event.action == "dry_run"
        assert "Dry-run" in event.details

    def test_enforce_disabled_policy(self, retention_mgr):
        retention_mgr.set_policy("session_data", 7, enabled=False)
        event = retention_mgr.enforce("session_data")
        assert event.status == "skipped"

    def test_enforce_all(self, retention_mgr):
        results = retention_mgr.enforce_all(dry_run=True)
        assert len(results) == len(DataCategory)
        assert all(r["action"] == "dry_run" for r in results)

    def test_enforce_nonexistent_policy(self, retention_mgr):
        event = retention_mgr.enforce("nonexistent_category")
        assert event.status == "skipped"


class TestRetentionEvents:
    """Event history & compliance reporting."""

    def test_events_recorded(self, retention_mgr):
        retention_mgr.enforce("conversations")
        events = retention_mgr.get_event_history(category="conversations")
        assert len(events) >= 1
        assert events[0]["category"] == "conversations"

    def test_evaluate_expired(self, retention_mgr):
        result = retention_mgr.evaluate_expired("conversations")
        assert result["status"] == "evaluated"
        assert "cutoff_timestamp" in result

    def test_compliance_report(self, retention_mgr):
        report = retention_mgr.compliance_report()
        assert report["total_categories"] == len(DataCategory)
        assert report["compliance_score"] == 100.0  # All defaults enabled
        assert len(report["uncovered_categories"]) == 0


# ═══════════════════════════════════════════════════════════════════════
# Onboarding Tests
# ═══════════════════════════════════════════════════════════════════════


class TestTenantRegistration:
    """Tenant registration lifecycle."""

    def test_register_tenant(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Acme Corp", "admin@acme.com")
        assert reg.tenant_id.startswith("tn_")
        assert reg.api_key.startswith("sk_")
        assert reg.status == OnboardingStatus.PENDING
        assert reg.plan == PlanTier.FREE

    def test_duplicate_email_rejected(self, onboarding_mgr):
        onboarding_mgr.register_tenant("First Co", "dup@test.com")
        with pytest.raises(ValueError, match="already registered"):
            onboarding_mgr.register_tenant("Second Co", "dup@test.com")

    def test_get_tenant_by_id(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Test Co", "test@co.com")
        found = onboarding_mgr.get_tenant(reg.tenant_id)
        assert found is not None
        assert found.company_name == "Test Co"

    def test_get_tenant_by_email(self, onboarding_mgr):
        onboarding_mgr.register_tenant("Email Co", "email@co.com")
        found = onboarding_mgr.get_tenant_by_email("email@co.com")
        assert found is not None
        assert found.company_name == "Email Co"

    def test_get_nonexistent_tenant(self, onboarding_mgr):
        assert onboarding_mgr.get_tenant("tn_nope") is None

    def test_registration_to_dict(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Dict Co", "dict@co.com")
        d = reg.to_dict()
        assert d["company_name"] == "Dict Co"
        assert "api_key" in d

    def test_list_tenants(self, onboarding_mgr):
        onboarding_mgr.register_tenant("A Corp", "a@corp.com")
        onboarding_mgr.register_tenant("B Corp", "b@corp.com")
        tenants = onboarding_mgr.list_tenants()
        assert len(tenants) == 2


class TestTenantActivation:
    """Activation, suspension, and plan changes."""

    def test_activate_tenant(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Act Co", "act@co.com")
        activated = onboarding_mgr.activate_tenant(reg.tenant_id)
        assert activated.status == OnboardingStatus.ACTIVE
        assert activated.activated_at > 0

    def test_activate_nonexistent_raises(self, onboarding_mgr):
        with pytest.raises(ValueError, match="not found"):
            onboarding_mgr.activate_tenant("tn_ghost")

    def test_suspend_tenant(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Sus Co", "sus@co.com")
        onboarding_mgr.activate_tenant(reg.tenant_id)
        assert onboarding_mgr.suspend_tenant(reg.tenant_id, "policy violation")

    def test_change_plan(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Plan Co", "plan@co.com")
        updated = onboarding_mgr.change_plan(reg.tenant_id, "professional")
        assert updated.plan == "professional"

    def test_change_plan_nonexistent_raises(self, onboarding_mgr):
        with pytest.raises(ValueError, match="not found"):
            onboarding_mgr.change_plan("tn_nope", "starter")


class TestOnboardingChecklist:
    """Checklist management and progress tracking."""

    def test_checklist_created_on_register(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Check Co", "check@co.com")
        checklist = onboarding_mgr.get_checklist(reg.tenant_id)
        assert len(checklist) == len(DEFAULT_CHECKLIST)
        assert all(not item["completed"] for item in checklist)

    def test_complete_step(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Step Co", "step@co.com")
        assert onboarding_mgr.complete_step(reg.tenant_id, "verify_email")

    def test_complete_already_done_step(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Done Co", "done@co.com")
        onboarding_mgr.complete_step(reg.tenant_id, "verify_email")
        # Second call returns False (already completed)
        assert not onboarding_mgr.complete_step(reg.tenant_id, "verify_email")

    def test_progress_tracking(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Prog Co", "prog@co.com")
        onboarding_mgr.complete_step(reg.tenant_id, "verify_email")
        onboarding_mgr.complete_step(reg.tenant_id, "generate_api_key")
        progress = onboarding_mgr.get_progress(reg.tenant_id)
        assert progress["completed_steps"] == 2
        assert progress["progress_pct"] == 40.0
        assert "first_api_call" in progress["remaining"]

    def test_activate_auto_completes_verify_email(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Auto Co", "auto@co.com")
        onboarding_mgr.activate_tenant(reg.tenant_id)
        progress = onboarding_mgr.get_progress(reg.tenant_id)
        completed_ids = [
            item["step_id"] for item in progress["checklist"] if item["completed"]
        ]
        assert "verify_email" in completed_ids


class TestQuotasAndStats:
    """Quota lookup and system stats."""

    def test_free_plan_quotas(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Free Co", "free@co.com")
        quotas = onboarding_mgr.get_quotas(reg.tenant_id)
        assert quotas["plan"] == "free"
        assert quotas["quotas"]["requests_per_day"] == 100

    def test_enterprise_quotas(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Ent Co", "ent@co.com", plan="enterprise")
        quotas = onboarding_mgr.get_quotas(reg.tenant_id)
        assert quotas["quotas"]["requests_per_day"] == 500000

    def test_quotas_nonexistent_tenant(self, onboarding_mgr):
        result = onboarding_mgr.get_quotas("tn_ghost")
        assert "error" in result

    def test_onboarding_stats(self, onboarding_mgr):
        onboarding_mgr.register_tenant("S1", "s1@co.com")
        onboarding_mgr.register_tenant("S2", "s2@co.com", plan="starter")
        stats = onboarding_mgr.get_stats()
        assert stats["total_tenants"] == 2
        assert stats["by_plan"]["free"] == 1
        assert stats["by_plan"]["starter"] == 1

    def test_event_history(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Ev Co", "ev@co.com")
        onboarding_mgr.activate_tenant(reg.tenant_id)
        events = onboarding_mgr.get_events(reg.tenant_id)
        types = [e["event_type"] for e in events]
        assert "registered" in types
        assert "activated" in types

    def test_list_tenants_by_status(self, onboarding_mgr):
        reg = onboarding_mgr.register_tenant("Filt Co", "filt@co.com")
        onboarding_mgr.activate_tenant(reg.tenant_id)
        active = onboarding_mgr.list_tenants(status="active")
        assert len(active) == 1
        assert active[0]["status"] == "active"


class TestPlanQuotaConstants:
    """Verify plan quota constants are well-formed."""

    def test_all_plans_have_quotas(self):
        for tier in PlanTier:
            assert tier in PLAN_QUOTAS

    def test_enterprise_has_most_features(self):
        free_features = set(PLAN_QUOTAS[PlanTier.FREE]["features"])
        ent_features = set(PLAN_QUOTAS[PlanTier.ENTERPRISE]["features"])
        assert free_features.issubset(ent_features)

    def test_quotas_increase_with_tier(self):
        tiers = [PlanTier.FREE, PlanTier.STARTER, PlanTier.PROFESSIONAL, PlanTier.ENTERPRISE]
        rpds = [PLAN_QUOTAS[t]["requests_per_day"] for t in tiers]
        assert rpds == sorted(rpds)
