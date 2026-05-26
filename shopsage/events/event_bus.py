"""
Event Bus — In-process pub/sub system for ShopSage AI.

Decouples producers (API routes, agents, workers) from consumers
(webhooks, notifications, analytics, audit). Any module can emit
an event without knowing who will handle it.

Design:
    - Handlers are registered per event type
    - Async and sync handlers are both supported
    - Errors in one handler don't block others
    - Events are processed in-order per type
    - Wildcard ("*") handlers receive every event
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from collections import defaultdict

logger = logging.getLogger("shopsage.events.bus")


@dataclass
class Event:
    """An event flowing through the bus."""
    type: str                          # e.g. "price_alert", "tenant.created"
    data: Dict[str, Any]               # event payload
    source: str = ""                   # origin module
    tenant_id: str = ""                # tenant scope (empty = system)
    timestamp: float = field(default_factory=time.time)
    event_id: str = ""                 # auto-assigned


# Type alias for handler callables
EventHandler = Callable[[Event], Any]

# Counter for auto-assigning event IDs
_event_counter = 0


class EventBus:
    """
    In-process publish/subscribe event bus.

    Usage:
        bus = EventBus()
        bus.subscribe("price_alert", my_handler)
        await bus.publish(Event(type="price_alert", data={...}))

    Features:
        - Per-type subscriptions
        - Wildcard subscribers (receive all events)
        - Async + sync handler support
        - Error isolation between handlers
        - Event history for debugging
    """

    def __init__(self, max_history: int = 500):
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._history: List[Dict[str, Any]] = []
        self._max_history = max_history
        self._stats: Dict[str, int] = defaultdict(int)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Register a handler for an event type.

        Use "*" as event_type to receive all events.
        """
        self._handlers[event_type].append(handler)
        logger.info(
            f"[EventBus] Subscribed {handler.__name__} to '{event_type}'"
        )

    def unsubscribe(self, event_type: str, handler: EventHandler) -> bool:
        """Remove a handler. Returns True if found and removed."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
            return True
        return False

    async def publish(self, event: Event) -> int:
        """
        Publish an event to all registered handlers.

        Returns the number of handlers that were called.
        """
        global _event_counter
        _event_counter += 1
        event.event_id = f"evt-{_event_counter}"

        # Collect matching handlers
        handlers = list(self._handlers.get(event.type, []))
        # Add wildcard handlers
        handlers.extend(self._handlers.get("*", []))

        if not handlers:
            logger.debug(f"[EventBus] No handlers for '{event.type}'")
            self._stats["dropped"] += 1
            return 0

        self._stats[event.type] = self._stats.get(event.type, 0) + 1
        self._stats["total"] = self._stats.get("total", 0) + 1

        called = 0
        for handler in handlers:
            try:
                result = handler(event)
                # Await if handler is async
                if asyncio.iscoroutine(result):
                    await result
                called += 1
            except Exception as e:
                logger.error(
                    f"[EventBus] Handler {handler.__name__} failed "
                    f"on '{event.type}': {e}"
                )
                self._stats["errors"] = self._stats.get("errors", 0) + 1

        # Record in history
        self._record_history(event, called)

        logger.debug(
            f"[EventBus] '{event.type}' dispatched to {called} handlers"
        )
        return called

    def emit_sync(self, event: Event) -> None:
        """
        Fire-and-forget event emission from synchronous code.

        Creates an asyncio task if an event loop is running,
        otherwise logs a warning.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            # No event loop running — execute handlers synchronously
            for handler in self._handlers.get(event.type, []):
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"[EventBus] Sync handler error: {e}")

    def _record_history(self, event: Event, handler_count: int) -> None:
        """Record event in circular history buffer."""
        self._history.append({
            "event_id": event.event_id,
            "type": event.type,
            "source": event.source,
            "tenant_id": event.tenant_id,
            "timestamp": event.timestamp,
            "handler_count": handler_count,
        })
        # Trim to max size
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent event history."""
        return list(reversed(self._history[-limit:]))

    def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        return {
            "total_events": self._stats.get("total", 0),
            "dropped_events": self._stats.get("dropped", 0),
            "errors": self._stats.get("errors", 0),
            "registered_types": len(self._handlers),
            "per_type": {
                k: v for k, v in self._stats.items()
                if k not in ("total", "dropped", "errors")
            },
        }

    def list_subscriptions(self) -> Dict[str, List[str]]:
        """List all registered subscriptions."""
        return {
            event_type: [h.__name__ for h in handlers]
            for event_type, handlers in self._handlers.items()
            if handlers
        }


# ─── Global singleton ─────────────────────────────────────────────────

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create the global EventBus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
