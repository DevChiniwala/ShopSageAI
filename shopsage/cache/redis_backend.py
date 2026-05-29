"""
Redis Backend — Connection management and Redis-backed cache implementation.

Provides a RedisCache class with the same interface as TTLCache but backed
by Redis for distributed, multi-process consistency. Falls back gracefully
to in-memory mode when Redis is unavailable.
"""

import os
import json
import time
import logging
import hashlib
from typing import Any, Optional, Dict

logger = logging.getLogger("shopsage.cache.redis")

# Redis connection URL from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _get_redis_client():
    """
    Create a Redis client. Returns None if Redis is unavailable.
    This is a lazy factory — import errors or connection failures are handled.
    """
    try:
        import redis
        client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True,
        )
        # Verify connectivity
        client.ping()
        logger.info("[Redis] Connected to %s", REDIS_URL)
        return client
    except Exception as e:
        logger.warning("[Redis] Unavailable (%s), will use in-memory fallback", e)
        return None


class RedisCache:
    """
    Distributed TTL cache backed by Redis.

    Maintains the same public interface as TTLCache so it can be used
    as a drop-in replacement. Values are JSON-serialised.

    If Redis is unavailable at init time, falls back to a local
    in-memory dict (useful for dev/testing without Redis running).
    """

    def __init__(
        self,
        default_ttl: int = 300,
        max_size: int = 500,
        name: str = "default",
        redis_client=None,
    ):
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.name = name
        self._prefix = f"shopsage:{name}:"
        self._redis = redis_client
        self._connected = self._redis is not None

        # In-memory fallback
        self._local: Dict[str, Any] = {}
        self._local_expiry: Dict[str, float] = {}

        # Stats (kept in-process for speed; can optionally be pushed to Redis)
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "evictions": 0,
            "expirations": 0,
        }

    # ── Core Operations ────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value. Returns None on miss or expiry."""
        full_key = self._prefix + key

        if self._connected:
            try:
                raw = self._redis.get(full_key)
                if raw is None:
                    self._stats["misses"] += 1
                    return None
                self._stats["hits"] += 1
                return json.loads(raw)
            except Exception:
                self._stats["misses"] += 1
                return None
        else:
            # In-memory fallback
            if key in self._local:
                if time.monotonic() > self._local_expiry.get(key, 0):
                    del self._local[key]
                    del self._local_expiry[key]
                    self._stats["expirations"] += 1
                    self._stats["misses"] += 1
                    return None
                self._stats["hits"] += 1
                return self._local[key]
            self._stats["misses"] += 1
            return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> None:
        """Store a value with optional custom TTL."""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        full_key = self._prefix + key

        if self._connected:
            try:
                self._redis.setex(full_key, effective_ttl, json.dumps(value))
            except Exception as e:
                logger.warning("[RedisCache:%s] set failed: %s", self.name, e)
        else:
            self._local[key] = value
            self._local_expiry[key] = time.monotonic() + effective_ttl
            # LRU eviction for in-memory
            if len(self._local) > self.max_size:
                oldest = next(iter(self._local))
                del self._local[oldest]
                del self._local_expiry[oldest]
                self._stats["evictions"] += 1

        self._stats["sets"] += 1

    def delete(self, key: str) -> bool:
        """Remove a specific key."""
        full_key = self._prefix + key
        if self._connected:
            try:
                return bool(self._redis.delete(full_key))
            except Exception:
                return False
        else:
            if key in self._local:
                del self._local[key]
                self._local_expiry.pop(key, None)
                return True
            return False

    def exists(self, key: str) -> bool:
        """Check if a key exists and hasn't expired."""
        return self.get(key) is not None

    def clear(self) -> int:
        """Clear all entries in this cache's namespace."""
        if self._connected:
            try:
                pattern = self._prefix + "*"
                keys = self._redis.keys(pattern)
                if keys:
                    return self._redis.delete(*keys)
                return 0
            except Exception:
                return 0
        else:
            count = len(self._local)
            self._local.clear()
            self._local_expiry.clear()
            return count

    # ── Namespaced Keys ────────────────────────────────────────────

    def ns_key(self, namespace: str, key: str) -> str:
        """Build a namespaced cache key."""
        return f"{namespace}:{key}"

    def get_ns(self, namespace: str, key: str) -> Optional[Any]:
        """Get with namespace prefix."""
        return self.get(self.ns_key(namespace, key))

    def set_ns(
        self, namespace: str, key: str, value: Any, ttl: Optional[int] = None
    ) -> None:
        """Set with namespace prefix."""
        self.set(self.ns_key(namespace, key), value, ttl)

    def invalidate_namespace(self, namespace: str) -> int:
        """Remove all entries with a given namespace prefix."""
        ns_prefix = f"{namespace}:"
        if self._connected:
            try:
                pattern = self._prefix + ns_prefix + "*"
                keys = self._redis.keys(pattern)
                if keys:
                    return self._redis.delete(*keys)
                return 0
            except Exception:
                return 0
        else:
            keys_to_delete = [k for k in self._local if k.startswith(ns_prefix)]
            for k in keys_to_delete:
                del self._local[k]
                self._local_expiry.pop(k, None)
            return len(keys_to_delete)

    # ── Statistics ─────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        """Return cache performance statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0

        size = 0
        if self._connected:
            try:
                pattern = self._prefix + "*"
                keys = self._redis.keys(pattern)
                size = len(keys)
            except Exception:
                pass
        else:
            size = len(self._local)

        return {
            "name": self.name,
            "backend": "redis" if self._connected else "memory",
            "size": size,
            "max_size": self.max_size,
            "hit_rate_pct": round(hit_rate, 1),
            **self._stats,
        }

    @property
    def size(self) -> int:
        """Current number of entries."""
        if self._connected:
            try:
                return len(self._redis.keys(self._prefix + "*"))
            except Exception:
                return 0
        return len(self._local)

    @property
    def is_redis(self) -> bool:
        """Whether this cache is backed by Redis."""
        return self._connected
