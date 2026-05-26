"""
Tests for Feature Flags and API Key Manager.
"""

import pytest
from datetime import datetime, timedelta

from shopsage.auth.feature_flags import FeatureFlagStore, PLAN_GATED_FLAGS
from shopsage.auth.key_manager import APIKeyManager


# ─── Feature Flag Tests ───────────────────────────────────────────────


@pytest.fixture
def flags(tmp_path):
    return FeatureFlagStore(db_path=str(tmp_path / "test_flags.db"))


def test_default_flags_seeded(flags):
    """Built-in flags should be seeded on init."""
    all_flags = flags.list_flags()
    assert len(all_flags) >= len(PLAN_GATED_FLAGS)


def test_free_tier_gets_free_features(flags):
    """Free tier should access free features."""
    assert flags.is_enabled("price_alerts", "t1", "free") is True
    assert flags.is_enabled("multi_language", "t1", "free") is True


def test_free_tier_blocked_from_pro(flags):
    """Free tier should NOT access pro features."""
    assert flags.is_enabled("visual_search", "t1", "free") is False
    assert flags.is_enabled("webhook_integrations", "t1", "free") is False


def test_pro_tier_gets_pro_features(flags):
    """Pro tier should access pro features."""
    assert flags.is_enabled("visual_search", "t1", "pro") is True
    assert flags.is_enabled("advanced_analytics", "t1", "pro") is True


def test_enterprise_gets_all(flags):
    """Enterprise should access everything."""
    assert flags.is_enabled("custom_branding", "t1", "enterprise") is True
    assert flags.is_enabled("priority_support", "t1", "enterprise") is True
    assert flags.is_enabled("visual_search", "t1", "enterprise") is True


def test_tenant_override(flags):
    """Per-tenant overrides should take precedence."""
    # Free tier normally can't access visual_search
    assert flags.is_enabled("visual_search", "t1", "free") is False

    # Override it on for this specific tenant (e.g. beta tester)
    flags.set_tenant_override("t1", "visual_search", True)
    assert flags.is_enabled("visual_search", "t1", "free") is True

    # Remove override — should fall back to plan check
    flags.remove_tenant_override("t1", "visual_search")
    assert flags.is_enabled("visual_search", "t1", "free") is False


def test_get_tenant_flags(flags):
    """Should return all flags resolved for a tenant."""
    resolved = flags.get_tenant_flags("t1", "pro")
    assert isinstance(resolved, dict)
    assert resolved["visual_search"] is True   # pro feature
    assert resolved["custom_branding"] is False  # enterprise only


def test_create_custom_flag(flags):
    """Should create a new custom flag."""
    assert flags.create_flag("beta_chat_v2", "Beta chat interface", True) is True
    assert flags.is_enabled("beta_chat_v2", "t1", "free") is True

    # Duplicate should fail
    assert flags.create_flag("beta_chat_v2", "dupe") is False


# ─── API Key Manager Tests ────────────────────────────────────────────


@pytest.fixture
def keys(tmp_path):
    return APIKeyManager(db_path=str(tmp_path / "test_keys.db"))


def test_create_key(keys):
    """Should create a key and return the raw value."""
    result = keys.create_key("tenant-1", label="production")
    assert result["key"].startswith("sk-")
    assert result["label"] == "production"
    assert result["tenant_id"] == "tenant-1"


def test_validate_key(keys):
    """Should validate a valid key and track usage."""
    result = keys.create_key("t1")
    raw_key = result["key"]

    validated = keys.validate_key(raw_key)
    assert validated is not None
    assert validated["tenant_id"] == "t1"
    assert validated["usage_count"] == 1


def test_invalid_key_rejected(keys):
    """Invalid keys should be rejected."""
    assert keys.validate_key("sk-totally-fake-key") is None


def test_revoke_key(keys):
    """Revoked keys should be rejected."""
    result = keys.create_key("t1")
    raw_key = result["key"]

    assert keys.revoke_key(result["id"], "t1") is True
    assert keys.validate_key(raw_key) is None


def test_key_rotation(keys):
    """Rotation should create new key and set old to expire."""
    old = keys.create_key("t1", label="old-key")
    new = keys.rotate_key("t1", old["id"], grace_period_hours=1, label="new-key")

    assert new["key"] != old["key"]
    assert new["label"] == "new-key"

    # Both keys should still be valid during grace period
    assert keys.validate_key(old["key"]) is not None
    assert keys.validate_key(new["key"]) is not None


def test_list_keys(keys):
    """Should list all keys for a tenant without exposing raw values."""
    keys.create_key("t1", label="key-1")
    keys.create_key("t1", label="key-2")
    keys.create_key("t2", label="other")

    t1_keys = keys.list_keys("t1")
    assert len(t1_keys) == 2
    # Raw key should NOT be in the listing
    for k in t1_keys:
        assert "key" not in k or not k.get("key", "").startswith("sk-")


def test_active_count(keys):
    """Should count active keys correctly."""
    k1 = keys.create_key("t1")
    keys.create_key("t1")
    keys.revoke_key(k1["id"], "t1")

    assert keys.get_active_count("t1") == 1


def test_key_with_expiry(keys):
    """Should create a key with an expiration date."""
    result = keys.create_key("t1", expires_in_days=30)
    assert result["expires_at"] is not None
