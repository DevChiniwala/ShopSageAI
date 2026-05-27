"""
Job Queue — Persistent background job system for ShopSage AI.

Stores jobs in SQLite with status tracking, retry logic, and
priority ordering. Workers poll for pending jobs and execute
registered handler functions.

Schema:
    jobs: id, job_type, payload, status, priority, max_retries,
          retry_count, error, scheduled_at, started_at,
          completed_at, created_at

Statuses: pending → running → completed | failed | cancelled
"""

import sqlite3
import uuid
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from collections import defaultdict

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.workers.job_queue")


class JobQueue:
    """
    SQLite-backed persistent job queue.

    Supports:
    - Priority ordering (higher = sooner)
    - Automatic retries with backoff
    - Scheduled jobs (future execution)
    - Job type handlers registration
    - Status tracking and history
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._handlers: Dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._stats: Dict[str, int] = defaultdict(int)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create jobs table."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        job_type TEXT NOT NULL,
                        payload TEXT DEFAULT '{}',
                        status TEXT DEFAULT 'pending',
                        priority INTEGER DEFAULT 0,
                        max_retries INTEGER DEFAULT 3,
                        retry_count INTEGER DEFAULT 0,
                        error TEXT,
                        scheduled_at TEXT,
                        started_at TEXT,
                        completed_at TEXT,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_job_status
                    ON jobs(status, priority DESC, scheduled_at)
                """)
                conn.commit()
            logger.info("[JobQueue] Initialized")
        except sqlite3.Error as e:
            logger.error(f"[JobQueue] Init error: {e}")
            raise

    # ─── Job Submission ────────────────────────────────────────────

    def enqueue(
        self,
        job_type: str,
        payload: Optional[Dict[str, Any]] = None,
        priority: int = 0,
        max_retries: int = 3,
        delay_seconds: int = 0,
    ) -> str:
        """
        Add a job to the queue.

        Args:
            job_type: Handler key (e.g. "send_email", "sync_prices").
            payload: JSON-serializable data for the handler.
            priority: Higher = executed sooner. Default 0.
            max_retries: Max retry attempts on failure.
            delay_seconds: Delay before the job becomes eligible.

        Returns:
            The job ID.
        """
        job_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        scheduled_at = now
        if delay_seconds > 0:
            scheduled_at = (
                datetime.utcnow() + timedelta(seconds=delay_seconds)
            ).isoformat()

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO jobs
                       (id, job_type, payload, status, priority,
                        max_retries, retry_count, scheduled_at, created_at)
                       VALUES (?, ?, ?, 'pending', ?, ?, 0, ?, ?)""",
                    (job_id, job_type, json.dumps(payload or {}),
                     priority, max_retries, scheduled_at, now),
                )
                conn.commit()

            self._stats["enqueued"] += 1
            logger.info(
                f"[JobQueue] Enqueued '{job_type}' (id={job_id[:8]}, "
                f"priority={priority})"
            )
            return job_id

        except sqlite3.Error as e:
            logger.error(f"[JobQueue] Enqueue error: {e}")
            raise

    # ─── Handler Registration ──────────────────────────────────────

    def register_handler(self, job_type: str, handler: Callable) -> None:
        """Register a handler function for a job type."""
        self._handlers[job_type] = handler
        logger.info(f"[JobQueue] Registered handler for '{job_type}'")

    # ─── Job Processing ───────────────────────────────────────────

    def process_next(self) -> bool:
        """
        Process the next eligible job.

        Returns True if a job was processed, False if queue is empty.
        """
        now = datetime.utcnow().isoformat()

        try:
            with self._conn() as conn:
                # Fetch next eligible job
                row = conn.execute(
                    """SELECT * FROM jobs
                       WHERE status = 'pending' AND scheduled_at <= ?
                       ORDER BY priority DESC, created_at ASC
                       LIMIT 1""",
                    (now,),
                ).fetchone()

                if not row:
                    return False

                job = dict(row)
                job_id = job["id"]

                # Mark as running
                conn.execute(
                    "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                    (now, job_id),
                )
                conn.commit()

        except sqlite3.Error as e:
            logger.error(f"[JobQueue] Fetch error: {e}")
            return False

        # Execute handler
        handler = self._handlers.get(job["job_type"])
        if not handler:
            self._fail_job(job_id, f"No handler for job_type '{job['job_type']}'")
            return True

        try:
            payload = json.loads(job["payload"])
            handler(payload)
            self._complete_job(job_id)
            self._stats["completed"] += 1
            return True

        except Exception as e:
            retry_count = job["retry_count"] + 1
            if retry_count < job["max_retries"]:
                self._retry_job(job_id, retry_count, str(e))
                self._stats["retried"] += 1
            else:
                self._fail_job(job_id, str(e))
                self._stats["failed"] += 1
            return True

    def _complete_job(self, job_id: str) -> None:
        """Mark job as completed."""
        now = datetime.utcnow().isoformat()
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE jobs SET status = 'completed', completed_at = ? WHERE id = ?",
                    (now, job_id),
                )
                conn.commit()
            logger.info(f"[JobQueue] ✅ Completed job {job_id[:8]}")
        except sqlite3.Error as e:
            logger.error(f"[JobQueue] Complete error: {e}")

    def _fail_job(self, job_id: str, error: str) -> None:
        """Mark job as failed."""
        now = datetime.utcnow().isoformat()
        try:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE jobs SET status = 'failed',
                       error = ?, completed_at = ? WHERE id = ?""",
                    (error[:500], now, job_id),
                )
                conn.commit()
            logger.error(f"[JobQueue] ❌ Failed job {job_id[:8]}: {error[:100]}")
        except sqlite3.Error as e:
            logger.error(f"[JobQueue] Fail error: {e}")

    def _retry_job(self, job_id: str, retry_count: int, error: str) -> None:
        """Schedule a retry with exponential backoff."""
        backoff = (retry_count ** 2) * 5  # 5s, 20s, 45s...
        scheduled_at = (
            datetime.utcnow() + timedelta(seconds=backoff)
        ).isoformat()

        try:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE jobs SET status = 'pending',
                       retry_count = ?, error = ?, scheduled_at = ?
                       WHERE id = ?""",
                    (retry_count, error[:500], scheduled_at, job_id),
                )
                conn.commit()
            logger.warning(
                f"[JobQueue] ↻ Retrying job {job_id[:8]} "
                f"(attempt {retry_count}, backoff {backoff}s)"
            )
        except sqlite3.Error as e:
            logger.error(f"[JobQueue] Retry error: {e}")

    # ─── Background Worker ────────────────────────────────────────

    def start_worker(self, poll_interval: float = 2.0) -> None:
        """Start the background worker thread."""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(poll_interval,),
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("[JobQueue] Worker started")

    def stop_worker(self) -> None:
        """Stop the background worker."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logger.info("[JobQueue] Worker stopped")

    def _worker_loop(self, poll_interval: float) -> None:
        """Main worker loop — polls for pending jobs."""
        while self._running:
            try:
                processed = self.process_next()
                if not processed:
                    time.sleep(poll_interval)
            except Exception as e:
                logger.error(f"[JobQueue] Worker error: {e}")
                time.sleep(poll_interval)

    # ─── Queries ───────────────────────────────────────────────────

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                return dict(row) if row else None
        except sqlite3.Error:
            return None

    def get_pending_count(self) -> int:
        """Count pending jobs."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM jobs WHERE status = 'pending'"
                ).fetchone()
                return row["cnt"]
        except sqlite3.Error:
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        try:
            with self._conn() as conn:
                counts = {}
                for status in ["pending", "running", "completed", "failed"]:
                    row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM jobs WHERE status = ?",
                        (status,),
                    ).fetchone()
                    counts[status] = row["cnt"]

                return {
                    "queue": counts,
                    "lifetime": dict(self._stats),
                    "registered_handlers": list(self._handlers.keys()),
                }
        except sqlite3.Error:
            return {}

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending job."""
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "UPDATE jobs SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                    (job_id,),
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error:
            return False

    def purge_completed(self, days: int = 7) -> int:
        """Delete completed jobs older than N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "DELETE FROM jobs WHERE status IN ('completed', 'cancelled') AND completed_at < ?",
                    (cutoff,),
                )
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error:
            return 0
