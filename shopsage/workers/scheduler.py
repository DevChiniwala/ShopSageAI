"""
Task Scheduler — Cron-like recurring task definitions for ShopSage AI.

Wraps the JobQueue to provide recurring scheduled tasks like:
- Nightly data exports
- Cache cleanup
- Stale notification purging
- Usage report generation
- Health check broadcasts

Tasks are defined declaratively and registered at startup.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, Any, List, Optional
from dataclasses import dataclass, field

from shopsage.workers.job_queue import JobQueue
from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.workers.scheduler")


@dataclass
class ScheduledTask:
    """A recurring task definition."""
    name: str
    job_type: str
    interval_seconds: int
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    enabled: bool = True
    last_run: Optional[str] = None
    run_count: int = 0
    description: str = ""


class TaskScheduler:
    """
    Manages recurring scheduled tasks.

    Instead of cron expressions, uses simple interval-based scheduling.
    Each task is enqueued into the JobQueue at its scheduled interval.
    """

    def __init__(self, job_queue: Optional[JobQueue] = None, db_path: str = DB_PATH):
        self._queue = job_queue or JobQueue(db_path)
        self._tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ─── Task Registration ─────────────────────────────────────────

    def register(
        self,
        name: str,
        job_type: str,
        handler: Callable,
        interval_seconds: int,
        payload: Optional[Dict[str, Any]] = None,
        priority: int = 0,
        description: str = "",
    ) -> None:
        """
        Register a recurring task.

        Args:
            name: Unique task name.
            job_type: The job type key for the queue.
            handler: The function to execute.
            interval_seconds: How often to run (in seconds).
            payload: Static payload to pass to handler.
            priority: Job priority (higher = sooner).
            description: Human-readable description.
        """
        self._tasks[name] = ScheduledTask(
            name=name,
            job_type=job_type,
            interval_seconds=interval_seconds,
            payload=payload or {},
            priority=priority,
            description=description,
        )
        self._queue.register_handler(job_type, handler)
        logger.info(
            f"[Scheduler] Registered '{name}' "
            f"(every {interval_seconds}s, type={job_type})"
        )

    def unregister(self, name: str) -> bool:
        """Remove a scheduled task."""
        if name in self._tasks:
            del self._tasks[name]
            return True
        return False

    def enable(self, name: str) -> bool:
        """Enable a disabled task."""
        if name in self._tasks:
            self._tasks[name].enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a task without removing it."""
        if name in self._tasks:
            self._tasks[name].enabled = False
            return True
        return False

    # ─── Scheduler Loop ───────────────────────────────────────────

    def start(self, check_interval: float = 10.0) -> None:
        """Start the scheduler thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._scheduler_loop,
            args=(check_interval,),
            daemon=True,
        )
        self._thread.start()
        logger.info("[Scheduler] Started")

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[Scheduler] Stopped")

    def _scheduler_loop(self, check_interval: float) -> None:
        """Main loop — checks which tasks are due and enqueues them."""
        while self._running:
            try:
                now = datetime.utcnow()

                for task in self._tasks.values():
                    if not task.enabled:
                        continue

                    # Check if task is due
                    if task.last_run:
                        last = datetime.fromisoformat(task.last_run)
                        next_run = last + timedelta(seconds=task.interval_seconds)
                        if now < next_run:
                            continue

                    # Enqueue the task
                    self._queue.enqueue(
                        job_type=task.job_type,
                        payload={**task.payload, "_task_name": task.name},
                        priority=task.priority,
                    )

                    task.last_run = now.isoformat()
                    task.run_count += 1

                    logger.info(
                        f"[Scheduler] Enqueued '{task.name}' "
                        f"(run #{task.run_count})"
                    )

            except Exception as e:
                logger.error(f"[Scheduler] Loop error: {e}")

            time.sleep(check_interval)

    # ─── Queries ───────────────────────────────────────────────────

    def list_tasks(self) -> List[Dict[str, Any]]:
        """List all registered tasks."""
        return [
            {
                "name": t.name,
                "job_type": t.job_type,
                "interval_seconds": t.interval_seconds,
                "enabled": t.enabled,
                "last_run": t.last_run,
                "run_count": t.run_count,
                "description": t.description,
            }
            for t in self._tasks.values()
        ]

    def get_task(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a single task's details."""
        task = self._tasks.get(name)
        if not task:
            return None
        return {
            "name": task.name,
            "job_type": task.job_type,
            "interval_seconds": task.interval_seconds,
            "enabled": task.enabled,
            "last_run": task.last_run,
            "run_count": task.run_count,
            "description": task.description,
        }


# ─── Built-in Task Handlers ───────────────────────────────────────────

def _handle_cache_cleanup(payload: Dict[str, Any]) -> None:
    """Purge expired entries from all caches."""
    from shopsage.cache.ttl_cache import price_cache, review_cache, embedding_cache
    for cache in [price_cache, review_cache, embedding_cache]:
        cache.clear_expired()
    logger.info("[Task] Cache cleanup complete")


def _handle_notification_purge(payload: Dict[str, Any]) -> None:
    """Delete old read notifications."""
    from shopsage.notifications.notification_center import NotificationCenter
    center = NotificationCenter()
    deleted = center.purge_old(days=30)
    logger.info(f"[Task] Purged {deleted} old notifications")


def _handle_job_purge(payload: Dict[str, Any]) -> None:
    """Delete old completed jobs."""
    from shopsage.workers.job_queue import JobQueue
    queue = JobQueue()
    deleted = queue.purge_completed(days=7)
    logger.info(f"[Task] Purged {deleted} old jobs")


def register_default_tasks(scheduler: TaskScheduler) -> None:
    """Register built-in recurring tasks."""
    scheduler.register(
        name="cache_cleanup",
        job_type="scheduled.cache_cleanup",
        handler=_handle_cache_cleanup,
        interval_seconds=3600,  # hourly
        description="Purge expired cache entries",
    )

    scheduler.register(
        name="notification_purge",
        job_type="scheduled.notification_purge",
        handler=_handle_notification_purge,
        interval_seconds=86400,  # daily
        description="Delete read notifications older than 30 days",
    )

    scheduler.register(
        name="job_purge",
        job_type="scheduled.job_purge",
        handler=_handle_job_purge,
        interval_seconds=86400,  # daily
        description="Delete completed jobs older than 7 days",
    )

    logger.info(f"[Scheduler] Registered {len(scheduler.list_tasks())} default tasks")
