"""
Tests for API Versioning and Rate Limit Analytics.
"""

import pytest
from shopsage.router.versioning import (
    VersionRegistry, APIVersion, VersionStatus,
    create_default_registry,
)
from shopsage.analytics.rate_limit_analytics import RateLimitAnalytics


# ─── API Versioning Tests ─────────────────────────────────────────────


@pytest.fixture
def registry():
    return create_default_registry()


def test_register_versions(registry):
    """Should register v1 and v2."""
    versions = registry.list_versions()
    keys = {v["version"] for v in versions}
    assert "v1" in keys
    assert "v2" in keys
    assert len(versions) == 2


def test_default_version(registry):
    """Default version should be v1."""
    default = registry.get_default()
    assert default.version == "v1"
    assert default.status == VersionStatus.ACTIVE


def test_negotiate_url_prefix(registry):
    """Should detect version from URL prefix."""
    assert registry.negotiate("/api/v1/chat") == "v1"
    assert registry.negotiate("/api/v2/chat") == "v2"


def test_negotiate_accept_header(registry):
    """Should detect version from Accept header."""
    assert registry.negotiate(
        "/api/chat", "application/vnd.shopsage.v2+json"
    ) == "v2"


def test_negotiate_fallback(registry):
    """Should fall back to default version."""
    assert registry.negotiate("/api/chat") == "v1"
    assert registry.negotiate("/other/path") == "v1"


def test_deprecation_check(registry):
    """Active versions should not be deprecated."""
    assert registry.is_deprecated("v1") is False
    assert registry.is_deprecated("v2") is False


def test_deprecation_flow(registry):
    """Should correctly report deprecated versions."""
    v_old = APIVersion(
        version="v0", status=VersionStatus.DEPRECATED,
        released="2025-01-01", deprecated_on="2026-01-01",
        sunset_on="2026-07-01",
    )
    registry.register(v_old)
    assert registry.is_deprecated("v0") is True
    info = registry.get_deprecation_info("v0")
    assert info["deprecated_on"] == "2026-01-01"
    assert info["migration_target"] == "v1"


def test_sunset_version(registry):
    """Sunset versions should be flagged."""
    v_dead = APIVersion(
        version="v_legacy", status=VersionStatus.SUNSET,
        released="2024-01-01", sunset_on="2025-06-01",
    )
    registry.register(v_dead)
    assert registry.is_sunset("v_legacy") is True
    assert registry.is_deprecated("v_legacy") is True


def test_feature_matrix(registry):
    """Should track per-version feature availability."""
    assert registry.has_feature("v1", "chat") is True
    assert registry.has_feature("v1", "pagination") is False
    assert registry.has_feature("v2", "pagination") is True
    assert registry.has_feature("v2", "structured_errors") is True


def test_migration_guide(registry):
    """Should return migration guide between versions."""
    guide = registry.get_migration_guide("v1", "v2")
    assert guide is not None
    assert len(guide["breaking_changes"]) > 0
    assert len(guide["new_features"]) > 0
    assert "tokens_remaining" in guide["renamed_fields"]


def test_active_versions(registry):
    """Should list active and preview versions."""
    active = registry.get_active_versions()
    assert "v1" in active
    assert "v2" in active


def test_get_nonexistent_version(registry):
    """Should return None for unknown versions."""
    assert registry.get("v99") is None
    assert registry.has_feature("v99", "chat") is False


# ─── Rate Limit Analytics Tests ───────────────────────────────────────


@pytest.fixture
def analytics(tmp_path):
    return RateLimitAnalytics(db_path=str(tmp_path / "test_rl.db"))


def test_record_and_summary(analytics):
    """Should record events and return a summary."""
    for i in range(10):
        analytics.record_event(
            tenant_id="t1", api_key="sk-test-key-123",
            tier="free", action="chat",
            requests_in_window=i + 1, limit_value=30,
            remaining=30 - (i + 1), blocked=False,
        )

    # Record 2 blocked events
    for _ in range(2):
        analytics.record_event(
            tenant_id="t1", api_key="sk-test-key-123",
            tier="free", action="chat",
            requests_in_window=30, limit_value=30,
            remaining=0, blocked=True,
        )

    summary = analytics.get_tenant_summary("t1", hours=1)
    assert summary["total_requests"] == 12
    assert summary["total_blocked"] == 2
    assert summary["block_rate"] > 0
    assert summary["tier"] == "free"


def test_empty_tenant_summary(analytics):
    """Should return zeros for unknown tenants."""
    summary = analytics.get_tenant_summary("nonexistent")
    assert summary["total_requests"] == 0
    assert summary["total_blocked"] == 0


def test_hourly_trends(analytics):
    """Should return hourly aggregated data."""
    for i in range(5):
        analytics.record_event(
            tenant_id="t1", api_key="sk-key",
            tier="pro", action="chat",
            requests_in_window=i, limit_value=120,
            remaining=120 - i,
        )

    trends = analytics.get_hourly_trends("t1", hours=1)
    assert len(trends) > 0
    assert trends[0]["requests"] == 5
    assert trends[0]["blocked"] == 0


def test_top_consumers(analytics):
    """Should rank tenants by request volume."""
    for i in range(15):
        analytics.record_event(
            tenant_id="heavy", api_key="sk-heavy",
            tier="pro", action="chat",
            requests_in_window=i, limit_value=120, remaining=120 - i,
        )
    for i in range(3):
        analytics.record_event(
            tenant_id="light", api_key="sk-light",
            tier="free", action="chat",
            requests_in_window=i, limit_value=30, remaining=30 - i,
        )

    top = analytics.get_top_consumers(hours=1, limit=5)
    assert len(top) == 2
    assert top[0]["tenant_id"] == "heavy"
    assert top[0]["total_requests"] == 15
    assert top[1]["tenant_id"] == "light"


def test_global_stats(analytics):
    """Should return system-wide statistics."""
    analytics.record_event(
        tenant_id="t1", api_key="sk-1", tier="free",
        action="chat", blocked=False,
    )
    analytics.record_event(
        tenant_id="t2", api_key="sk-2", tier="pro",
        action="chat", blocked=True,
    )

    stats = analytics.get_global_stats(hours=1)
    assert stats["total_events"] == 2
    assert stats["total_blocked"] == 1
    assert stats["unique_tenants"] == 2
    assert "free" in stats["by_tier"]
    assert "pro" in stats["by_tier"]


def test_purge_old_events(analytics):
    """Purge should not delete recent events."""
    analytics.record_event(
        tenant_id="t1", api_key="sk-1", tier="free", action="chat",
    )
    deleted = analytics.purge_old_events(days=1)
    assert deleted == 0  # nothing old to delete

    # Event should still exist
    summary = analytics.get_tenant_summary("t1", hours=1)
    assert summary["total_requests"] == 1


def test_global_trends_unfiltered(analytics):
    """Hourly trends without tenant filter should aggregate all."""
    analytics.record_event(
        tenant_id="t1", api_key="sk-1", tier="free", action="chat",
    )
    analytics.record_event(
        tenant_id="t2", api_key="sk-2", tier="pro", action="chat",
    )
    trends = analytics.get_hourly_trends(hours=1)
    assert len(trends) > 0
    assert trends[0]["requests"] == 2
