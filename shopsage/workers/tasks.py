"""
Celery Tasks — Background asynchronous operations for ShopSage AI.

Migrated from the custom SQLite JobQueue to robust Celery tasks backed by Redis.
All heavy imports are deferred to inside the task body (lazy imports) to avoid
import errors at Celery worker startup and to keep the module lightweight.
"""

import time
import logging
from shopsage.workers.celery_app import celery_app

logger = logging.getLogger("shopsage.tasks")


@celery_app.task(name="shopsage.tasks.scrape_prices", bind=True, max_retries=3)
def scrape_prices_task(self, product_name: str, tenant_id: str = ""):
    """Background task to scrape prices for a product."""
    logger.info(f"[Task:scrape] Starting scrape for '{product_name}' (tenant={tenant_id})")

    start = time.time()
    try:
        from shopsage.tool.price_scraper import fetch_prices
        import asyncio

        results = asyncio.run(fetch_prices(product_name))
        elapsed = time.time() - start

        logger.info(f"[Task:scrape] Completed '{product_name}' in {elapsed:.2f}s")
        return results
    except Exception as exc:
        logger.error(f"[Task:scrape] Failed for '{product_name}': {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(name="shopsage.tasks.build_embeddings", bind=True, max_retries=2)
def build_embeddings_task(self, docs: list[dict]):
    """Background task to process texts and insert them into FAISS."""
    logger.info(f"[Task:embed] Building embeddings for {len(docs)} documents.")

    try:
        from shopsage.rag.index_builder import build_index
        success_count = build_index(docs)
        logger.info(f"[Task:embed] Successfully embedded {success_count} documents.")
        return success_count
    except ImportError:
        logger.warning("[Task:embed] RAG index builder module not yet available, skipping.")
        return 0
    except Exception as exc:
        logger.error(f"[Task:embed] Failed: {exc}")
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="shopsage.tasks.dispatch_webhook", bind=True, max_retries=5)
def dispatch_webhook_task(self, event_type: str, payload: dict, tenant_id: str):
    """Background task to reliably deliver webhooks."""
    logger.info(f"[Task:webhook] Dispatching '{event_type}' for tenant {tenant_id}")

    try:
        import asyncio

        from shopsage.webhooks.dispatcher import WebhookDispatcher
        from shopsage.config import settings

        dispatcher = WebhookDispatcher(db_path=settings.DB_PATH)
        delivered = asyncio.run(
            dispatcher.dispatch(event_type, payload, tenant_id)
        )
        return delivered
    except Exception as exc:
        logger.warning(f"[Task:webhook] Delivery failed, scheduling retry: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
