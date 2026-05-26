"""
Tests for EventBus, NotificationCenter, and Event Handlers.
"""

import pytest
import asyncio
from shopsage.events.event_bus import EventBus, Event
from shopsage.notifications.notification_center import NotificationCenter


# ─── EventBus Tests ────────────────────────────────────────────────────


@pytest.fixture
def bus():
    return EventBus()


def test_publish_and_handle(bus):
    """Test basic publish-subscribe."""
    received = []

    def handler(event: Event):
        received.append(event.data)

    bus.subscribe("test.event", handler)

    asyncio.run(bus.publish(Event(type="test.event", data={"key": "value"})))

    assert len(received) == 1
    assert received[0]["key"] == "value"


def test_multiple_handlers(bus):
    """Test multiple handlers for same event."""
    results = []

    def handler_a(event: Event):
        results.append("a")

    def handler_b(event: Event):
        results.append("b")

    bus.subscribe("multi", handler_a)
    bus.subscribe("multi", handler_b)

    asyncio.run(bus.publish(Event(type="multi", data={})))

    assert "a" in results
    assert "b" in results


def test_wildcard_handler(bus):
    """Wildcard handlers should receive all events."""
    received = []

    def wildcard(event: Event):
        received.append(event.type)

    bus.subscribe("*", wildcard)

    asyncio.run(bus.publish(Event(type="event.one", data={})))
    asyncio.run(bus.publish(Event(type="event.two", data={})))

    assert len(received) == 2
    assert "event.one" in received
    assert "event.two" in received


def test_error_isolation(bus):
    """Errors in one handler should not block others."""
    results = []

    def bad_handler(event: Event):
        raise ValueError("boom")

    def good_handler(event: Event):
        results.append("ok")

    bus.subscribe("error.test", bad_handler)
    bus.subscribe("error.test", good_handler)

    asyncio.run(bus.publish(Event(type="error.test", data={})))

    assert results == ["ok"]
    assert bus.get_stats()["errors"] == 1


def test_unsubscribe(bus):
    """Unsubscribe should remove handler."""
    called = []

    def handler(event: Event):
        called.append(True)

    bus.subscribe("unsub.test", handler)
    assert bus.unsubscribe("unsub.test", handler) is True

    asyncio.run(bus.publish(Event(type="unsub.test", data={})))
    assert len(called) == 0


def test_event_history(bus):
    """Events should be recorded in history."""
    def noop(event: Event):
        pass

    bus.subscribe("history.test", noop)
    asyncio.run(bus.publish(Event(type="history.test", data={"a": 1})))

    history = bus.get_history(limit=10)
    assert len(history) == 1
    assert history[0]["type"] == "history.test"


def test_stats_tracking(bus):
    """Stats should track event counts."""
    def noop(event: Event):
        pass

    bus.subscribe("stats.test", noop)
    asyncio.run(bus.publish(Event(type="stats.test", data={})))
    asyncio.run(bus.publish(Event(type="stats.test", data={})))

    stats = bus.get_stats()
    assert stats["total_events"] == 2
    assert stats["per_type"]["stats.test"] == 2


# ─── NotificationCenter Tests ─────────────────────────────────────────


@pytest.fixture
def notif_center(tmp_path):
    return NotificationCenter(db_path=str(tmp_path / "test_notif.db"))


def test_create_notification(notif_center):
    """Should create and retrieve notifications."""
    notif = notif_center.create(
        tenant_id="t1",
        notification_type="price_alert",
        title="Price Drop!",
        message="Nike shoes dropped 20%",
        priority="info",
    )
    assert notif["id"]
    assert notif["title"] == "Price Drop!"


def test_unread_notifications(notif_center):
    """Should return only unread notifications."""
    notif_center.create("t1", "alert", "Alert 1", "Message 1")
    notif_center.create("t1", "alert", "Alert 2", "Message 2")

    unread = notif_center.get_unread("t1")
    assert len(unread) == 2


def test_mark_read(notif_center):
    """Marking as read should remove from unread list."""
    notif = notif_center.create("t1", "alert", "Test", "Message")
    assert notif_center.mark_read(notif["id"], "t1") is True

    unread = notif_center.get_unread("t1")
    assert len(unread) == 0


def test_mark_all_read(notif_center):
    """Should mark all notifications as read."""
    notif_center.create("t1", "alert", "A1", "M1")
    notif_center.create("t1", "alert", "A2", "M2")
    notif_center.create("t1", "alert", "A3", "M3")

    count = notif_center.mark_all_read("t1")
    assert count == 3
    assert notif_center.get_unread_count("t1") == 0


def test_unread_count(notif_center):
    """Should count unread notifications."""
    notif_center.create("t1", "a", "T1", "M1")
    notif_center.create("t1", "a", "T2", "M2")
    notif_center.create("t2", "a", "T3", "M3")  # different tenant

    assert notif_center.get_unread_count("t1") == 2
    assert notif_center.get_unread_count("t2") == 1


def test_tenant_isolation(notif_center):
    """Notifications should be tenant-scoped."""
    notif_center.create("t1", "a", "T1", "M1")
    notif_center.create("t2", "a", "T2", "M2")

    assert len(notif_center.get_all("t1")) == 1
    assert len(notif_center.get_all("t2")) == 1
