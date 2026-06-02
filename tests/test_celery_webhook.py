"""Regression tests for Celery webhook dispatch."""

from pathlib import Path


def test_dispatch_webhook_task_uses_asyncio_run():
    """Webhook Celery task must await async dispatch via asyncio.run."""
    source = Path("shopsage/workers/tasks.py").read_text(encoding="utf-8")
    assert "asyncio.run" in source
    assert "dispatcher.dispatch" in source
    assert "settings.DB_PATH" in source
    assert "from shopsage.config import DB_PATH" not in source


def test_dispatch_webhook_task_does_not_import_invalid_db_path():
    source = Path("shopsage/workers/tasks.py").read_text(encoding="utf-8")
    assert "WebhookStore(db_path=" not in source or "settings.DB_PATH" in source
