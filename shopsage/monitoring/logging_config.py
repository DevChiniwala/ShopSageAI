"""
Structured Logging — Production-grade JSON logging for ShopSage AI.

Uses `structlog` to produce machine-parseable JSON logs with:
- Correlation IDs (request_id, tenant_id)
- Timestamps in ISO 8601 UTC
- Log level, logger name, module/function/line info
- Exception tracebacks embedded in JSON

Usage:
    from shopsage.monitoring.logging_config import get_logger, configure_logging
    configure_logging()  # call once at startup
    logger = get_logger("shopsage.mymodule")
    logger.info("event_happened", user_id="abc", latency_ms=42.5)
"""

import os
import sys
import logging
import structlog
from typing import Optional


def configure_logging(
    log_level: str = "INFO",
    json_output: bool = True,
    development: bool = False,
) -> None:
    """
    Configure structured logging for the entire application.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, output JSON. If False, output colored console logs.
        development: If True, use pretty console output regardless of json_output.
    """
    log_level = os.getenv("LOG_LEVEL", log_level).upper()
    is_dev = os.getenv("ENVIRONMENT", "production").lower() == "development" or development

    # Shared processors for both structlog and stdlib
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if is_dev:
        # Pretty console output for development
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    elif json_output:
        # Machine-readable JSON for production
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging to use structlog's formatter
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Quiet down noisy third-party loggers
    for noisy in ["uvicorn.access", "httpx", "httpcore", "urllib3", "asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name, typically the module path.

    Returns:
        A bound structlog logger with JSON output capabilities.
    """
    return structlog.get_logger(name)


def bind_request_context(
    request_id: str,
    tenant_id: Optional[str] = None,
    path: Optional[str] = None,
    method: Optional[str] = None,
) -> None:
    """
    Bind request-level context variables that will be included
    in all subsequent log entries within this async context.

    Call this in middleware at the start of each request.
    """
    structlog.contextvars.clear_contextvars()
    ctx = {"request_id": request_id}
    if tenant_id:
        ctx["tenant_id"] = tenant_id
    if path:
        ctx["http_path"] = path
    if method:
        ctx["http_method"] = method
    structlog.contextvars.bind_contextvars(**ctx)
