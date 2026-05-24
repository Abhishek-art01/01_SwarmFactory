"""
api/middleware/rate_limit.py
-----------------------------
Per-IP sliding-window rate limiter backed by Redis.

Algorithm: For each incoming request, we:
  1. Build a key: "rate_limit:{ip}:{current_window}"
     where current_window = floor(unix_timestamp / window_size)
  2. INCR the counter for that key
  3. Set a TTL on the key equal to 2x the window (ensures cleanup)
  4. If the counter exceeds the limit, return HTTP 429

This is a "fixed window" approximation of a sliding window.
For production, consider the more accurate sliding window log approach
using Redis ZADD/ZRANGEBYSCORE.
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from core.config import settings

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Limits requests per IP to RATE_LIMIT_REQUESTS per RATE_LIMIT_WINDOW_SECONDS.

    Reads config from settings. Uses app.state.redis so it shares the
    connection pool opened at startup rather than creating new connections.

    Args:
        app: The next ASGI application in the middleware stack.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.limit = settings.RATE_LIMIT_REQUESTS
        self.window = settings.RATE_LIMIT_WINDOW_SECONDS

    def _get_client_ip(self, request: Request) -> str:
        """
        Extract the real client IP, respecting X-Forwarded-For if behind a proxy.

        Args:
            request: Incoming HTTP request.

        Returns:
            str: Client IP address string.
        """
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Check and increment the rate-limit counter before passing the request on.

        Args:
            request:   Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            Response: HTTP 429 if limit exceeded, otherwise the downstream response.
        """
        # Skip rate limiting for health checks
        if request.url.path == "/health":
            # await: forwarding the health request without any rate limit check
            return await call_next(request)

        ip = self._get_client_ip(request)

        # Window slot: changes every `self.window` seconds
        window_slot = int(time.time() // self.window)
        redis_key = f"rate_limit:{ip}:{window_slot}"

        try:
            redis = request.app.state.redis

            # await: atomic INCR on the rate limit counter in Redis
            count: int = await redis.incr(redis_key)

            # Set TTL on first access to ensure key expires after 2 windows
            if count == 1:
                # await: setting the key expiry
                await redis.expire(redis_key, self.window * 2)

            if count > self.limit:
                retry_after = self.window - (int(time.time()) % self.window)
                logger.warning(
                    "Rate limit exceeded",
                    extra={"ip": ip, "count": count, "limit": self.limit},
                )
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    content={
                        "error": "rate_limit_exceeded",
                        "message": (
                            f"Too many requests. Limit: {self.limit} per {self.window}s. "
                            f"Retry after {retry_after}s."
                        ),
                        "retry_after_seconds": retry_after,
                    },
                )

        except Exception as exc:
            # If Redis is down, fail OPEN (allow the request) rather than
            # blocking all traffic. Log for alerting.
            logger.error(
                "Rate limit Redis check failed — failing open",
                extra={"ip": ip, "error": str(exc)},
            )

        # await: forwarding the request to the next handler
        return await call_next(request)
