"""
Celery Tasks — Background asynchronous operations for ShopSage AI.

Migrated from the custom SQLite JobQueue to robust Celery tasks backed by Redis.
"""

import time
import logging
from shopsage.workers.celery_app import celery_app

# Import the actual logic to be executed
from shopsage.scraper.price_scraper import PriceScraper
from shopsage.rag.embedding_builder import EmbeddingBuilder
from shopsage.webhooks.dispatcher import WebhookDispatcher
from shopsage.webhooks.webhook_store import WebhookStore

logger = logging.getLogger("shopsage.tasks")


@celery_app.task(name="shopsage.tasks.scrape_prices", bind=True, max_retries=3)
def scrape_prices_task(self, product_name: str, tenant_id: str = ""):
    """Background task to scrape prices for a product."""
    logger.info(f"[Task:scrape] Starting scrape for '{product_name}' (tenant={tenant_id})")
    
    start = time.time()
    try:
        scraper = PriceScraper()
        results = scraper.scrape(product_name)
        elapsed = time.time() - start
        
        logger.info(f"[Task:scrape] Completed '{product_name}' in {elapsed:.2f}s, found {len(results)} items.")
        return results
    except Exception as exc:
        logger.error(f"[Task:scrape] Failed for '{product_name}': {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(name="shopsage.tasks.build_embeddings", bind=True, max_retries=2)
def build_embeddings_task(self, docs: list[dict]):
    """Background task to process texts and insert them into FAISS."""
    logger.info(f"[Task:embed] Building embeddings for {len(docs)} documents.")
    
    try:
        builder = EmbeddingBuilder()
        success_count = builder.process_and_store(docs)
        logger.info(f"[Task:embed] Successfully embedded {success_count} documents.")
        return success_count
    except Exception as exc:
        logger.error(f"[Task:embed] Failed: {exc}")
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="shopsage.tasks.dispatch_webhook", bind=True, max_retries=5)
def dispatch_webhook_task(self, event_type: str, payload: dict, tenant_id: str):
    """Background task to reliably deliver webhooks."""
    logger.info(f"[Task:webhook] Dispatching '{event_type}' for tenant {tenant_id}")
    
    try:
        # Reconstruct dependencies. In a real app we might inject these or use singletons
        store = WebhookStore()
        dispatcher = WebhookDispatcher(store)
        
        # This calls the synchronous dispatch method (or asyncio.run if it's async)
        # Assuming dispatch() handles its own requests
        dispatcher.dispatch(event_type, payload, tenant_id)
        return True
    except Exception as exc:
        logger.warning(f"[Task:webhook] Delivery failed, scheduling retry: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

