"""
Tests for the rate limiter — verifies sliding window logic and tier limits.
"""

import time
import pytest
from shopsage.auth.redis_rate_limiter import RedisRateLimiter as RateLimiter, TIER_LIMITS


@pytest.fixture
def limiter():
    """Fresh RateLimiter for each test."""
    return RateLimiter()


def test_free_tier_allows_requests_within_limit(limiter):
    """Free tier should allow up to 30 requests."""
    limit = TIER_LIMITS["free"]
    for _ in range(limit):
        assert limiter.is_allowed("test-key", "free") is True


def test_free_tier_blocks_over_limit(limiter):
    """Free tier should block the 31st request."""
    limit = TIER_LIMITS["free"]
    for _ in range(limit):
        limiter.is_allowed("test-key", "free")
    assert limiter.is_allowed("test-key", "free") is False


def test_pro_tier_has_higher_limit(limiter):
    """Pro tier limit should be higher than free tier."""
    assert TIER_LIMITS["pro"] > TIER_LIMITS["free"]


def test_enterprise_is_effectively_unlimited(limiter):
    """Enterprise tier should allow many requests."""
    for _ in range(200):
        assert limiter.is_allowed("enterprise-key", "enterprise") is True


def test_different_keys_have_independent_buckets(limiter):
    """Rate limits should be per-key, not global."""
    limit = TIER_LIMITS["free"]
    for _ in range(limit):
        limiter.is_allowed("key-a", "free")

    # key-a is blocked, key-b should still work
    assert limiter.is_allowed("key-a", "free") is False
    assert limiter.is_allowed("key-b", "free") is True


def test_reset_clears_bucket(limiter):
    """After reset, a previously blocked key should be allowed again."""
    limit = TIER_LIMITS["free"]
    for _ in range(limit + 1):
        limiter.is_allowed("reset-key", "free")

    assert limiter.is_allowed("reset-key", "free") is False
    limiter.reset("reset-key")
    assert limiter.is_allowed("reset-key", "free") is True


def test_get_usage_returns_correct_remaining(limiter):
    """get_usage should accurately report remaining requests."""
    limit = TIER_LIMITS["free"]
    used = 5
    for _ in range(used):
        limiter.is_allowed("usage-key", "free")

    usage = limiter.get_usage("usage-key", "free")
    assert usage["requests_in_window"] == used
    assert usage["remaining"] == limit - used
    assert usage["limit"] == limit


def test_stats_track_blocked_requests(limiter):
    """total_blocked should increment when requests are denied."""
    limit = TIER_LIMITS["free"]
    for _ in range(limit + 3):
        limiter.is_allowed("block-key", "free")

    usage = limiter.get_usage("block-key", "free")
    assert usage["total_blocked"] == 3
