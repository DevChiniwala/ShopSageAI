"""
Abusive IP Blocker — Security middleware for ShopSage AI.

Tracks excessive HTTP 401/403 errors and rate-limiting (429) hits
from specific IP addresses. If an IP exceeds the penalty threshold
within the window, it is blocked at the routing layer entirely.

Backed by Redis.
"""

import time
import logging
from typing import Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("shopsage.security.abusive_ip_blocker")


class AbusiveIPBlockerMiddleware(BaseHTTPMiddleware):
    """
    Middleware that blocks IPs that frequently generate 4xx errors
    indicating abusive behavior (e.g. brute force, scraping, scanning).
    """

    def __init__(
        self,
        app,
        redis_client=None,
        threshold: int = 50,
        window_seconds: int = 3600,
        block_duration_seconds: int = 86400,
    ):
        super().__init__(app)
        self.redis = redis_client
        self.threshold = threshold
        self.window = window_seconds
        self.block_duration = block_duration_seconds

    async def dispatch(self, request: Request, call_next):
        # Determine client IP
        client_ip = self._get_client_ip(request)
        if not client_ip:
            return await call_next(request)

        # 1. Check if IP is currently blocked
        if self.redis:
            try:
                is_blocked = self.redis.get(f"block_ip:{client_ip}")
                if is_blocked:
                    logger.warning(f"[Security] Rejected request from blocked IP: {client_ip}")
                    return JSONResponse(
                        {"detail": "Access denied due to abusive behavior."},
                        status_code=403,
                    )
            except Exception as e:
                logger.error(f"[Security] Redis check failed: {e}")

        # 2. Process request
        response = await call_next(request)

        # 3. Track abusive responses (401 Unauthorized, 403 Forbidden, 429 Too Many Requests)
        if response.status_code in (401, 403, 429) and self.redis:
            self._record_strike(client_ip)

        return response

    def _get_client_ip(self, request: Request) -> str:
        """Extract the real client IP, considering trusted proxies."""
        # Note: If running behind a proxy, `ForwardedAllowIPS` in uvicorn should be set,
        # which populates request.client.host correctly. Otherwise, check headers.
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        return request.client.host if request.client else ""

    def _record_strike(self, client_ip: str) -> None:
        """Record a strike against the IP in Redis."""
        try:
            key = f"strikes_ip:{client_ip}"
            
            # Increment strike count
            current = self.redis.incr(key)
            
            # If it's the first strike, set expiry for the window
            if current == 1:
                self.redis.expire(key, self.window)
                
            # If threshold exceeded, apply block
            if current >= self.threshold:
                logger.critical(f"[Security] IP {client_ip} exceeded threshold ({self.threshold} strikes). Blocking for {self.block_duration}s.")
                self.redis.setex(f"block_ip:{client_ip}", self.block_duration, "1")
                # We can optionally clear the strikes here, but letting them expire naturally is fine
        except Exception as e:
            logger.error(f"[Security] Failed to record strike for {client_ip}: {e}")
