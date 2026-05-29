"""
Admin Dashboard — Aggregated statistics API for ShopSage AI.

Provides a single endpoint that collects metrics from all
subsystems (tenants, billing, cache, health, events, jobs,
analytics) into a unified admin overview.
"""

import logging
from typing import Dict, Any

from shopsage.auth.tenant_store import TenantStore
from shopsage.billing.usage_tracker import UsageTracker
from shopsage.analytics.search_tracker import SearchTracker
from shopsage.notifications.notification_center import NotificationCenter
from shopsage.security.audit_log import AuditLog
from shopsage.monitoring.health import HealthChecker
from shopsage.cache.distributed_cache import price_cache, review_cache, embedding_cache
from shopsage.events.event_bus import get_event_bus
from shopsage.workers.job_queue import JobQueue
from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.admin.dashboard")


class AdminDashboard:
    """
    Aggregates metrics from all subsystems into a single admin view.

    Designed to power the admin dashboard UI with real-time stats.
    """

    def __init__(self, db_path: str = DB_PATH):
        self._tenants = TenantStore(db_path)
        self._usage = UsageTracker(db_path)
        self._search = SearchTracker(db_path)
        self._notifications = NotificationCenter(db_path)
        self._audit = AuditLog(db_path)
        self._health = HealthChecker(db_path)
        self._jobs = JobQueue(db_path)

    def get_overview(self) -> Dict[str, Any]:
        """
        Get a full admin dashboard overview.

        Returns:
            Dict with tenant, system, cache, events, and analytics data.
        """
        return {
            "tenants": self._get_tenant_stats(),
            "system": self._get_system_health(),
            "cache": self._get_cache_stats(),
            "events": self._get_event_stats(),
            "jobs": self._get_job_stats(),
            "search": self._get_search_stats(),
            "audit": self._get_audit_summary(),
        }

    def _get_tenant_stats(self) -> Dict[str, Any]:
        """Tenant overview."""
        try:
            tenants = self._tenants.get_all_tenants()
            plan_counts = {"free": 0, "pro": 0, "enterprise": 0}
            active_count = 0

            for t in tenants:
                plan = t.get("plan", "free")
                plan_counts[plan] = plan_counts.get(plan, 0) + 1
                if t.get("is_active"):
                    active_count += 1

            return {
                "total": len(tenants),
                "active": active_count,
                "by_plan": plan_counts,
            }
        except Exception as e:
            logger.error(f"[Dashboard] Tenant stats error: {e}")
            return {"total": 0, "active": 0, "by_plan": {}}

    def _get_system_health(self) -> Dict[str, Any]:
        """System health overview."""
        try:
            health = self._health.get_health()
            return {
                "status": health.get("status", "unknown"),
                "components": health.get("checks", {}),
            }
        except Exception as e:
            logger.error(f"[Dashboard] Health error: {e}")
            return {"status": "error", "components": {}}

    def _get_cache_stats(self) -> Dict[str, Any]:
        """Cache performance metrics."""
        try:
            return {
                "price_cache": price_cache.stats,
                "review_cache": review_cache.stats,
                "embedding_cache": embedding_cache.stats,
            }
        except Exception as e:
            logger.error(f"[Dashboard] Cache stats error: {e}")
            return {}

    def _get_event_stats(self) -> Dict[str, Any]:
        """Event bus statistics."""
        try:
            bus = get_event_bus()
            return bus.get_stats()
        except Exception as e:
            logger.error(f"[Dashboard] Event stats error: {e}")
            return {}

    def _get_job_stats(self) -> Dict[str, Any]:
        """Background job queue statistics."""
        try:
            return self._jobs.get_stats()
        except Exception as e:
            logger.error(f"[Dashboard] Job stats error: {e}")
            return {}

    def _get_search_stats(self) -> Dict[str, Any]:
        """Search analytics summary."""
        try:
            volume = self._search.get_search_volume(hours=24)
            popular = self._search.get_popular_queries(limit=5, hours=24)
            demand = self._search.get_zero_result_queries(limit=5, hours=48)

            return {
                "last_24h": volume,
                "top_queries": popular,
                "unmet_demand": demand,
            }
        except Exception as e:
            logger.error(f"[Dashboard] Search stats error: {e}")
            return {}

    def _get_audit_summary(self) -> Dict[str, Any]:
        """Recent audit activity."""
        try:
            action_counts = self._audit.count_actions(hours=24)
            recent = self._audit.get_recent(limit=5)

            return {
                "actions_24h": action_counts,
                "recent_entries": [
                    {
                        "action": e["action"],
                        "resource_type": e["resource_type"],
                        "actor_type": e["actor_type"],
                        "timestamp": e["timestamp"],
                    }
                    for e in recent
                ],
            }
        except Exception as e:
            logger.error(f"[Dashboard] Audit stats error: {e}")
            return {}
