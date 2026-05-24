"""
Tests for TTL Cache — verifies TTL expiry, LRU eviction, namespaces, and stats.
"""

import time
import pytest
from shopsage.cache.ttl_cache import TTLCache


@pytest.fixture
def cache():
    """Fresh TTLCache for each test."""
    return TTLCache(default_ttl=5, max_size=10, name="test")


def test_set_and_get(cache):
    """Basic set/get should work."""
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"


def test_get_missing_key(cache):
    """Missing keys should return None."""
    assert cache.get("nonexistent") is None


def test_ttl_expiry(cache):
    """Entries should expire after TTL."""
    cache.set("expire-me", "data", ttl=0)  # instant expiry
    time.sleep(0.01)
    assert cache.get("expire-me") is None


def test_lru_eviction():
    """When max_size is reached, LRU entries should be evicted."""
    small_cache = TTLCache(default_ttl=60, max_size=3, name="lru-test")
    small_cache.set("a", 1)
    small_cache.set("b", 2)
    small_cache.set("c", 3)

    # Cache is full, adding "d" should evict "a" (LRU)
    small_cache.set("d", 4)

    assert small_cache.get("a") is None  # evicted
    assert small_cache.get("b") == 2
    assert small_cache.get("d") == 4


def test_access_refreshes_lru():
    """Accessing an entry should move it to most recently used."""
    small_cache = TTLCache(default_ttl=60, max_size=3, name="lru-refresh")
    small_cache.set("a", 1)
    small_cache.set("b", 2)
    small_cache.set("c", 3)

    # Access "a" to make it most recently used
    small_cache.get("a")

    # Now "b" is LRU, so adding "d" should evict "b"
    small_cache.set("d", 4)

    assert small_cache.get("a") == 1  # still alive
    assert small_cache.get("b") is None  # evicted


def test_delete(cache):
    """delete should remove a key."""
    cache.set("del-me", "data")
    assert cache.delete("del-me") is True
    assert cache.get("del-me") is None
    assert cache.delete("del-me") is False


def test_clear(cache):
    """clear should remove all entries."""
    cache.set("a", 1)
    cache.set("b", 2)
    count = cache.clear()
    assert count == 2
    assert cache.size == 0


def test_namespace_operations(cache):
    """Namespace get/set/invalidate should work."""
    cache.set_ns("prices", "nike", [100, 200])
    cache.set_ns("prices", "adidas", [150, 250])
    cache.set_ns("reviews", "nike", {"rating": 4.5})

    assert cache.get_ns("prices", "nike") == [100, 200]
    assert cache.get_ns("reviews", "nike") == {"rating": 4.5}

    # Invalidate only prices namespace
    removed = cache.invalidate_namespace("prices")
    assert removed == 2
    assert cache.get_ns("prices", "nike") is None
    assert cache.get_ns("reviews", "nike") == {"rating": 4.5}


def test_stats_tracking(cache):
    """Stats should track hits, misses, and sets."""
    cache.set("stats-key", "data")
    cache.get("stats-key")  # hit
    cache.get("stats-key")  # hit
    cache.get("missing")    # miss

    stats = cache.stats
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["sets"] == 1
    assert stats["hit_rate_pct"] == pytest.approx(66.7, abs=0.1)


def test_overwrite_existing_key(cache):
    """Setting an existing key should update it."""
    cache.set("key", "v1")
    cache.set("key", "v2")
    assert cache.get("key") == "v2"


def test_exists(cache):
    """exists should return True for valid keys."""
    cache.set("exists-key", "data")
    assert cache.exists("exists-key") is True
    assert cache.exists("nope") is False
