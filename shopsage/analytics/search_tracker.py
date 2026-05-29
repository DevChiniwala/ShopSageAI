"""
Search Analytics — Track and analyze user search patterns.

Records every search query to identify trending products,
popular categories, and demand signals for merchant insights.

Schema:
    search_queries: id, session_id, query, route, result_count, timestamp
"""

import sqlite3
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.analytics.search")


class SearchTracker:
    """
    SQLite-backed search query analytics.

    Tracks:
    - Every search query with session attribution
    - Popular queries over time windows
    - Zero-result queries (demand signals)
    - Search volume trends
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create search_queries table."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS search_queries (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        query TEXT NOT NULL,
                        normalized_query TEXT NOT NULL,
                        route TEXT DEFAULT '',
                        result_count INTEGER DEFAULT 0,
                        timestamp TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_search_ts
                    ON search_queries(timestamp)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_search_norm
                    ON search_queries(normalized_query)
                """)
                conn.commit()
            logger.info("[SearchTracker] Initialized")
        except sqlite3.Error as e:
            logger.error(f"[SearchTracker] Init error: {e}")
            raise

    # ─── Write ─────────────────────────────────────────────────────

    def track(
        self,
        session_id: str,
        query: str,
        route: str = "",
        result_count: int = 0,
    ) -> None:
        """Record a search query."""
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO search_queries
                       (id, session_id, query, normalized_query, route, result_count, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), session_id, query,
                     self._normalize(query), route, result_count,
                     datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"[SearchTracker] Track error: {e}")

    # ─── Analytics ─────────────────────────────────────────────────

    def get_popular_queries(
        self, limit: int = 20, hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get the most popular search queries in the last N hours.

        Returns list of {query, count, avg_results}.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT normalized_query as query,
                              COUNT(*) as count,
                              ROUND(AVG(result_count), 1) as avg_results
                       FROM search_queries
                       WHERE timestamp > ?
                       GROUP BY normalized_query
                       ORDER BY count DESC
                       LIMIT ?""",
                    (cutoff, limit),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[SearchTracker] Popular error: {e}")
            return []

    def get_zero_result_queries(
        self, limit: int = 20, hours: int = 48
    ) -> List[Dict[str, Any]]:
        """
        Get queries that returned zero results — demand signals.

        These represent products users want but aren't in inventory.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT normalized_query as query,
                              COUNT(*) as count
                       FROM search_queries
                       WHERE result_count = 0 AND timestamp > ?
                       GROUP BY normalized_query
                       ORDER BY count DESC
                       LIMIT ?""",
                    (cutoff, limit),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[SearchTracker] Zero-result error: {e}")
            return []

    def get_search_volume(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get search volume statistics for the last N hours.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        try:
            with self._conn() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) as total,
                              COUNT(DISTINCT session_id) as unique_sessions,
                              COUNT(DISTINCT normalized_query) as unique_queries,
                              ROUND(AVG(result_count), 1) as avg_results
                       FROM search_queries
                       WHERE timestamp > ?""",
                    (cutoff,),
                ).fetchone()

                return {
                    "period_hours": hours,
                    "total_searches": row["total"],
                    "unique_sessions": row["unique_sessions"],
                    "unique_queries": row["unique_queries"],
                    "avg_results_per_search": row["avg_results"] or 0,
                }
        except sqlite3.Error as e:
            logger.error(f"[SearchTracker] Volume error: {e}")
            return {"period_hours": hours, "total_searches": 0}

    def get_hourly_trend(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get search counts grouped by hour for the last N hours.

        Useful for traffic pattern visualization.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT SUBSTR(timestamp, 1, 13) as hour,
                              COUNT(*) as count
                       FROM search_queries
                       WHERE timestamp > ?
                       GROUP BY hour
                       ORDER BY hour ASC""",
                    (cutoff,),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[SearchTracker] Trend error: {e}")
            return []

    @staticmethod
    def _normalize(query: str) -> str:
        """Normalize a query for grouping (lowercase, strip, collapse spaces)."""
        import re
        return re.sub(r"\s+", " ", query.strip().lower())
