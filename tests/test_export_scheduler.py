"""
Tests for ExportPipeline and TaskScheduler.
"""

import pytest
import os
import json

from shopsage.export.pipeline import ExportPipeline
from shopsage.workers.scheduler import TaskScheduler
from shopsage.workers.job_queue import JobQueue


# ─── Export Pipeline Tests ─────────────────────────────────────────────


@pytest.fixture
def pipeline(tmp_path):
    return ExportPipeline(db_path=str(tmp_path / "test_export.db"))


def test_export_usage_csv(pipeline, tmp_path):
    """Should export usage data as CSV."""
    # Record some usage first
    pipeline._usage.record_usage("t1", api_calls=100, date_str="2026-05-01")
    pipeline._usage.record_usage("t1", api_calls=200, date_str="2026-05-02")

    result = pipeline.export_usage("t1", "2026-05", fmt="csv")
    assert result["row_count"] == 2
    assert result["format"] == "csv"
    assert os.path.exists(result["filepath"])
    assert result["file_size_bytes"] > 0


def test_export_usage_json(pipeline):
    """Should export usage data as JSON."""
    pipeline._usage.record_usage("t2", api_calls=50, date_str="2026-06-01")

    result = pipeline.export_usage("t2", "2026-06", fmt="json")
    assert result["format"] == "json"
    assert os.path.exists(result["filepath"])

    # Verify JSON is valid
    with open(result["filepath"]) as f:
        data = json.load(f)
        assert data["count"] == 1


def test_export_audit_log(pipeline):
    """Should export audit log entries."""
    pipeline._audit.record("a1", "admin", "create", "tenant", "t1")
    pipeline._audit.record("a1", "admin", "delete", "tenant", "t2")

    result = pipeline.export_audit_log(tenant_id="a1", fmt="csv")
    assert result["row_count"] == 2


def test_export_search_analytics(pipeline):
    """Should export search analytics."""
    pipeline._search.track("s1", "Nike shoes", "shopping", 5)
    pipeline._search.track("s2", "Adidas", "shopping", 3)

    result = pipeline.export_search_analytics(hours=1, fmt="json")
    assert result["row_count"] == 2


def test_list_exports(pipeline):
    """Should list all generated exports."""
    pipeline._usage.record_usage("t1", api_calls=10, date_str="2026-05-01")
    pipeline.export_usage("t1", "2026-05")
    pipeline.export_usage("t1", "2026-05", fmt="json")

    exports = pipeline.list_exports()
    assert len(exports) == 2


def test_get_export(pipeline):
    """Should retrieve export by ID."""
    pipeline._usage.record_usage("t1", api_calls=10, date_str="2026-05-01")
    result = pipeline.export_usage("t1", "2026-05")

    retrieved = pipeline.get_export(result["export_id"])
    assert retrieved is not None
    assert retrieved["export_id"] == result["export_id"]


# ─── Task Scheduler Tests ─────────────────────────────────────────────


@pytest.fixture
def scheduler(tmp_path):
    queue = JobQueue(db_path=str(tmp_path / "test_sched.db"))
    return TaskScheduler(job_queue=queue)


def test_register_task(scheduler):
    """Should register a recurring task."""
    def my_handler(payload):
        pass

    scheduler.register(
        name="test_task",
        job_type="test.task",
        handler=my_handler,
        interval_seconds=60,
        description="A test task",
    )

    tasks = scheduler.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["name"] == "test_task"
    assert tasks[0]["interval_seconds"] == 60


def test_disable_enable_task(scheduler):
    """Should disable and enable tasks."""
    def handler(p):
        pass

    scheduler.register("t1", "type.t1", handler, 60)
    assert scheduler.disable("t1") is True

    task = scheduler.get_task("t1")
    assert task["enabled"] is False

    assert scheduler.enable("t1") is True
    task = scheduler.get_task("t1")
    assert task["enabled"] is True


def test_unregister_task(scheduler):
    """Should remove a registered task."""
    def handler(p):
        pass

    scheduler.register("removable", "type.r", handler, 60)
    assert scheduler.unregister("removable") is True
    assert len(scheduler.list_tasks()) == 0


def test_get_nonexistent_task(scheduler):
    """Should return None for unknown tasks."""
    assert scheduler.get_task("ghost") is None
