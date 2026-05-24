"""
TTL Cache — Thread-safe in-memory cache with time-based expiry and LRU eviction.

Designed for caching expensive operations like price scraping results,
API responses, and embedding computations. Supports:
- Configurable TTL per entry or global default
- LRU eviction when max capacity is reached
- Hit/miss statistics for monitoring
- Thread-safe via threading.Lock
- Namespace isolation for multi-tenant caching
"""

import time
import logging
from collections import OrderedDict
from threading import Lock
from dataclasses import dataclass, field
from typing import Any, Optional, Dict

logger = logging.getLogger("shopsage.cache")


@dataclass
class CacheEntry:
    """A single cached value with metadata."""
    key: str
    value: Any
    created_at: float
    expires_at: float
    hit_count: int = 0
    size_hint: int = 0  # approximate size in bytes


class TTLCache:
    """
    Thread-safe TTL cache with LRU eviction.

    When the cache exceeds max_size, the least recently used
    entries are evicted first. Expired entries are lazily removed
    on access and periodically during writes.

    Usage:
        cache = TTLCache(default_ttl=300, max_size=1000)
        cache.set("prices:nike-shoes", results, ttl=600)
        data = cache.get("prices:nike-shoes")
    """

    def __init__(
        self,
        default_ttl: int = 300,
        max_size: int = 500,
        name: str = "default",
    ):
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.name = name
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = Lock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expirations": 0,
            "sets": 0,
        }

    # ─── Core Operations ───────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve a value from cache.

        Returns None if the key doesn't exist or has expired.
        Moves accessed entries to the end (most recently used).
        """
        with self._lock:
            entry = self._store.get(key)

            if entry is None:
                self._stats["misses"] += 1
                return None

            # Check expiry
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                self._stats["expirations"] += 1
                self._stats["misses"] += 1
                return None

            # Move to end (most recently used)
            self._store.move_to_end(key)
            entry.hit_count += 1
            self._stats["hits"] += 1

            return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        size_hint: int = 0,
    ) -> None:
        """
        Store a value in cache with optional custom TTL.

        If the cache is full, evicts the least recently used entry.
        """
        effective_ttl = ttl if ttl is not None else self.default_ttl
        now = time.monotonic()

        entry = CacheEntry(
            key=key,
            value=value,
            created_at=now,
            expires_at=now + effective_ttl,
            size_hint=size_hint,
        )

        with self._lock:
            # If key exists, update it
            if key in self._store:
                self._store[key] = entry
                self._store.move_to_end(key)
            else:
                # Evict if at capacity
                self._evict_if_needed()
                self._store[key] = entry

            self._stats["sets"] += 1

            # Periodic cleanup every 50 writes
            if self._stats["sets"] % 50 == 0:
                self._cleanup_expired()

    def delete(self, key: str) -> bool:
        """Remove a specific key from cache."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def exists(self, key: str) -> bool:
        """Check if a key exists and hasn't expired."""
        return self.get(key) is not None

    def clear(self) -> int:
        """Clear all cache entries. Returns count of entries cleared."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    # ─── Namespaced Keys ───────────────────────────────────────────

    def ns_key(self, namespace: str, key: str) -> str:
        """Build a namespaced cache key: 'prices:nike-shoes'."""
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
        prefix = f"{namespace}:"
        with self._lock:
            keys_to_delete = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._store[k]
            return len(keys_to_delete)

    # ─── Statistics ────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        """Return cache performance statistics."""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0

            return {
                "name": self.name,
                "size": len(self._store),
                "max_size": self.max_size,
                "hit_rate_pct": round(hit_rate, 1),
                **self._stats,
            }

    @property
    def size(self) -> int:
        """Current number of entries in cache."""
        return len(self._store)

    # ─── Internal ──────────────────────────────────────────────────

    def _evict_if_needed(self) -> None:
        """Evict LRU entries if cache is at max capacity. Must hold lock."""
        while len(self._store) >= self.max_size:
            evicted_key, _ = self._store.popitem(last=False)
            self._stats["evictions"] += 1
            logger.debug(f"[Cache:{self.name}] Evicted LRU: {evicted_key[:30]}")

    def _cleanup_expired(self) -> None:
        """Remove expired entries. Must hold lock."""
        now = time.monotonic()
        expired = [
            k for k, v in self._store.items() if now > v.expires_at
        ]
        for k in expired:
            del self._store[k]
            self._stats["expirations"] += 1


# ─── Singleton Caches ──────────────────────────────────────────────────

# Price scraper results (5 min TTL, up to 200 queries)
price_cache = TTLCache(default_ttl=300, max_size=200, name="prices")

# Review analysis results (15 min TTL)
review_cache = TTLCache(default_ttl=900, max_size=100, name="reviews")

# Embedding results (1 hour TTL)
embedding_cache = TTLCache(default_ttl=3600, max_size=500, name="embeddings")
