"""
Deal Alert Tools — LangChain tools for price watch management.

Allows the agent to create, list, and manage price drop alerts
for users during natural conversation.
"""

import logging
from langchain_core.tools import tool
from shopsage.monetise.deal_alerts import DealAlertStore

logger = logging.getLogger("shopsage.tools.deals")

_store = DealAlertStore()


@tool
def set_price_alert(
    product_query: str, target_price: float, session_id: str = ""
) -> str:
    """
    Set a price drop alert for a product.

    Call this when the user wants to be notified when a product's price
    drops below a certain amount.

    Triggers include:
    - "Alert me when Nike shoes drop below 3000"
    - "Notify me if this goes under 2000"
    - "Set a price watch for iPhone at 50000"
    - "Tell me when Samsung earbuds are under 1500"

    Args:
        product_query: The product to watch.
        target_price: The price threshold to trigger the alert.
        session_id: The user's session ID for attribution.

    Returns:
        Confirmation message with watch details.
    """
    try:
        watch = _store.create_watch(
            user_id=session_id or "anonymous",
            product_query=product_query,
            target_price=target_price,
        )
        return (
            f"✅ Price alert set!\n\n"
            f"📦 Product: {product_query}\n"
            f"🎯 Target: ₹{target_price:,.0f}\n"
            f"🔔 Alert ID: #{watch.id}\n\n"
            f"I'll keep watching this product. "
            f"You'll be notified when the price drops below ₹{target_price:,.0f}."
        )
    except Exception as e:
        logger.error(f"[DealAlert] Error creating watch: {e}")
        return "Sorry, I couldn't set the price alert. Please try again."


@tool
def list_price_alerts(session_id: str = "") -> str:
    """
    List all active price alerts for the current user.

    Call this when the user asks about their existing alerts
    or wants to see what products they are watching.

    Triggers include:
    - "Show my price alerts"
    - "What products am I watching?"
    - "List my deal alerts"
    - "Do I have any active alerts?"

    Args:
        session_id: The user's session ID.

    Returns:
        Formatted list of active price watches.
    """
    try:
        watches = _store.get_user_watches(
            user_id=session_id or "anonymous",
            active_only=True,
        )
        return _store.format_watches(watches)
    except Exception as e:
        logger.error(f"[DealAlert] Error listing watches: {e}")
        return "Sorry, I couldn't retrieve your alerts. Please try again."


@tool
def remove_price_alert(alert_id: int, session_id: str = "") -> str:
    """
    Remove (deactivate) a price alert by its ID.

    Call this when the user wants to stop watching a product.

    Triggers include:
    - "Remove alert #3"
    - "Cancel my price watch on Nike shoes"
    - "Stop tracking that product"
    - "Delete alert 5"

    Args:
        alert_id: The numeric ID of the alert to remove.
        session_id: The user's session ID.

    Returns:
        Confirmation or error message.
    """
    try:
        success = _store.deactivate_watch(
            watch_id=alert_id,
            user_id=session_id or "anonymous",
        )
        if success:
            return f"✅ Alert #{alert_id} has been removed. You won't receive further notifications for this product."
        else:
            return f"❌ Alert #{alert_id} not found or already removed."
    except Exception as e:
        logger.error(f"[DealAlert] Error removing watch: {e}")
        return "Sorry, I couldn't remove the alert. Please try again."
