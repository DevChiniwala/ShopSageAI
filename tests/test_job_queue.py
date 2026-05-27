"""
Tests for JobQueue and AdminDashboard.
"""

import pytest
import time

from shopsage.workers.job_queue import JobQueue


# ─── Job Queue Tests ───────────────────────────────────────────────────


@pytest.fixture
def queue(tmp_path):
    return JobQueue(db_path=str(tmp_path / "test_jobs.db"))


def test_enqueue_job(queue):
    """Should enqueue a job and return an ID."""
    job_id = queue.enqueue("send_email", {"to": "user@test.com"})
    assert job_id
    assert queue.get_pending_count() == 1


def test_process_job(queue):
    """Should process a job with a registered handler."""
    results = []

    def email_handler(payload):
        results.append(payload["to"])

    queue.register_handler("send_email", email_handler)
    queue.enqueue("send_email", {"to": "user@test.com"})

    processed = queue.process_next()
    assert processed is True
    assert results == ["user@test.com"]

    # Job should be completed
    assert queue.get_pending_count() == 0


def test_priority_ordering(queue):
    """Higher priority jobs should be processed first."""
    results = []

    def handler(payload):
        results.append(payload["order"])

    queue.register_handler("task", handler)
    queue.enqueue("task", {"order": "low"}, priority=0)
    queue.enqueue("task", {"order": "high"}, priority=10)
    queue.enqueue("task", {"order": "medium"}, priority=5)

    queue.process_next()
    queue.process_next()
    queue.process_next()

    assert results == ["high", "medium", "low"]


def test_retry_on_failure(queue):
    """Failed jobs should be retried up to max_retries."""
    call_count = [0]

    def flaky_handler(payload):
        call_count[0] += 1
        if call_count[0] < 3:
            raise ValueError("Temporary failure")

    queue.register_handler("flaky", flaky_handler)
    queue.enqueue("flaky", {}, max_retries=3)

    # First attempt - fails, schedules retry
    queue.process_next()
    assert call_count[0] == 1


def test_job_failure_after_max_retries(queue):
    """Jobs should fail permanently after max retries."""
    def always_fails(payload):
        raise ValueError("Permanent failure")

    queue.register_handler("bad", always_fails)
    queue.enqueue("bad", {}, max_retries=1)

    queue.process_next()

    stats = queue.get_stats()
    assert stats["queue"]["failed"] == 1


def test_cancel_job(queue):
    """Should cancel a pending job."""
    job_id = queue.enqueue("task", {})
    assert queue.cancel_job(job_id) is True
    assert queue.get_pending_count() == 0


def test_get_job(queue):
    """Should retrieve job details."""
    job_id = queue.enqueue("export", {"format": "csv"}, priority=5)
    job = queue.get_job(job_id)
    assert job is not None
    assert job["job_type"] == "export"
    assert job["priority"] == 5
    assert job["status"] == "pending"


def test_delayed_job(queue):
    """Delayed jobs should not be processed until scheduled time."""
    def handler(payload):
        pass

    queue.register_handler("delayed", handler)
    queue.enqueue("delayed", {}, delay_seconds=3600)  # 1 hour delay

    # Should not find any eligible jobs
    processed = queue.process_next()
    assert processed is False


def test_stats(queue):
    """Should track queue statistics."""
    def handler(payload):
        pass

    queue.register_handler("task", handler)
    queue.enqueue("task", {})
    queue.enqueue("task", {})
    queue.process_next()

    stats = queue.get_stats()
    assert stats["queue"]["pending"] == 1
    assert stats["queue"]["completed"] == 1
    assert stats["lifetime"]["enqueued"] == 2


def test_no_handler_fails_job(queue):
    """Jobs with no registered handler should fail."""
    queue.enqueue("unknown_type", {})
    queue.process_next()

    stats = queue.get_stats()
    assert stats["queue"]["failed"] == 1
