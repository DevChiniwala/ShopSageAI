"""
Security Middleware — FastAPI middleware for request logging and security headers.

Adds:
- Request/response timing
- Security headers (CSP, HSTS, X-Frame-Options, etc.)
- Request ID tracing
- Client IP extraction
"""

import time
import uuid
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("shopsage.security.middleware")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds security headers to every response and logs request timing.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate request ID for tracing
        request_id = str(uuid.uuid4())[:8]
        start = time.monotonic()

        # Extract client IP
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path

        logger.info(f"[{request_id}] {method} {path} from {client_ip}")

        try:
            response = await call_next(request)
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            logger.error(f"[{request_id}] {method} {path} FAILED ({elapsed:.0f}ms): {e}")
            raise

        elapsed = (time.monotonic() - start) * 1000

        # Add security headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Response-Time"] = f"{elapsed:.0f}ms"

        # HSTS for production (only over HTTPS)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'"
        )

        log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            log_level,
            f"[{request_id}] {method} {path} → {response.status_code} ({elapsed:.0f}ms)",
        )

        return response


class RateLimitHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds standard rate limit headers to API responses.

    This is a lightweight pass-through that sets headers based on
    response metadata. The actual enforcement is done by the
    rate_limiter module.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Only add rate limit headers for API routes
        if request.url.path.startswith("/api/"):
            response.headers["X-RateLimit-Policy"] = "sliding-window"
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"

        return response
