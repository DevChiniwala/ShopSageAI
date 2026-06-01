"""
Event Handlers — Connects the EventBus to downstream systems.

Registers handlers that react to domain events by:
- Creating in-app notifications
- Logging to the audit trail
- Triggering webhook dispatches

This module is the wiring layer — import it at app startup
to register all handlers with the global event bus.
"""

import logging
from shopsage.events.event_bus import Event, get_event_bus
from shopsage.notifications.notification_center import NotificationCenter
from shopsage.security.audit_log import AuditLog
from shopsage.config import settings

logger = logging.getLogger("shopsage.events.handlers")

_notif_center = NotificationCenter(db_path=settings.DB_PATH)
_audit_log = AuditLog(db_path=settings.DB_PATH)


# ─── Price Alert Handler ──────────────────────────────────────────────

def on_price_alert(event: Event) -> None:
    """Handle price drop events by creating notifications."""
    data = event.data
    product = data.get("product_name", "Unknown product")
    old_price = data.get("old_price", 0)
    new_price = data.get("new_price", 0)
    savings = old_price - new_price

    _notif_center.create(
        tenant_id=event.tenant_id or "system",
        notification_type="price_alert",
        title=f"💰 Price Drop: {product}",
        message=(
            f"{product} dropped from ${old_price:.2f} to ${new_price:.2f} "
            f"(save ${savings:.2f}!)"
        ),
        priority="info" if savings < 20 else "warning",
        action_url=data.get("product_url", ""),
    )


# ─── Billing Alert Handler ───────────────────────────────────────────

def on_billing_threshold(event: Event) -> None:
    """Alert when a tenant approaches usage limits."""
    data = event.data
    tenant_id = event.tenant_id
    usage_pct = data.get("usage_percentage", 0)

    if usage_pct >= 90:
        priority = "critical"
        title = "🚨 Usage Limit Critical"
        message = f"You've used {usage_pct}% of your plan quota. Upgrade to avoid service interruption."
    elif usage_pct >= 75:
        priority = "warning"
        title = "⚠️ Usage Approaching Limit"
        message = f"You've used {usage_pct}% of your plan quota. Consider upgrading."
    else:
        return  # No notification needed

    _notif_center.create(
        tenant_id=tenant_id,
        notification_type="billing",
        title=title,
        message=message,
        priority=priority,
        action_url="/billing",
    )


# ─── Tenant Lifecycle Handler ─────────────────────────────────────────

def on_tenant_event(event: Event) -> None:
    """Log tenant lifecycle events to audit trail."""
    data = event.data
    action = data.get("action", event.type.split(".")[-1])

    _audit_log.record(
        actor_id=data.get("actor_id", "system"),
        actor_type=data.get("actor_type", "system"),
        action=action,
        resource_type="tenant",
        resource_id=data.get("tenant_id", event.tenant_id),
        details=data,
    )

    # Welcome notification for new tenants
    if action == "created":
        _notif_center.create(
            tenant_id=data.get("tenant_id", event.tenant_id),
            notification_type="system",
            title="🎉 Welcome to ShopSage AI!",
            message="Your account is ready. Start by setting up your first webhook integration.",
            priority="info",
            action_url="/getting-started",
        )


# ─── Security Event Handler ──────────────────────────────────────────

def on_security_event(event: Event) -> None:
    """Handle security-related events (failed logins, suspicious activity)."""
    data = event.data
    severity = data.get("severity", "warning")

    _audit_log.record(
        actor_id=data.get("actor_id", "unknown"),
        actor_type="security",
        action=data.get("action", "security_event"),
        resource_type="security",
        resource_id=data.get("resource_id", ""),
        details=data,
        ip_address=data.get("ip_address", ""),
    )

    if severity == "critical":
        _notif_center.create(
            tenant_id=event.tenant_id or "system",
            notification_type="security",
            title="🔒 Security Alert",
            message=data.get("message", "Suspicious activity detected on your account."),
            priority="critical",
        )


# ─── System Health Handler ────────────────────────────────────────────

def on_health_degraded(event: Event) -> None:
    """Handle system health degradation events."""
    data = event.data
    component = data.get("component", "unknown")
    status = data.get("status", "degraded")

    _notif_center.create(
        tenant_id="system",
        notification_type="system",
        title=f"⚠️ System Health: {component}",
        message=f"Component '{component}' is {status}. {data.get('details', '')}",
        priority="warning" if status == "degraded" else "critical",
    )


# ─── Registration ─────────────────────────────────────────────────────

def register_all_handlers() -> None:
    """
    Register all event handlers with the global event bus.

    Call this once at application startup.
    """
    bus = get_event_bus()

    bus.subscribe("price_alert", on_price_alert)
    bus.subscribe("billing.threshold", on_billing_threshold)
    bus.subscribe("tenant.created", on_tenant_event)
    bus.subscribe("tenant.updated", on_tenant_event)
    bus.subscribe("tenant.deactivated", on_tenant_event)
    bus.subscribe("security.alert", on_security_event)
    bus.subscribe("security.failed_login", on_security_event)
    bus.subscribe("health.degraded", on_health_degraded)
    bus.subscribe("health.down", on_health_degraded)

    logger.info("[EventHandlers] Registered 9 event handlers across 9 event types")
