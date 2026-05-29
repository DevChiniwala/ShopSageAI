"""
Price Checker Worker — Background task for monitoring price watches.

Periodically scans all active price watches, fetches current prices
from the scraper, and triggers notifications when thresholds are met.
Runs as an asyncio background task alongside the FastAPI server.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from shopsage.monetise.deal_alerts import DealAlertStore, PriceWatch
from shopsage.tool.price_scraper import fetch_prices
from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.workers.price_checker")

# ─── Configuration ─────────────────────────────────────────────────────

CHECK_INTERVAL_SECONDS = 900  # 15 minutes between full scans
BATCH_SIZE = 5                # Max concurrent product queries per cycle
MAX_RETRIES = 2               # Retries per product on failure


class PriceCheckerWorker:
    """
    Background worker that monitors active price watches.

    Lifecycle:
        1. start() — launches the async loop
        2. _check_cycle() — iterates all active watches
        3. _check_watch() — fetches price and updates watch
        4. stop() — gracefully shuts down

    Integrates with DealAlertStore for persistence and
    the notification system for alert delivery.
    """

    def __init__(self, db_path: str = DB_PATH):
        self._store = DealAlertStore(db_path=db_path)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = {
            "cycles_completed": 0,
            "watches_checked": 0,
            "alerts_triggered": 0,
            "errors": 0,
            "last_run": None,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return {**self._stats}

    # ─── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background price checking loop."""
        if self._running:
            logger.warning("[PriceChecker] Already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"[PriceChecker] ✅ Started — checking every "
            f"{CHECK_INTERVAL_SECONDS}s"
        )

    async def stop(self) -> None:
        """Gracefully stop the worker."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[PriceChecker] 🛑 Stopped")

    # ─── Core Loop ─────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main loop — runs check cycles at fixed intervals."""
        # Initial delay to let the server start up
        await asyncio.sleep(10)

        while self._running:
            try:
                await self._check_cycle()
                self._stats["cycles_completed"] += 1
                self._stats["last_run"] = datetime.now(timezone.utc).isoformat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[PriceChecker] Cycle error: {e}", exc_info=True)
                self._stats["errors"] += 1

            # Wait for next cycle
            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _check_cycle(self) -> None:
        """Run one full check cycle across all active watches."""
        watches = self._store.get_all_active_watches()

        if not watches:
            logger.debug("[PriceChecker] No active watches")
            return

        logger.info(f"[PriceChecker] Checking {len(watches)} active watches")

        # Group watches by product query to avoid duplicate scrapes
        query_groups: dict[str, list[PriceWatch]] = {}
        for watch in watches:
            key = watch.product_query.lower().strip()
            if key not in query_groups:
                query_groups[key] = []
            query_groups[key].append(watch)

        # Process in batches
        queries = list(query_groups.keys())
        for i in range(0, len(queries), BATCH_SIZE):
            batch = queries[i : i + BATCH_SIZE]
            tasks = [
                self._check_query(q, query_groups[q]) for q in batch
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Small delay between batches to be polite to stores
            if i + BATCH_SIZE < len(queries):
                await asyncio.sleep(3)

    async def _check_query(
        self, query: str, watches: list[PriceWatch]
    ) -> None:
        """Fetch prices for a query and update all related watches."""
        for attempt in range(MAX_RETRIES + 1):
            try:
                results = await fetch_prices(query)
                valid = [r for r in results if r.error is None and r.price > 0]

                if not valid:
                    logger.debug(f"[PriceChecker] No valid results for '{query[:30]}'")
                    return

                # Use the lowest price found across all stores
                best = min(valid, key=lambda r: r.price)

                for watch in watches:
                    triggered = self._store.update_price(
                        watch_id=watch.id,
                        current_price=best.price,
                        product_url=best.url,
                    )

                    self._stats["watches_checked"] += 1

                    if triggered:
                        self._stats["alerts_triggered"] += 1
                        await self._send_notification(watch, best.price, best.store)

                return  # Success — no retry needed

            except Exception as e:
                if attempt < MAX_RETRIES:
                    logger.debug(
                        f"[PriceChecker] Retry {attempt + 1} for '{query[:30]}': {e}"
                    )
                    await asyncio.sleep(2)
                else:
                    logger.warning(
                        f"[PriceChecker] Failed after {MAX_RETRIES + 1} attempts: "
                        f"'{query[:30]}' — {e}"
                    )
                    self._stats["errors"] += 1

    async def _send_notification(
        self, watch: PriceWatch, current_price: float, store: str
    ) -> None:
        """
        Send a price drop notification.

        Currently logs the alert. In production, this would delegate
        to the notifications module (email, push, SMS).
        """
        try:
            # Import here to avoid circular imports
            from shopsage.notifications.email_notifier import send_price_alert

            await send_price_alert(
                user_id=watch.user_id,
                product=watch.product_query,
                target_price=watch.target_price,
                current_price=current_price,
                store=store,
                url=watch.product_url,
            )
        except ImportError:
            logger.info(
                f"[PriceChecker] 🔔 ALERT: '{watch.product_query}' "
                f"dropped to ₹{current_price:,.0f} on {store} "
                f"(target: ₹{watch.target_price:,.0f}) "
                f"for user {watch.user_id[:8]}"
            )
        except Exception as e:
            logger.error(f"[PriceChecker] Notification error: {e}")
