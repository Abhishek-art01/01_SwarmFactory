"""
api/server.py
-------------
FastAPI application factory for Swarm Factory.

Responsibilities:
  - Create and configure the FastAPI app instance
  - Register CORS middleware (so the browser-based frontend can call us)
  - Wire in auth, rate-limiting, and error-handling middleware
  - Mount all HTTP routers and the WebSocket endpoint
  - Define the lifespan context manager (startup / shutdown hooks)

Import this module's `app` object in your ASGI server command:
    uvicorn backend.api.server:app --reload
"""

import logging
import logging.config
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import settings
from api.middleware.auth import AuthMiddleware
from api.middleware.rate_limit import RateLimitMiddleware
from api.middleware.error_handler import register_exception_handlers
from api.routes import health, generate, status, output, projects
from api.websocket import router as ws_router

# ── Logging setup ─────────────────────────────────────────────────────────────
# Configure structured logging once, at import time, so every module that does
# `logger = logging.getLogger(__name__)` inherits this configuration.
LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            # In production you'd swap this for python-json-logger for true JSON
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        }
    },
    "root": {
        "level": settings.LOG_LEVEL,
        "handlers": ["console"],
    },
}
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────
# FastAPI's lifespan replaces the old @app.on_event("startup") pattern.
# Code before `yield` runs on startup; code after runs on shutdown.
# We use it to open/close the Redis connection pool used by the rate limiter
# and WebSocket state tracker.
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Startup:
        - Connects to Redis and stores the client on app.state so
          middleware and route handlers can access it without creating
          new connections on every request.

    Shutdown:
        - Gracefully closes the Redis connection pool.

    Args:
        app: The FastAPI application instance (injected by FastAPI).

    Yields:
        None — control returns to FastAPI while the app is running.
    """
    # ── STARTUP ───────────────────────────────────────────────────────────────
    logger.info("Swarm Factory API starting up", extra={"env": settings.APP_ENV})

    # Why async Redis? Because our routes are async. Using a blocking client
    # here would stall the entire event loop on every cache/pub-sub call.
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
        **settings.redis_connection_kwargs,
    )

    # Ping to verify connectivity before we accept any traffic
    try:
        await redis_client.ping()
        logger.info("Redis connection established", extra={"url": settings.safe_redis_url})
    except Exception as exc:
        # Log and re-raise — we don't want to start accepting traffic
        # if our state store is unavailable.
        logger.error("Failed to connect to Redis", extra={"error": str(exc)})
        raise

    # Attach to app.state so middleware / routes can do:
    #   request.app.state.redis
    app.state.redis = redis_client

    # ── Hand control to FastAPI ───────────────────────────────────────────────
    yield

    # ── SHUTDOWN ──────────────────────────────────────────────────────────────
    logger.info("Swarm Factory API shutting down")
    await redis_client.aclose()
    logger.info("Redis connection closed")


# ── App factory ───────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    """
    Construct and configure the FastAPI application.

    Separating construction into a factory function makes it easy to create
    fresh instances in tests without importing a module-level global.

    Returns:
        FastAPI: Fully configured application instance.
    """
    app = FastAPI(
        title="Swarm Factory API",
        description=(
            "Orchestration layer for a 7-agent AI swarm that generates "
            "complete software projects from plain English requirements."
        ),
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Allows the React / Next.js frontend (different origin) to call our API.
    # In production, replace "*" with the exact frontend domain to prevent
    # other sites from making credentialed requests on your users' behalf.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else ["https://your-frontend.com"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    # Must be added BEFORE AuthMiddleware so that even unauthenticated floods
    # are throttled. Middleware executes in LIFO order in Starlette.
    app.add_middleware(RateLimitMiddleware)

    # ── API key authentication ────────────────────────────────────────────────
    # Validates the X-API-Key header on every non-health request.
    app.add_middleware(AuthMiddleware)

    # ── Global exception handlers ─────────────────────────────────────────────
    # Converts unhandled exceptions into structured JSON error responses
    # instead of leaking stack traces to the client.
    register_exception_handlers(app)

    # ── HTTP routers ──────────────────────────────────────────────────────────
    app.include_router(health.router)                          # GET /health
    app.include_router(generate.router, prefix="/api")         # POST /api/generate
    app.include_router(status.router, prefix="/api")           # GET  /api/status/{job_id}
    app.include_router(output.router, prefix="/api")           # GET  /api/output/{job_id}
    app.include_router(projects.router, prefix="/api")         # Project chat history

    # ── WebSocket router ──────────────────────────────────────────────────────
    app.include_router(ws_router)                              # WS /ws/{job_id}

    # ── Frontend SPA ──────────────────────────────────────────────────────────
    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    logger.info("FastAPI app created", extra={"routes": len(app.routes)})
    return app


# ── Module-level app instance ─────────────────────────────────────────────────
# Uvicorn / Gunicorn target: `uvicorn backend.api.server:app`
app: FastAPI = create_app()
