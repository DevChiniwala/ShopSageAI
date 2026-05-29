"""
Redis Rate Limiter — Distributed sliding window rate limiting backed by Redis.

Uses Redis sorted sets for precise sliding-window counting that works
correctly across multiple application processes / containers.
Falls back to the existing in-memory RateLimiter when Redis is unavailable.
"""

import os
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("shopsage.auth.redis_rate_limiter")

# ── Tier Limits ────────────────────────────────────────────────────────

TIER_LIMITS: dict[str, int] = {
    "free": 30,
    "starter": 50,
    "pro": 120,
    "professional": 200,
    "enterprise": 9999,
}
WINDOW_SECONDS = 60


class RedisRateLimiter:
    """
    Sliding window rate limiter using Redis sorted sets.

    Each API key gets a sorted set where members are unique request IDs
    and scores are timestamps. On each check we:
      1. Remove entries older than the window
      2. Count remaining entries
      3. Add the new request if under limit

    This is atomic via a Redis pipeline, so it's safe across processes.
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._connected = redis_client is not None
        self._prefix = "shopsage:ratelimit:"

        # In-memory fallback (same structure as original rate_limiter.py)
        self._local_buckets: Dict[str, list] = {}
        self._local_stats: Dict[str, int] = {}

        backend = "redis" if self._connected else "memory"
        logger.info("[RateLimiter] Initialised (backend=%s)", backend)

    def is_allowed(self, api_key: str, tier: str = "free") -> bool:
        """
        Check if a request from `api_key` is within rate limits.
        Returns True if allowed, False if rate-limited.
        """
        limit = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        now = time.time()
        window_start = now - WINDOW_SECONDS

        if self._connected:
            return self._check_redis(api_key, limit, now, window_start)
        else:
            return self._check_local(api_key, limit, now, window_start)

    def get_usage(self, api_key: str, tier: str = "free") -> dict:
        """Return current usage info for an API key."""
        limit = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        now = time.time()
        window_start = now - WINDOW_SECONDS

        if self._connected:
            key = self._prefix + api_key
            try:
                self._redis.zremrangebyscore(key, "-inf", window_start)
                current = self._redis.zcard(key)
            except Exception:
                current = 0
        else:
            bucket = self._local_buckets.get(api_key, [])
            bucket = [t for t in bucket if t > window_start]
            self._local_buckets[api_key] = bucket
            current = len(bucket)

        return {
            "requests_in_window": current,
            "limit": limit,
            "remaining": max(0, limit - current),
            "window_seconds": WINDOW_SECONDS,
            "tier": tier,
            "total_blocked": self._local_stats.get(api_key, 0),
            "backend": "redis" if self._connected else "memory",
        }

    def reset(self, api_key: str) -> None:
        """Clear the rate limit bucket for an API key."""
        if self._connected:
            try:
                self._redis.delete(self._prefix + api_key)
            except Exception:
                pass
        self._local_buckets.pop(api_key, None)
        self._local_stats.pop(api_key, None)
        logger.info("[RateLimiter] Reset bucket for %s", api_key[:12])

    # ── Redis Implementation ───────────────────────────────────────

    def _check_redis(
        self, api_key: str, limit: int, now: float, window_start: float
    ) -> bool:
        key = self._prefix + api_key
        try:
            pipe = self._redis.pipeline(True)
            pipe.zremrangebyscore(key, "-inf", window_start)
            pipe.zcard(key)
            pipe.zadd(key, {f"{now}:{id(self)}": now})
            pipe.expire(key, WINDOW_SECONDS + 5)
            results = pipe.execute()

            current_count = results[1]  # zcard result before adding

            if current_count >= limit:
                # Over limit — remove the entry we just added
                self._redis.zrem(key, f"{now}:{id(self)}")
                self._local_stats[api_key] = self._local_stats.get(api_key, 0) + 1
                logger.warning(
                    "[RateLimiter] BLOCKED %s (%d/%d, tier detected)",
                    api_key[:12], current_count, limit,
                )
                return False

            return True
        except Exception as e:
            logger.error("[RateLimiter] Redis error, allowing request: %s", e)
            return True  # Fail-open on Redis errors

    # ── In-Memory Fallback ─────────────────────────────────────────

    def _check_local(
        self, api_key: str, limit: int, now: float, window_start: float
    ) -> bool:
        if api_key not in self._local_buckets:
            self._local_buckets[api_key] = []

        bucket = self._local_buckets[api_key]
        # Evict old entries
        self._local_buckets[api_key] = [t for t in bucket if t > window_start]
        bucket = self._local_buckets[api_key]

        if len(bucket) >= limit:
            self._local_stats[api_key] = self._local_stats.get(api_key, 0) + 1
            logger.warning(
                "[RateLimiter] BLOCKED %s (%d/%d)",
                api_key[:12], len(bucket), limit,
            )
            return False

        bucket.append(now)
        return True

    @property
    def is_redis(self) -> bool:
        """Whether this limiter is backed by Redis."""
        return self._connected


# ── Factory & FastAPI Dependencies ──────────────────────────────────────

def create_rate_limiter(redis_client=None) -> RedisRateLimiter:
    """Create a rate limiter, using Redis if a client is provided."""
    return RedisRateLimiter(redis_client=redis_client)

# Shared instance for FastAPI
from shopsage.cache.distributed_cache import _get_shared_client
_shared_limiter = create_rate_limiter(_get_shared_client())

def get_rate_limiter() -> RedisRateLimiter:
    return _shared_limiter

from fastapi import Request, HTTPException

async def enforce_rate_limit(request: Request, api_key: str, tier: str = "free") -> None:
    if not _shared_limiter.is_allowed(api_key, tier):
        usage = _shared_limiter.get_usage(api_key, tier)
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
