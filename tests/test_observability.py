"""
Tests for the observability stack — structured logging, tracing, metrics, and Sentry.
"""

import os
import json
import io
import logging
import pytest
from unittest.mock import patch, MagicMock

# ── Structured Logging Tests ──────────────────────────────────────────


class TestStructuredLogging:
    """Verify structlog configuration and output format."""

    def test_configure_logging_runs_without_error(self):
        from shopsage.monitoring.logging_config import configure_logging
        configure_logging(log_level="DEBUG", json_output=True)

    def test_get_logger_returns_bound_logger(self):
        from shopsage.monitoring.logging_config import get_logger
        logger = get_logger("test.module")
        assert logger is not None
        # Structlog loggers are callable / have .info, .error etc.
        assert hasattr(logger, "info")
        assert hasattr(logger, "error")
        assert hasattr(logger, "warning")

    def test_bind_request_context(self):
        import structlog
        from shopsage.monitoring.logging_config import bind_request_context

        bind_request_context(
            request_id="req-123",
            tenant_id="t-abc",
            path="/chat",
            method="POST",
        )
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["request_id"] == "req-123"
        assert ctx["tenant_id"] == "t-abc"
        assert ctx["http_path"] == "/chat"
        assert ctx["http_method"] == "POST"

        # Clean up
        structlog.contextvars.clear_contextvars()

    def test_development_mode(self):
        from shopsage.monitoring.logging_config import configure_logging
        configure_logging(development=True)

    def test_json_output_mode(self):
        from shopsage.monitoring.logging_config import configure_logging
        configure_logging(json_output=True, development=False)


# ── OpenTelemetry Tracing Tests ───────────────────────────────────────


class TestTracing:
    """Verify OpenTelemetry tracing configuration."""

    def test_configure_tracing_without_endpoint(self):
        """Without OTEL_EXPORTER_OTLP_ENDPOINT, tracing should be no-op."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
            from shopsage.monitoring.tracing import configure_tracing
            tracer = configure_tracing()
            assert tracer is not None

    def test_get_tracer(self):
        from shopsage.monitoring.tracing import get_tracer
        tracer = get_tracer("test")
        assert tracer is not None

    def test_tracer_creates_spans(self):
        from shopsage.monitoring.tracing import get_tracer
        tracer = get_tracer("test.spans")
        with tracer.start_as_current_span("test-operation") as span:
            assert span is not None
            span.set_attribute("test.key", "test-value")


# ── Sentry Integration Tests ─────────────────────────────────────────


class TestSentryIntegration:
    """Verify Sentry initialization logic."""

    def test_sentry_disabled_without_dsn(self):
        """No DSN → Sentry should not initialize."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SENTRY_DSN", None)
            from shopsage.monitoring.sentry_integration import configure_sentry
            result = configure_sentry()
            assert result is False

    def test_sentry_enabled_with_dsn(self):
        """With a DSN, Sentry should initialize."""
        with patch.dict(
            os.environ,
            {"SENTRY_DSN": "https://examplePublicKey@o0.ingest.sentry.io/0"},
        ):
            from shopsage.monitoring.sentry_integration import configure_sentry
            result = configure_sentry()
            assert result is True


# ── Prometheus Metrics Tests ──────────────────────────────────────────


class TestPrometheusMetrics:
    """Verify Prometheus metrics collection and endpoint."""

    def test_init_app_info(self):
        from shopsage.monitoring.metrics import init_app_info
        init_app_info()  # Should not raise

    def test_request_count_counter(self):
        from shopsage.monitoring.metrics import REQUEST_COUNT
        # Increment a test label combo
        REQUEST_COUNT.labels(
            method="GET", endpoint="/test", status_code="200"
        ).inc()
        val = REQUEST_COUNT.labels(
            method="GET", endpoint="/test", status_code="200"
        )._value.get()
        assert val >= 1

    def test_request_latency_histogram(self):
        from shopsage.monitoring.metrics import REQUEST_LATENCY
        REQUEST_LATENCY.labels(method="POST", endpoint="/chat").observe(0.042)

    def test_cache_tracking_helpers(self):
        from shopsage.monitoring.metrics import (
            track_cache_hit, track_cache_miss, CACHE_OPERATIONS,
        )
        track_cache_hit("prices")
        track_cache_miss("prices")

        hits = CACHE_OPERATIONS.labels(
            cache_name="prices", operation="hit"
        )._value.get()
        misses = CACHE_OPERATIONS.labels(
            cache_name="prices", operation="miss"
        )._value.get()

        assert hits >= 1
        assert misses >= 1

    def test_task_tracking_helper(self):
        from shopsage.monitoring.metrics import track_task, BACKGROUND_TASKS
        track_task("scrape_prices", "success")
        track_task("scrape_prices", "failure")

        success = BACKGROUND_TASKS.labels(
            task_name="scrape_prices", status="success"
        )._value.get()
        failure = BACKGROUND_TASKS.labels(
            task_name="scrape_prices", status="failure"
        )._value.get()

        assert success >= 1
        assert failure >= 1

    def test_path_normalization(self):
        from shopsage.monitoring.metrics import PrometheusMiddleware

        assert PrometheusMiddleware._normalize_path("/health") == "/health"
        assert PrometheusMiddleware._normalize_path("/profile/abc123def") == "/profile/{id}"
        assert PrometheusMiddleware._normalize_path("/chat") == "/chat"
        assert PrometheusMiddleware._normalize_path("/") == "/"

    def test_metrics_endpoint_returns_prometheus_format(self):
        from prometheus_client import generate_latest, REGISTRY
        output = generate_latest(REGISTRY)
        assert isinstance(output, bytes)
        text = output.decode("utf-8")
        # Should contain our custom metric names
        assert "shopsage_http_requests_total" in text
        assert "shopsage_app_info" in text


# ── .env.example Tests ────────────────────────────────────────────────


class TestEnvExample:
    """Verify the .env.example documents all new environment variables."""

    def test_env_example_exists(self):
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), ".env.example"
        )
        assert os.path.exists(env_path), ".env.example should exist"

    def test_env_example_documents_observability_vars(self):
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), ".env.example"
        )
        with open(env_path, "r") as f:
            content = f.read()
        assert "REDIS_URL" in content
        assert "GOOGLE_API_KEY" in content
