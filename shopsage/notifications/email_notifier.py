"""
Email Notifier — Price alert email delivery for ShopSage AI.

Provides HTML email templates and async delivery via SMTP.
Currently operates in log-only mode; configure SMTP credentials
in .env for production email delivery.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("shopsage.notifications.email")

# ─── Configuration ─────────────────────────────────────────────────────

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "alerts@shopsage.ai")
SMTP_ENABLED = bool(SMTP_HOST and SMTP_USER)


# ─── Email Templates ──────────────────────────────────────────────────


def _build_price_alert_html(
    product: str,
    target_price: float,
    current_price: float,
    store: str,
    url: str = "",
) -> str:
    """Build a styled HTML email for a price drop alert."""
    savings = target_price - current_price
    buy_link = f'<a href="{url}" style="background:#8B5CF6;color:white;padding:12px 28px;border-radius:24px;text-decoration:none;font-weight:600;display:inline-block;margin-top:16px;">Buy Now on {store} →</a>' if url else ""

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0;padding:0;background:#0f0f23;font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif;">
        <div style="max-width:520px;margin:32px auto;background:linear-gradient(135deg,#1a1a2e,#16213e);border-radius:16px;border:1px solid rgba(139,92,246,0.2);overflow:hidden;">
            <!-- Header -->
            <div style="background:linear-gradient(135deg,#8B5CF6,#6366F1);padding:24px 32px;text-align:center;">
                <h1 style="margin:0;color:white;font-size:20px;">🔔 Price Drop Alert!</h1>
                <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">ShopSage AI found a deal for you</p>
            </div>

            <!-- Body -->
            <div style="padding:28px 32px;">
                <h2 style="color:#e2e8f0;font-size:16px;margin:0 0 16px;">{product}</h2>

                <div style="display:flex;gap:20px;margin:20px 0;">
                    <div style="flex:1;text-align:center;padding:16px;background:rgba(74,222,128,0.08);border-radius:12px;border:1px solid rgba(74,222,128,0.2);">
                        <div style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Current Price</div>
                        <div style="color:#4ade80;font-size:24px;font-weight:700;margin-top:4px;">₹{current_price:,.0f}</div>
                    </div>
                    <div style="flex:1;text-align:center;padding:16px;background:rgba(139,92,246,0.08);border-radius:12px;border:1px solid rgba(139,92,246,0.2);">
                        <div style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Your Target</div>
                        <div style="color:#a78bfa;font-size:24px;font-weight:700;margin-top:4px;">₹{target_price:,.0f}</div>
                    </div>
                </div>

                <div style="text-align:center;padding:12px;background:rgba(74,222,128,0.06);border-radius:8px;border:1px solid rgba(74,222,128,0.15);margin:16px 0;">
                    <span style="color:#4ade80;font-weight:600;">💰 You save ₹{savings:,.0f} vs your target!</span>
                </div>

                <div style="color:#94a3b8;font-size:13px;margin-top:12px;">
                    📍 Found on <strong style="color:#e2e8f0;">{store}</strong>
                </div>

                <div style="text-align:center;margin-top:20px;">
                    {buy_link}
                </div>
            </div>

            <!-- Footer -->
            <div style="padding:16px 32px;border-top:1px solid rgba(139,92,246,0.1);text-align:center;">
                <p style="margin:0;color:#64748b;font-size:11px;">
                    Sent by ShopSage AI • <a href="#" style="color:#8B5CF6;">Manage Alerts</a>
                </p>
            </div>
        </div>
    </body>
    </html>
    """


# ─── Delivery ──────────────────────────────────────────────────────────


async def send_price_alert(
    user_id: str,
    product: str,
    target_price: float,
    current_price: float,
    store: str,
    url: str = "",
    recipient_email: Optional[str] = None,
) -> bool:
    """
    Send a price drop alert notification.

    In production mode (SMTP configured), sends an HTML email.
    In dev mode, logs the alert to console.

    Args:
        user_id: User session ID for logging.
        product: Product name/query.
        target_price: User's target price threshold.
        current_price: Current lowest price found.
        store: Store with the best price.
        url: Product URL (affiliate-tagged).
        recipient_email: Email address to send to.

    Returns:
        True if notification was sent/logged successfully.
    """
    html = _build_price_alert_html(
        product=product,
        target_price=target_price,
        current_price=current_price,
        store=store,
        url=url,
    )

    if SMTP_ENABLED and recipient_email:
        return await _send_smtp(recipient_email, product, html)

    # Dev mode — log to console
    logger.info(
        f"[EmailNotifier] 📧 PRICE ALERT (dev mode)\n"
        f"  User: {user_id[:12]}\n"
        f"  Product: {product}\n"
        f"  Price: ₹{current_price:,.0f} on {store}\n"
        f"  Target: ₹{target_price:,.0f}\n"
        f"  URL: {url[:80] if url else 'N/A'}"
    )
    return True


async def _send_smtp(to: str, subject: str, html: str) -> bool:
    """
    Send email via SMTP (production mode).

    Uses aiosmtplib for async delivery. Falls back to logging
    if the library is not installed.
    """
    try:
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔔 Price Drop: {subject}"
        msg["From"] = FROM_EMAIL
        msg["To"] = to
        msg.attach(MIMEText(html, "html"))

        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASS,
            start_tls=True,
        )

        logger.info(f"[EmailNotifier] ✅ Email sent to {to}")
        return True

    except ImportError:
        logger.warning(
            "[EmailNotifier] aiosmtplib not installed. "
            "Run: pip install aiosmtplib"
        )
        return False
    except Exception as e:
        logger.error(f"[EmailNotifier] SMTP error: {e}")
        return False
