"""
Tests for WebhookStore and SearchTracker.
"""

import pytest

from shopsage.webhooks.webhook_store import WebhookStore
from shopsage.analytics.search_tracker import SearchTracker


# ─── Webhook Tests ─────────────────────────────────────────────────────


@pytest.fixture
def wh_store(tmp_path):
    return WebhookStore(db_path=str(tmp_path / "test_wh.db"))


def test_register_webhook(wh_store):
    """Should register a webhook and return a secret."""
    wh = wh_store.register("tenant-1", "https://example.com/hook", ["price_alert"])
    assert wh.id
    assert wh.secret
    assert wh.url == "https://example.com/hook"
    assert "price_alert" in wh.events


def test_get_by_tenant(wh_store):
    """Should return webhooks for a specific tenant."""
    wh_store.register("tenant-1", "https://a.com/hook")
    wh_store.register("tenant-1", "https://b.com/hook")
    wh_store.register("tenant-2", "https://c.com/hook")

    hooks = wh_store.get_by_tenant("tenant-1")
    assert len(hooks) == 2


def test_get_subscribers_wildcard(wh_store):
    """Wildcard webhooks should match all events."""
    wh_store.register("t1", "https://a.com/hook")  # default events = ["*"]
    subs = wh_store.get_subscribers("any_event")
    assert len(subs) == 1


def test_get_subscribers_filtered(wh_store):
    """Subscribers should only match registered event types."""
    wh_store.register("t1", "https://a.com/hook", ["price_alert"])
    wh_store.register("t2", "https://b.com/hook", ["order_update"])

    price_subs = wh_store.get_subscribers("price_alert")
    assert len(price_subs) == 1
    assert price_subs[0].url == "https://a.com/hook"


def test_deactivate_webhook(wh_store):
    """Deactivated webhooks should not appear in queries."""
    wh = wh_store.register("t1", "https://a.com/hook")
    assert wh_store.deactivate(wh.id, "t1") is True

    hooks = wh_store.get_by_tenant("t1", active_only=True)
    assert len(hooks) == 0


def test_delivery_logging(wh_store):
    """Should log delivery attempts and update counters."""
    wh = wh_store.register("t1", "https://a.com/hook")

    # Successful delivery
    wh_store.log_delivery(wh.id, "price_alert", '{"test": 1}', 200, 45.2)
    # Failed delivery
    wh_store.log_delivery(wh.id, "price_alert", '{"test": 2}', 500, 120.0)

    logs = wh_store.get_delivery_logs(wh.id)
    assert len(logs) == 2


# ─── Search Tracker Tests ─────────────────────────────────────────────


@pytest.fixture
def tracker(tmp_path):
    return SearchTracker(db_path=str(tmp_path / "test_search.db"))


def test_track_query(tracker):
    """Should track a search query."""
    tracker.track("sess-1", "Nike shoes", "shopping", 5)
    popular = tracker.get_popular_queries(limit=10, hours=1)
    assert len(popular) == 1
    assert popular[0]["query"] == "nike shoes"  # normalized


def test_popular_queries_ranked(tracker):
    """Should rank by frequency."""
    tracker.track("s1", "Nike shoes", "shopping", 5)
    tracker.track("s2", "Nike shoes", "shopping", 3)
    tracker.track("s3", "Adidas shoes", "shopping", 2)

    popular = tracker.get_popular_queries(limit=5, hours=1)
    assert popular[0]["query"] == "nike shoes"
    assert popular[0]["count"] == 2


def test_zero_result_queries(tracker):
    """Should identify queries with no results."""
    tracker.track("s1", "purple unicorn hat", "shopping", 0)
    tracker.track("s2", "Nike shoes", "shopping", 5)

    demand = tracker.get_zero_result_queries(limit=5, hours=1)
    assert len(demand) == 1
    assert demand[0]["query"] == "purple unicorn hat"


def test_search_volume(tracker):
    """Should return correct volume stats."""
    tracker.track("s1", "query1", "shopping", 3)
    tracker.track("s1", "query2", "shopping", 5)
    tracker.track("s2", "query1", "shopping", 2)

    vol = tracker.get_search_volume(hours=1)
    assert vol["total_searches"] == 3
    assert vol["unique_sessions"] == 2
    assert vol["unique_queries"] == 2


def test_hourly_trend(tracker):
    """Should group searches by hour."""
    tracker.track("s1", "shoes", "shopping", 3)
    tracker.track("s2", "shirts", "shopping", 5)

    trend = tracker.get_hourly_trend(hours=1)
    assert len(trend) >= 1
    assert trend[0]["count"] >= 2
