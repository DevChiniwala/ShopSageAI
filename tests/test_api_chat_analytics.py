"""Regression tests for SaaS API chat analytics logging."""

from pathlib import Path


def test_api_router_chat_passes_event_data_to_log_event():
    """Guard against missing event_data kwarg in /api/v1/chat."""
    source = Path("shopsage/router/api_router.py").read_text(encoding="utf-8")
    assert "event_data=event_data" in source


def test_analytics_store_accepts_event_data(tmp_path):
    from shopsage.analytics.tracker import AnalyticsStore

    store = AnalyticsStore(db_path=str(tmp_path / "analytics.db"))
    store.log_event(
        tenant_id="tenant-1",
        session_id="sess-abc",
        event_type="chat",
        event_data={"message_length": 9, "response_length": 4, "plan": "free"},
    )

    stats = store.get_summary_stats()
    assert stats["total_events"] == 1
    assert stats["events_by_type"]["chat"] == 1
