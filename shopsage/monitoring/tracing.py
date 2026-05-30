"""
OpenTelemetry Tracing — Distributed tracing for ShopSage AI.

Configures the OpenTelemetry SDK to:
- Instrument FastAPI with automatic span creation per request
- Export traces to an OTLP-compatible backend (Jaeger, Grafana Tempo, etc.)
- Fall back to a no-op exporter when no collector is configured

Environment Variables:
    OTEL_EXPORTER_OTLP_ENDPOINT: The OTLP collector endpoint
        (e.g., http://localhost:4318). If not set, tracing is disabled.
    OTEL_SERVICE_NAME: Override the service name (default: "shopsage-api").
    ENVIRONMENT: Sets the deployment.environment resource attribute.
"""

import os
import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes

logger = logging.getLogger("shopsage.monitoring.tracing")


def configure_tracing(app=None) -> trace.Tracer:
    """
    Configure OpenTelemetry distributed tracing.

    Args:
        app: Optional FastAPI application to instrument.

    Returns:
        An OpenTelemetry Tracer instance.
    """
    service_name = os.getenv("OTEL_SERVICE_NAME", "shopsage-api")
    environment = os.getenv("ENVIRONMENT", "production")
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: service_name,
        ResourceAttributes.SERVICE_VERSION: "2.1.0",
        ResourceAttributes.DEPLOYMENT_ENVIRONMENT: environment,
    })

    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        # Export to a real OTLP collector (Jaeger, Tempo, etc.)
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(
                f"[Tracing] OTLP exporter configured → {otlp_endpoint}"
            )
        except Exception as e:
            logger.warning(f"[Tracing] Failed to configure OTLP exporter: {e}")
    else:
        logger.info("[Tracing] No OTEL_EXPORTER_OTLP_ENDPOINT set; tracing is no-op.")

    trace.set_tracer_provider(provider)

    # Instrument FastAPI if the app is provided
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(
                app,
                excluded_urls="health,metrics,favicon.ico",
            )
            logger.info("[Tracing] FastAPI auto-instrumented")
        except Exception as e:
            logger.warning(f"[Tracing] Could not instrument FastAPI: {e}")

    return trace.get_tracer(service_name)


def get_tracer(name: str = "shopsage") -> trace.Tracer:
    """Get a tracer instance for manual span creation."""
    return trace.get_tracer(name)
