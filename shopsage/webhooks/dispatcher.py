"""
Webhook Dispatcher — Async delivery engine with HMAC signing and retries.

Delivers event payloads to registered webhook URLs via HTTP POST.
Each request is signed with the webhook's secret using HMAC-SHA256
so recipients can verify authenticity.

Retry policy: 3 attempts with exponential backoff (1s, 4s, 9s).
"""

import hmac
import json
import time
import hashlib
import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

from shopsage.webhooks.webhook_store import WebhookStore, Webhook
from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.webhooks.dispatcher")

MAX_RETRIES = 3
TIMEOUT_SECONDS = 10


class WebhookDispatcher:
    """
    Delivers webhook payloads to registered endpoints.

    Features:
    - HMAC-SHA256 request signing (X-ShopSage-Signature header)
    - Exponential backoff retries (1s, 4s, 9s)
    - Per-delivery logging with status codes and latency
    - Fire-and-forget background delivery via asyncio.create_task
    """

    def __init__(self, db_path: str = DB_PATH):
        self._store = WebhookStore(db_path=db_path)

    def _sign_payload(self, payload: str, secret: str) -> str:
        """Generate HMAC-SHA256 signature for payload verification."""
        return hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def dispatch(
        self,
        event_type: str,
        data: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> int:
        """
        Dispatch an event to all subscribed webhooks.

        Args:
            event_type: Event name (e.g. "price_alert", "new_order").
            data: Event payload dictionary.
            tenant_id: If set, only dispatch to this tenant's webhooks.

        Returns:
            Number of webhooks that received the event.
        """
        subscribers = self._store.get_subscribers(event_type)

        if tenant_id:
            subscribers = [w for w in subscribers if w.tenant_id == tenant_id]

        if not subscribers:
            logger.debug(f"[Webhook] No subscribers for event '{event_type}'")
            return 0

        logger.info(
            f"[Webhook] Dispatching '{event_type}' to {len(subscribers)} webhooks"
        )

        payload = json.dumps({
            "event": event_type,
            "data": data,
            "timestamp": time.time(),
        }, default=str)

        # Fire all deliveries concurrently
        tasks = [
            self._deliver(webhook, event_type, payload)
            for webhook in subscribers
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        return len(subscribers)

    async def dispatch_background(
        self,
        event_type: str,
        data: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> None:
        """
        Fire-and-forget dispatch — launches delivery as a background task.

        Use this from synchronous contexts or when you don't need
        to await the result.
        """
        asyncio.create_task(self.dispatch(event_type, data, tenant_id))

    async def _deliver(
        self, webhook: Webhook, event_type: str, payload: str
    ) -> bool:
        """
        Deliver a payload to a single webhook with retries.

        Returns True if delivery succeeded (2xx response).
        """
        signature = self._sign_payload(payload, webhook.secret)

        headers = {
            "Content-Type": "application/json",
            "X-ShopSage-Event": event_type,
            "X-ShopSage-Signature": f"sha256={signature}",
            "X-ShopSage-Webhook-ID": webhook.id,
            "User-Agent": "ShopSageAI-Webhook/1.0",
        }

        for attempt in range(MAX_RETRIES):
            start = time.monotonic()
            status_code = None
            error = None

            try:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        webhook.url,
                        content=payload,
                        headers=headers,
                    )
                    status_code = response.status_code
                    elapsed_ms = (time.monotonic() - start) * 1000

                    self._store.log_delivery(
                        webhook_id=webhook.id,
                        event_type=event_type,
                        payload=payload,
                        status_code=status_code,
                        response_time_ms=elapsed_ms,
                    )

                    if 200 <= status_code < 300:
                        logger.info(
                            f"[Webhook] ✅ Delivered to {webhook.url[:40]} "
                            f"({status_code}, {elapsed_ms:.0f}ms)"
                        )
                        return True

                    logger.warning(
                        f"[Webhook] ⚠️ Non-2xx from {webhook.url[:40]}: {status_code}"
                    )

            except Exception as e:
                elapsed_ms = (time.monotonic() - start) * 1000
                error = str(e)
                logger.warning(
                    f"[Webhook] ❌ Attempt {attempt + 1}/{MAX_RETRIES} "
                    f"to {webhook.url[:40]} failed: {error}"
                )
                self._store.log_delivery(
                    webhook_id=webhook.id,
                    event_type=event_type,
                    payload=payload,
                    status_code=None,
                    response_time_ms=elapsed_ms,
                    error=error,
                )

            # Exponential backoff: 1s, 4s, 9s
            if attempt < MAX_RETRIES - 1:
                backoff = (attempt + 1) ** 2
                await asyncio.sleep(backoff)

        logger.error(
            f"[Webhook] Failed all {MAX_RETRIES} attempts to {webhook.url[:40]}"
        )
        return False
