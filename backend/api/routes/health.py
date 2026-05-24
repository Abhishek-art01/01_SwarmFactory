"""
api/routes/health.py
--------------------
GET /health — liveness and readiness probe.

Used by:
  - Kubernetes / Docker liveness probes  → is the process alive?
  - Load balancers                        → should traffic be routed here?
  - Uptime monitors                       → is the service up?

This is intentionally the SIMPLEST route in the codebase. It:
  1. Always returns 200 OK if the process is running
  2. Optionally checks downstream dependencies (Redis) for a "deep" check
  3. Is excluded from API key auth (public endpoint)
"""

import logging
import time
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# APIRouter groups related routes. We include this in server.py via
# app.include_router(health.router) — no prefix so it lives at /health.
router = APIRouter(tags=["Health"])


# ── Response models ───────────────────────────────────────────────────────────

class DependencyStatus(BaseModel):
    """Status of a single downstream dependency."""

    name: str
    status: Literal["ok", "degraded", "down"]
    latency_ms: float


class HealthResponse(BaseModel):
    """
    Shape of the /health response body.

    Attributes:
        status:       'ok' if all deps are healthy, 'degraded' otherwise.
        version:      API version string.
        uptime_s:     Seconds since the process started.
        dependencies: Per-dependency health checks.
    """

    status: Literal["ok", "degraded"]
    version: str = "1.0.0"
    uptime_s: float
    dependencies: list[DependencyStatus]


# Process start time — used to compute uptime in the health response.
_PROCESS_START = time.monotonic()


# ── Route ─────────────────────────────────────────────────────────────────────

# HTTP GET /health — returns liveness + readiness information
@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns 200 if the API is running. Checks Redis connectivity.",
)
async def health_check(request: Request) -> HealthResponse:
    """
    Perform a health check of the API and its dependencies.

    Checks Redis by issuing a PING command and measuring latency.
    Returns HTTP 200 regardless of dependency status so that the process
    is never restarted just because Redis is temporarily unreachable
    (Kubernetes should use a separate readiness probe for that).

    Args:
        request: FastAPI Request — used to access app.state.redis.

    Returns:
        HealthResponse: Current health status with dependency details.
    """
    uptime = time.monotonic() - _PROCESS_START
    dependencies: list[DependencyStatus] = []

    # ── Check Redis ───────────────────────────────────────────────────────────
    # Why async? Because redis_client.ping() is a network call.
    # Using `await` yields control back to the event loop while we wait,
    # allowing other requests to be served concurrently.
    redis_status: Literal["ok", "degraded", "down"] = "down"
    redis_latency_ms = 0.0

    try:
        redis_client = request.app.state.redis
        t0 = time.monotonic()
        # await: we're waiting for a round-trip TCP packet to Redis
        await redis_client.ping()
        redis_latency_ms = (time.monotonic() - t0) * 1000
        redis_status = "ok"
        logger.debug("Redis health check passed", extra={"latency_ms": redis_latency_ms})
    except Exception as exc:
        logger.warning("Redis health check failed", extra={"error": str(exc)})
        redis_status = "down"

    dependencies.append(
        DependencyStatus(
            name="redis",
            status=redis_status,
            latency_ms=round(redis_latency_ms, 2),
        )
    )

    # Overall status: degraded if ANY dependency is not "ok"
    overall: Literal["ok", "degraded"] = (
        "ok" if all(d.status == "ok" for d in dependencies) else "degraded"
    )

    logger.info(
        "Health check",
        extra={"status": overall, "uptime_s": round(uptime, 1)},
    )

    return HealthResponse(
        status=overall,
        uptime_s=round(uptime, 2),
        dependencies=dependencies,
    )
