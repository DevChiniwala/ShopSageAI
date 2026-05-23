"""
Rate Limiter — Sliding window in-memory rate limiting for ShopSage AI SaaS.

Tracks request counts per API key in a sliding 60-second window.
Designed to be injected as a FastAPI middleware or dependency.

Usage tiers:
    - free:    30 req/min
    - pro:     120 req/min
    - enterprise: unlimited
"""

import time
import logging
from collections import defaultdict, deque
from threading import Lock
from fastapi import HTTPException, Request
from typing import Deque

logger = logging.getLogger("shopsage.auth.rate_limiter")

# ─── Tier Limits (requests per minute) ────────────────────────────────

TIER_LIMITS: dict[str, int] = {
    "free": 30,
    "pro": 120,
    "enterprise": 9999,  # effectively unlimited
}
WINDOW_SECONDS = 60


class RateLimiter:
    """
    Sliding window rate limiter using an in-process deque per API key.

    Thread-safe via threading.Lock. Works per-process — for multi-worker
    deployments, swap the backend for Redis using the same interface.
    """

    def __init__(self) -> None:
        # Maps api_key -> deque of request timestamps
        self._buckets: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._stats: dict[str, int] = defaultdict(int)  # total blocked per key

    def is_allowed(self, api_key: str, tier: str = "free") -> bool:
        """
        Check if a request from `api_key` is within rate limits.

        Evicts timestamps older than the sliding window, then checks
        against the tier's request-per-minute limit.

        Returns:
            True if request is allowed, False if rate limited.
        """
        limit = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS

        with self._lock:
            bucket = self._buckets[api_key]

            # Evict stale timestamps
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                self._stats[api_key] += 1
                logger.warning(
                    f"[RateLimit] BLOCKED {api_key[:12]}… "
                    f"({len(bucket)}/{limit} req/min, tier={tier})"
                )
                return False

            bucket.append(now)
            return True

    def get_usage(self, api_key: str, tier: str = "free") -> dict:
        """
        Return current usage info for an API key.
        """
        limit = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS

        with self._lock:
            bucket = self._buckets[api_key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            current = len(bucket)

        return {
            "requests_in_window": current,
            "limit": limit,
            "remaining": max(0, limit - current),
            "window_seconds": WINDOW_SECONDS,
            "tier": tier,
            "total_blocked": self._stats.get(api_key, 0),
        }

    def reset(self, api_key: str) -> None:
        """Manually clear the rate limit bucket for an API key."""
        with self._lock:
            self._buckets[api_key].clear()
            self._stats[api_key] = 0
        logger.info(f"[RateLimit] Reset bucket for {api_key[:12]}…")


# Singleton shared across the app
_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """FastAPI dependency — returns the shared RateLimiter instance."""
    return _limiter


async def enforce_rate_limit(request: Request, api_key: str, tier: str = "free") -> None:
    """
    Raise HTTP 429 if the API key has exceeded its rate limit.

    Call this from route handlers or as a sub-dependency.
    """
    if not _limiter.is_allowed(api_key, tier):
        usage = _limiter.get_usage(api_key, tier)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": usage["limit"],
                "window_seconds": WINDOW_SECONDS,
                "retry_after": WINDOW_SECONDS,
                "tier": tier,
            },
            headers={"Retry-After": str(WINDOW_SECONDS)},
        )
