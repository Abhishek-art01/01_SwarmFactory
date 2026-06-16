"""
api/middleware/auth.py
-----------------------
Starlette middleware that validates the X-API-Key header on protected API requests.

Excluded paths (no key required):
  - GET /health        (public liveness probe)
  - WS  /ws/*          (WebSocket auth handled separately via query param)
  - GET /docs          (Swagger UI, dev only)
  - GET /openapi.json  (OpenAPI spec, dev only)
"""

import logging
from typing import Sequence

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from core.config import settings

logger = logging.getLogger(__name__)

# Paths that bypass API key validation
AUTH_EXCLUDED_PREFIXES: Sequence[str] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/ws/",   # WebSocket connections
)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Validates the X-API-Key header against the configured API_KEY.

    Returns HTTP 401 if the header is missing.
    Returns HTTP 403 if the header is present but incorrect.

    Args:
        app: The next ASGI application in the middleware stack.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Intercept every request and validate the API key before passing it on.

        Args:
            request:   Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            Response: Either an error response or the downstream response.
        """
        path = request.url.path

        # Skip auth for CORS preflight (OPTIONS) requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip auth for excluded paths
        for excluded in AUTH_EXCLUDED_PREFIXES:
            if path.startswith(excluded):
                # await: forwarding to the next handler in the middleware chain
                return await call_next(request)

        # The bundled frontend is public. API routes remain protected.
        if not path.startswith("/api/"):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")

        if not api_key:
            logger.warning(
                "Missing API key",
                extra={"path": path, "ip": request.client.host if request.client else "unknown"},
            )
            return JSONResponse(
                status_code=401,
                content={"error": "missing_api_key", "message": "X-API-Key header is required"},
            )

        if api_key != settings.API_KEY:
            logger.warning(
                "Invalid API key",
                extra={"path": path, "ip": request.client.host if request.client else "unknown"},
            )
            return JSONResponse(
                status_code=403,
                content={"error": "invalid_api_key", "message": "The provided API key is invalid"},
            )

        # await: key is valid — pass to next middleware/route
        return await call_next(request)
