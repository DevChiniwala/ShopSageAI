"""
Rate Limit Analytics — Persistent tracking and reporting of rate limit
events for ShopSage AI tenants.

Records every rate-limit check (allowed/blocked) into SQLite and provides:
- Per-tenant usage summaries (requests, blocks, block rate)
- Hourly/daily trend data for dashboards
- Top consumers ranking
- Burst detection (sudden spikes in request volume)
- Historical window replay for debugging

This complements the in-memory RateLimiter with durable analytics
that survive process restarts.
"""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta, timezone
from typing import Any, Dict, List, Optional
from threading import Lock

from shopsage.config import settings

logger = logging.getLogger("shopsage.analytics.rate_limit_analytics")


class RateLimitAnalytics:
    """
    SQLite-backed rate limit analytics engine.

    Tracks every rate-limit decision and provides aggregated
    reporting for admin dashboards and alerting.
    """

    def __init__(self, db_path: str = settings.DB_PATH) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        """Create the rate_limit_events table."""
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS rate_limit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id TEXT NOT NULL,
                        api_key_prefix TEXT NOT NULL,
                        tier TEXT NOT NULL DEFAULT 'free',
                        action TEXT NOT NULL,
                        endpoint TEXT DEFAULT '',
                        requests_in_window INTEGER DEFAULT 0,
                        limit_value INTEGER DEFAULT 0,
                        remaining INTEGER DEFAULT 0,
                        blocked INTEGER DEFAULT 0,
                        timestamp TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rle_tenant
                    ON rate_limit_events (tenant_id, timestamp)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rle_blocked
                    ON rate_limit_events (blocked, timestamp)
                """)
                conn.commit()
            finally:
                conn.close()

    # ─── Recording ────────────────────────────────────────────────────

    def record_event(
        self,
        tenant_id: str,
        api_key: str,
        tier: str,
        action: str,
        endpoint: str = "",
        requests_in_window: int = 0,
        limit_value: int = 0,
        remaining: int = 0,
        blocked: bool = False,
    ) -> None:
        """Record a single rate-limit check event."""
        now = datetime.now(timezone.utc).isoformat()
        key_prefix = api_key[:12] if api_key else "unknown"

        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """INSERT INTO rate_limit_events
                       (tenant_id, api_key_prefix, tier, action, endpoint,
                        requests_in_window, limit_value, remaining, blocked, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (tenant_id, key_prefix, tier, action, endpoint,
                     requests_in_window, limit_value, remaining,
                     1 if blocked else 0, now),
                )
                conn.commit()
            finally:
                conn.close()

    # ─── Tenant Summary ───────────────────────────────────────────────

    def get_tenant_summary(
        self, tenant_id: str, hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get rate-limit summary for a specific tenant over the last N hours.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).isoformat()

        conn = self._conn()
        try:
            row = conn.execute(
                """SELECT
                       COUNT(*) as total_requests,
                       SUM(blocked) as total_blocked,
                       MAX(requests_in_window) as peak_window_usage,
                       MAX(limit_value) as limit_value,
                       tier
                   FROM rate_limit_events
                   WHERE tenant_id = ? AND timestamp >= ?
                   GROUP BY tenant_id""",
                (tenant_id, cutoff),
            ).fetchone()

            if not row:
                return {
                    "tenant_id": tenant_id,
                    "period_hours": hours,
                    "total_requests": 0,
                    "total_blocked": 0,
                    "block_rate": 0.0,
                    "peak_window_usage": 0,
                    "limit": 0,
                    "tier": "unknown",
                }

            total = row["total_requests"]
            blocked = row["total_blocked"] or 0
            return {
                "tenant_id": tenant_id,
                "period_hours": hours,
                "total_requests": total,
                "total_blocked": blocked,
                "block_rate": round(blocked / total * 100, 2) if total > 0 else 0.0,
                "peak_window_usage": row["peak_window_usage"] or 0,
                "limit": row["limit_value"] or 0,
                "tier": row["tier"] or "unknown",
            }
        finally:
            conn.close()

    # ─── Hourly Trends ────────────────────────────────────────────────

    def get_hourly_trends(
        self, tenant_id: str = "", hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get hourly request/block counts, optionally filtered by tenant.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).isoformat()

        conn = self._conn()
        try:
            if tenant_id:
                rows = conn.execute(
                    """SELECT
                           substr(timestamp, 1, 13) as hour,
                           COUNT(*) as requests,
                           SUM(blocked) as blocked
                       FROM rate_limit_events
                       WHERE tenant_id = ? AND timestamp >= ?
                       GROUP BY hour ORDER BY hour""",
                    (tenant_id, cutoff),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT
                           substr(timestamp, 1, 13) as hour,
                           COUNT(*) as requests,
                           SUM(blocked) as blocked
                       FROM rate_limit_events
                       WHERE timestamp >= ?
                       GROUP BY hour ORDER BY hour""",
                    (cutoff,),
                ).fetchall()

            return [
                {
                    "hour": r["hour"],
                    "requests": r["requests"],
                    "blocked": r["blocked"] or 0,
                    "allowed": r["requests"] - (r["blocked"] or 0),
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ─── Top Consumers ────────────────────────────────────────────────

    def get_top_consumers(
        self, hours: int = 24, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Rank tenants by total request volume over the last N hours.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).isoformat()

        conn = self._conn()
        try:
            rows = conn.execute(
                """SELECT
                       tenant_id,
                       tier,
                       COUNT(*) as total_requests,
                       SUM(blocked) as total_blocked,
                       MAX(requests_in_window) as peak_usage
                   FROM rate_limit_events
                   WHERE timestamp >= ?
                   GROUP BY tenant_id
                   ORDER BY total_requests DESC
                   LIMIT ?""",
                (cutoff, limit),
            ).fetchall()

            return [
                {
                    "tenant_id": r["tenant_id"],
                    "tier": r["tier"],
                    "total_requests": r["total_requests"],
                    "total_blocked": r["total_blocked"] or 0,
                    "peak_usage": r["peak_usage"] or 0,
                    "block_rate": round(
                        (r["total_blocked"] or 0) / r["total_requests"] * 100, 2
                    ) if r["total_requests"] > 0 else 0.0,
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ─── Burst Detection ──────────────────────────────────────────────

    def detect_bursts(
        self, threshold_multiplier: float = 3.0, minutes: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Detect tenants with request bursts significantly above their
        recent average.

        A burst is when the last `minutes` window has >= threshold_multiplier
        times the tenant's average per-window request count.
        """
        now = datetime.now(timezone.utc)
        recent_cutoff = (now - timedelta(minutes=minutes)).isoformat()
        baseline_cutoff = (now - timedelta(hours=1)).isoformat()

        conn = self._conn()
        try:
            # Baseline: average requests per 5-min window over last hour
            baselines = conn.execute(
                """SELECT tenant_id, COUNT(*) * 1.0 / 12 as avg_per_window
                   FROM rate_limit_events
                   WHERE timestamp >= ?
                   GROUP BY tenant_id""",
                (baseline_cutoff,),
            ).fetchall()

            baseline_map = {
                r["tenant_id"]: r["avg_per_window"] for r in baselines
            }

            # Recent: requests in the last N minutes
            recents = conn.execute(
                """SELECT tenant_id, COUNT(*) as recent_count
                   FROM rate_limit_events
                   WHERE timestamp >= ?
                   GROUP BY tenant_id""",
                (recent_cutoff,),
            ).fetchall()

            bursts = []
            for r in recents:
                tid = r["tenant_id"]
                recent = r["recent_count"]
                avg = baseline_map.get(tid, 0)
                if avg > 0 and recent >= avg * threshold_multiplier:
                    bursts.append({
                        "tenant_id": tid,
                        "recent_requests": recent,
                        "average_per_window": round(avg, 1),
                        "multiplier": round(recent / avg, 1),
                        "threshold": threshold_multiplier,
                        "window_minutes": minutes,
                        "is_burst": True,
                    })

            return sorted(bursts, key=lambda x: x["multiplier"], reverse=True)
        finally:
            conn.close()

    # ─── Global Stats ─────────────────────────────────────────────────

    def get_global_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get system-wide rate limit statistics.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).isoformat()

        conn = self._conn()
        try:
            row = conn.execute(
                """SELECT
                       COUNT(*) as total_events,
                       SUM(blocked) as total_blocked,
                       COUNT(DISTINCT tenant_id) as unique_tenants,
                       MAX(requests_in_window) as global_peak
                   FROM rate_limit_events
                   WHERE timestamp >= ?""",
                (cutoff,),
            ).fetchone()

            tier_breakdown = conn.execute(
                """SELECT tier, COUNT(*) as count, SUM(blocked) as blocked
                   FROM rate_limit_events
                   WHERE timestamp >= ?
                   GROUP BY tier""",
                (cutoff,),
            ).fetchall()

            return {
                "period_hours": hours,
                "total_events": row["total_events"] or 0,
                "total_blocked": row["total_blocked"] or 0,
                "block_rate": round(
                    (row["total_blocked"] or 0) / row["total_events"] * 100, 2
                ) if row["total_events"] else 0.0,
                "unique_tenants": row["unique_tenants"] or 0,
                "global_peak_window": row["global_peak"] or 0,
                "by_tier": {
                    r["tier"]: {
                        "requests": r["count"],
                        "blocked": r["blocked"] or 0,
                    }
                    for r in tier_breakdown
                },
            }
        finally:
            conn.close()

    # ─── Cleanup ──────────────────────────────────────────────────────

    def purge_old_events(self, days: int = 30) -> int:
        """Delete events older than N days. Returns count deleted."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        with self._lock:
            conn = self._conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM rate_limit_events WHERE timestamp < ?",
                    (cutoff,),
                )
                conn.commit()
                deleted = cursor.rowcount
                logger.info(
                    f"[RateLimitAnalytics] Purged {deleted} events older than {days}d"
                )
                return deleted
            finally:
                conn.close()
