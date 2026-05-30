"""
Prometheus Metrics — Application metrics endpoint for ShopSage AI.

Exposes a /metrics endpoint that Prometheus can scrape, tracking:
- HTTP request counts, latencies, and in-flight requests
- Cache hit/miss rates
- Background task counts
- Application info (version, environment)

Usage:
    from shopsage.monitoring.metrics import metrics_app, track_request
    app.mount("/metrics", metrics_app)
"""

import os
import time
import logging
from typing import Optional

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    REGISTRY,
)
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

logger = logging.getLogger("shopsage.monitoring.metrics")


# ── Application-level metrics ──────────────────────────────────────────

APP_INFO = Info(
    "shopsage_app",
    "ShopSage AI application metadata",
)

REQUEST_COUNT = Counter(
    "shopsage_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "shopsage_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

REQUESTS_IN_PROGRESS = Gauge(
    "shopsage_http_requests_in_progress",
    "Number of HTTP requests currently being processed",
    ["method"],
)

CACHE_OPERATIONS = Counter(
    "shopsage_cache_operations_total",
    "Cache operations (hits and misses)",
    ["cache_name", "operation"],
)

BACKGROUND_TASKS = Counter(
    "shopsage_background_tasks_total",
    "Background tasks processed",
    ["task_name", "status"],
)

ACTIVE_CONNECTIONS = Gauge(
    "shopsage_active_websocket_connections",
    "Number of active WebSocket connections",
)


def init_app_info() -> None:
    """Set application metadata once at startup."""
    APP_INFO.info({
        "version": "2.1.0",
        "environment": os.getenv("ENVIRONMENT", "production"),
        "python_version": os.sys.version.split()[0],
    })


# ── Prometheus Metrics Middleware ──────────────────────────────────────


class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    Middleware to automatically track HTTP request metrics.

    Captures request count, latency, and in-progress gauge for every request.
    """

    async def dispatch(self, request: Request, call_next):
        method = request.method
        # Normalize the path to avoid high-cardinality explosion
        path = self._normalize_path(request.url.path)

        REQUESTS_IN_PROGRESS.labels(method=method).inc()
        start = time.perf_counter()

        try:
            response = await call_next(request)
            status = str(response.status_code)
        except Exception:
            status = "500"
            raise
        finally:
            elapsed = time.perf_counter() - start
            REQUEST_COUNT.labels(
                method=method, endpoint=path, status_code=status
            ).inc()
            REQUEST_LATENCY.labels(method=method, endpoint=path).observe(elapsed)
            REQUESTS_IN_PROGRESS.labels(method=method).dec()

        return response

    @staticmethod
    def _normalize_path(path: str) -> str:
        """
        Collapse path parameters to reduce cardinality.
        e.g., /profile/abc123 → /profile/{id}
        """
        parts = path.strip("/").split("/")
        normalized = []
        for part in parts:
            # If it looks like a UUID, hash, or long ID, replace it
            if len(part) > 8 and any(c.isdigit() for c in part):
                normalized.append("{id}")
            else:
                normalized.append(part)
        return "/" + "/".join(normalized) if normalized else "/"


# ── Metrics Endpoint App ──────────────────────────────────────────────


metrics_app = FastAPI(title="Metrics", docs_url=None, redoc_url=None)


@metrics_app.get("/")
async def prometheus_metrics():
    """Serve Prometheus metrics in the standard exposition format."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


# ── Helper Functions ──────────────────────────────────────────────────


def track_cache_hit(cache_name: str) -> None:
    """Record a cache hit."""
    CACHE_OPERATIONS.labels(cache_name=cache_name, operation="hit").inc()


def track_cache_miss(cache_name: str) -> None:
    """Record a cache miss."""
    CACHE_OPERATIONS.labels(cache_name=cache_name, operation="miss").inc()


def track_task(task_name: str, status: str = "success") -> None:
    """Record a background task completion."""
    BACKGROUND_TASKS.labels(task_name=task_name, status=status).inc()
