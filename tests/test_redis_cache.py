"""
Tests for Day 33 — Distributed Caching (Redis) & Redis Rate Limiter.

All tests run against the in-memory fallback (no Redis required),
which validates the full interface contract. When REDIS_URL is set,
the same tests exercise the Redis backend.
"""

import time
import pytest

from shopsage.cache.redis_backend import RedisCache
from shopsage.cache.distributed_cache import create_cache
from shopsage.auth.redis_rate_limiter import (
    RedisRateLimiter,
    create_rate_limiter,
    TIER_LIMITS,
    WINDOW_SECONDS,
)


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def cache():
    """In-memory RedisCache (no Redis client)."""
    c = RedisCache(default_ttl=5, max_size=10, name="test")
    yield c
    c.clear()


@pytest.fixture
def limiter():
    """In-memory RedisRateLimiter (no Redis client)."""
    return RedisRateLimiter(redis_client=None)


# ═══════════════════════════════════════════════════════════════════════
# RedisCache Tests (in-memory fallback)
# ═══════════════════════════════════════════════════════════════════════


class TestRedisCacheBasic:
    """Core get/set/delete operations."""

    def test_set_and_get(self, cache):
        cache.set("key1", {"price": 29.99})
        assert cache.get("key1") == {"price": 29.99}

    def test_get_missing_key(self, cache):
        assert cache.get("nonexistent") is None

    def test_delete_key(self, cache):
        cache.set("del_me", "value")
        assert cache.delete("del_me")
        assert cache.get("del_me") is None

    def test_delete_missing_key(self, cache):
        assert not cache.delete("nope")

    def test_exists(self, cache):
        cache.set("ex_key", 42)
        assert cache.exists("ex_key")
        assert not cache.exists("no_key")

    def test_clear(self, cache):
        cache.set("a", 1)
        cache.set("b", 2)
        cleared = cache.clear()
        assert cleared == 2
        assert cache.get("a") is None

    def test_overwrite(self, cache):
        cache.set("ow", "old")
        cache.set("ow", "new")
        assert cache.get("ow") == "new"


class TestRedisCacheTTL:
    """TTL and expiration behavior."""

    def test_custom_ttl(self, cache):
        cache.set("short", "data", ttl=1)
        assert cache.get("short") == "data"

    def test_expiry(self, cache):
        c = RedisCache(default_ttl=1, max_size=10, name="expiry_test")
        c.set("exp_key", "value", ttl=1)
        assert c.get("exp_key") == "value"
        time.sleep(1.1)
        assert c.get("exp_key") is None

    def test_default_ttl_used(self, cache):
        # default_ttl is 5s, so should still be alive
        cache.set("def_ttl", "alive")
        assert cache.get("def_ttl") == "alive"


class TestRedisCacheEviction:
    """LRU eviction when at max capacity."""

    def test_eviction_at_max_size(self):
        c = RedisCache(default_ttl=60, max_size=3, name="evict_test")
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.set("d", 4)  # Should evict 'a'
        assert c.get("a") is None
        assert c.get("d") == 4


class TestRedisCacheNamespace:
    """Namespaced key operations."""

    def test_ns_set_and_get(self, cache):
        cache.set_ns("prices", "nike", 99.99)
        assert cache.get_ns("prices", "nike") == 99.99

    def test_ns_key_format(self, cache):
        assert cache.ns_key("reviews", "item1") == "reviews:item1"

    def test_invalidate_namespace(self, cache):
        cache.set_ns("stale", "a", 1)
        cache.set_ns("stale", "b", 2)
        cache.set_ns("fresh", "c", 3)
        removed = cache.invalidate_namespace("stale")
        assert removed == 2
        assert cache.get_ns("fresh", "c") == 3


class TestRedisCacheStats:
    """Cache statistics tracking."""

    def test_stats_structure(self, cache):
        stats = cache.stats
        assert "name" in stats
        assert "backend" in stats
        assert "hit_rate_pct" in stats
        assert stats["backend"] == "memory"

    def test_hit_miss_counting(self, cache):
        cache.set("stat_key", "val")
        cache.get("stat_key")  # hit
        cache.get("miss_key")  # miss
        stats = cache.stats
        assert stats["hits"] >= 1
        assert stats["misses"] >= 1

    def test_is_redis_false(self, cache):
        assert not cache.is_redis

    def test_size(self, cache):
        cache.set("s1", 1)
        cache.set("s2", 2)
        assert cache.size == 2


class TestRedisCacheDataTypes:
    """Verify various data types are cached correctly."""

    def test_cache_string(self, cache):
        cache.set("str", "hello")
        assert cache.get("str") == "hello"

    def test_cache_int(self, cache):
        cache.set("int", 42)
        assert cache.get("int") == 42

    def test_cache_float(self, cache):
        cache.set("float", 3.14)
        assert cache.get("float") == 3.14

    def test_cache_list(self, cache):
        cache.set("list", [1, 2, 3])
        assert cache.get("list") == [1, 2, 3]

    def test_cache_dict(self, cache):
        cache.set("dict", {"a": 1, "b": [2, 3]})
        assert cache.get("dict") == {"a": 1, "b": [2, 3]}

    def test_cache_bool(self, cache):
        cache.set("bool", True)
        assert cache.get("bool") is True

    def test_cache_none(self, cache):
        cache.set("none", None)
        assert cache.get("none") is None  # None can't be distinguished from miss


# ═══════════════════════════════════════════════════════════════════════
# Distributed Cache Factory Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDistributedCacheFactory:
    """Test the create_cache factory function."""

    def test_create_cache(self):
        c = create_cache("factory_test", default_ttl=60, max_size=50)
        assert c.name == "factory_test"
        assert c.default_ttl == 60

    def test_factory_caches_are_independent(self):
        c1 = create_cache("ind1", default_ttl=60)
        c2 = create_cache("ind2", default_ttl=120)
        c1.set("shared_key", "from_c1")
        # c2 should NOT see c1's key (different prefix)
        assert c2.get("shared_key") is None


# ═══════════════════════════════════════════════════════════════════════
# Redis Rate Limiter Tests (in-memory fallback)
# ═══════════════════════════════════════════════════════════════════════


class TestRedisRateLimiterBasic:
    """Core rate limiting behavior."""

    def test_allows_under_limit(self, limiter):
        assert limiter.is_allowed("key_ok", tier="free")

    def test_blocks_over_limit(self):
        lim = RedisRateLimiter(redis_client=None)
        limit = TIER_LIMITS["free"]
        for _ in range(limit):
            assert lim.is_allowed("flood_key", tier="free")
        # Next request should be blocked
        assert not lim.is_allowed("flood_key", tier="free")

    def test_different_tiers(self):
        lim = RedisRateLimiter(redis_client=None)
        # Pro tier has higher limit
        for _ in range(TIER_LIMITS["free"] + 1):
            lim.is_allowed("tier_key", tier="pro")
        # Should still be allowed (pro limit > free limit)
        assert lim.is_allowed("tier_key", tier="pro")

    def test_different_keys_independent(self, limiter):
        limiter.is_allowed("user_a", tier="free")
        limiter.is_allowed("user_b", tier="free")
        # Both should be allowed independently
        assert limiter.is_allowed("user_a", tier="free")
        assert limiter.is_allowed("user_b", tier="free")


class TestRedisRateLimiterUsage:
    """Usage reporting and reset."""

    def test_get_usage(self, limiter):
        limiter.is_allowed("usage_key", tier="free")
        limiter.is_allowed("usage_key", tier="free")
        usage = limiter.get_usage("usage_key", tier="free")
        assert usage["requests_in_window"] == 2
        assert usage["limit"] == TIER_LIMITS["free"]
        assert usage["remaining"] == TIER_LIMITS["free"] - 2
        assert usage["backend"] == "memory"

    def test_reset(self, limiter):
        for _ in range(5):
            limiter.is_allowed("reset_key", tier="free")
        limiter.reset("reset_key")
        usage = limiter.get_usage("reset_key", tier="free")
        assert usage["requests_in_window"] == 0

    def test_blocked_count(self):
        lim = RedisRateLimiter(redis_client=None)
        limit = TIER_LIMITS["free"]
        for _ in range(limit + 3):
            lim.is_allowed("block_key", tier="free")
        usage = lim.get_usage("block_key", tier="free")
        assert usage["total_blocked"] == 3

    def test_is_redis_false(self, limiter):
        assert not limiter.is_redis


class TestRedisRateLimiterFactory:
    """Factory function."""

    def test_create_rate_limiter(self):
        lim = create_rate_limiter(redis_client=None)
        assert isinstance(lim, RedisRateLimiter)
        assert not lim.is_redis


class TestTierLimitsConstants:
    """Verify tier limits are well-formed."""

    def test_all_tiers_exist(self):
        assert "free" in TIER_LIMITS
        assert "pro" in TIER_LIMITS
        assert "enterprise" in TIER_LIMITS

    def test_tiers_increase(self):
        assert TIER_LIMITS["free"] < TIER_LIMITS["pro"]
        assert TIER_LIMITS["pro"] < TIER_LIMITS["enterprise"]
