"""
Distributed Cache — Unified cache factory for ShopSage AI.

Automatically selects between Redis (production) and in-memory (development)
backends based on the REDIS_URL environment variable. Provides the same
singleton caches (price_cache, review_cache, embedding_cache) that the rest
of the application imports.
"""

import os
import logging
from typing import Optional

from shopsage.cache.redis_backend import RedisCache, _get_redis_client

logger = logging.getLogger("shopsage.cache")

# ── Shared Redis client (lazy singleton) ───────────────────────────────

_redis_client = None
_redis_attempted = False


def _get_shared_client():
    """Get or create the shared Redis client. Only attempts once."""
    global _redis_client, _redis_attempted
    if not _redis_attempted:
        _redis_attempted = True
        redis_url = os.getenv("REDIS_URL", "")
        if redis_url:
            _redis_client = _get_redis_client()
        else:
            logger.info("[Cache] No REDIS_URL set, using in-memory caches")
    return _redis_client


# ── Cache Factory ──────────────────────────────────────────────────────


def create_cache(
    name: str,
    default_ttl: int = 300,
    max_size: int = 500,
) -> RedisCache:
    """
    Create a cache instance. Uses Redis if available, else in-memory.
    All caches share the same Redis connection but use different key prefixes.
    """
    client = _get_shared_client()
    cache = RedisCache(
        default_ttl=default_ttl,
        max_size=max_size,
        name=name,
        redis_client=client,
    )
    backend = "redis" if cache.is_redis else "memory"
    logger.info("[Cache] Created '%s' cache (backend=%s, ttl=%ds)", name, backend, default_ttl)
    return cache


# ── Singleton Caches (drop-in replacements) ────────────────────────────

# Price scraper results (5 min TTL, up to 200 queries)
price_cache = create_cache("prices", default_ttl=300, max_size=200)

# Review analysis results (15 min TTL)
review_cache = create_cache("reviews", default_ttl=900, max_size=100)

# Embedding results (1 hour TTL)
embedding_cache = create_cache("embeddings", default_ttl=3600, max_size=500)
