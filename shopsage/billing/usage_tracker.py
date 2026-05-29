"""
Usage Tracker — Daily metering for tenant usage.

Records API requests, agent invocations, and searches per tenant
on a daily basis. This data feeds into the billing engine and
the admin analytics dashboard.

Schema:
    daily_usage: tenant_id, date, api_calls, agent_runs, searches, cost_incurred
"""

import sqlite3
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.billing.usage")


class UsageTracker:
    """
    Tracks daily usage metrics for SaaS tenants.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create daily_usage table."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS daily_usage (
                        tenant_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        api_calls INTEGER DEFAULT 0,
                        agent_runs INTEGER DEFAULT 0,
                        searches INTEGER DEFAULT 0,
                        cost_incurred REAL DEFAULT 0.0,
                        PRIMARY KEY (tenant_id, date)
                    )
                """)
                conn.commit()
            logger.info("[UsageTracker] Initialized")
        except sqlite3.Error as e:
            logger.error(f"[UsageTracker] Init error: {e}")
            raise

    def record_usage(
        self,
        tenant_id: str,
        api_calls: int = 0,
        agent_runs: int = 0,
        searches: int = 0,
        cost: float = 0.0,
        date_str: str = None,
    ) -> None:
        """
        Increment usage metrics for a tenant for the given day.
        If date_str is None, uses today's date (YYYY-MM-DD).
        """
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO daily_usage 
                       (tenant_id, date, api_calls, agent_runs, searches, cost_incurred)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(tenant_id, date) DO UPDATE SET
                       api_calls = api_calls + excluded.api_calls,
                       agent_runs = agent_runs + excluded.agent_runs,
                       searches = searches + excluded.searches,
                       cost_incurred = cost_incurred + excluded.cost_incurred""",
                    (tenant_id, date_str, api_calls, agent_runs, searches, cost),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"[UsageTracker] Record error: {e}")

    def get_monthly_usage(self, tenant_id: str, year_month: str) -> Dict[str, Any]:
        """
        Get total usage for a specific month (format: YYYY-MM).
        """
        try:
            with self._conn() as conn:
                row = conn.execute(
                    """SELECT SUM(api_calls) as total_api_calls,
                              SUM(agent_runs) as total_agent_runs,
                              SUM(searches) as total_searches,
                              SUM(cost_incurred) as total_cost
                       FROM daily_usage
                       WHERE tenant_id = ? AND date LIKE ?""",
                    (tenant_id, f"{year_month}%"),
                ).fetchone()

                return {
                    "tenant_id": tenant_id,
                    "month": year_month,
                    "api_calls": row["total_api_calls"] or 0,
                    "agent_runs": row["total_agent_runs"] or 0,
                    "searches": row["total_searches"] or 0,
                    "cost": round(row["total_cost"] or 0.0, 4),
                }
        except sqlite3.Error as e:
            logger.error(f"[UsageTracker] Fetch error: {e}")
            return {}

    def get_daily_breakdown(
        self, tenant_id: str, year_month: str
    ) -> List[Dict[str, Any]]:
        """
        Get day-by-day breakdown of usage for a month.
        """
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT date, api_calls, agent_runs, searches, cost_incurred
                       FROM daily_usage
                       WHERE tenant_id = ? AND date LIKE ?
                       ORDER BY date ASC""",
                    (tenant_id, f"{year_month}%"),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[UsageTracker] Breakdown error: {e}")
            return []
