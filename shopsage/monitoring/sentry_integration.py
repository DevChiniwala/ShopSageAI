"""
Sentry Integration — Real-time error tracking for ShopSage AI.

Initializes the Sentry SDK to capture:
- Unhandled exceptions
- Performance transactions (via traces_sample_rate)
- FastAPI request context (user, tags, breadcrumbs)

Environment Variables:
    SENTRY_DSN: The Sentry project DSN. If not set, Sentry is disabled.
    ENVIRONMENT: Deployment environment tag (default: "production").
    SENTRY_TRACES_SAMPLE_RATE: Float 0.0–1.0 (default: 0.2).
"""

import os
import logging

logger = logging.getLogger("shopsage.monitoring.sentry_integration")


def configure_sentry() -> bool:
    """
    Initialize Sentry error tracking.

    Returns:
        True if Sentry was successfully initialized, False otherwise.
    """
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        logger.info("[Sentry] No SENTRY_DSN set; error tracking is disabled.")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        environment = os.getenv("ENVIRONMENT", "production")
        traces_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.2"))

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=traces_rate,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                LoggingIntegration(
                    level=logging.INFO,
                    event_level=logging.ERROR,
                ),
            ],
            send_default_pii=False,
            release=f"shopsage@2.1.0",
            _experiments={
                "profiles_sample_rate": 0.1,
            },
        )

        logger.info(
            f"[Sentry] Initialized (env={environment}, "
            f"traces_rate={traces_rate})"
        )
        return True

    except ImportError:
        logger.warning("[Sentry] sentry-sdk not installed; skipping.")
        return False
    except Exception as e:
        logger.error(f"[Sentry] Initialization failed: {e}")
        return False
