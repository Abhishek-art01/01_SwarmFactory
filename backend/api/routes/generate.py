"""
api/routes/generate.py
----------------------
POST /api/generate — Accept a plain-English requirement and start a swarm job.

This is the front door of Swarm Factory. A single POST kicks off an entire
7-agent pipeline that will:
  1. Validate and sanitise the incoming requirement
  2. Mint a unique job_id (UUID4)
  3. Store initial job state in Redis
  4. Dispatch the orchestration task to Celery (background, non-blocking)
  5. Return { "job_id": "..." } immediately so the client can open a WebSocket

The heavy lifting happens asynchronously in orchestrator/swarm_controller.py.
The client polls GET /api/status/:job_id or streams WS /ws/:job_id for updates.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from core.config import settings

logger = logging.getLogger(__name__)

# ── Router ────────────────────────────────────────────────────────────────────
# Included in server.py with prefix="/api", so the full path is POST /api/generate
router = APIRouter(tags=["Generate"])


# ── Redis key helpers ─────────────────────────────────────────────────────────
# Centralise key naming so there's ONE place to change if the schema evolves.

def job_key(job_id: str) -> str:
    """Return the Redis hash key for a job's metadata."""
    return f"job:{job_id}"


def job_events_key(job_id: str) -> str:
    """Return the Redis list key where agent events are appended."""
    return f"job:{job_id}:events"


# ── Request / Response models ─────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    """
    Payload for POST /api/generate.

    Attributes:
        requirement: Plain-English description of the software to build.
                     Min 20 chars to prevent trivially short prompts.
                     Max 4000 chars to keep token costs predictable.
        options:     Optional knobs to tune the generation pipeline.
    """

    requirement: str = Field(
        ...,
        min_length=20,
        max_length=4000,
        description="Plain-English description of what to build.",
        examples=["Build a REST API for a todo list app with PostgreSQL and JWT auth."],
    )
    options: "GenerateOptions | None" = Field(
        default=None,
        description="Optional pipeline configuration.",
    )

    @field_validator("requirement")
    @classmethod
    def strip_and_validate(cls, v: str) -> str:
        """Strip whitespace and reject obviously empty inputs."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("requirement must not be blank after stripping whitespace")
        return stripped


class GenerateOptions(BaseModel):
    """
    Optional tunables for a specific generate request.

    Attributes:
        language:      Target programming language (default: python).
        include_tests: Whether test_agent should run (default: True).
        include_devops: Whether devops_agent should run (default: True).
        max_files:     Cap on the number of files coder_agent may emit.
    """

    language: str = Field(default="python", description="Target language")
    include_tests: bool = Field(default=True)
    include_devops: bool = Field(default=True)
    max_files: int = Field(default=50, ge=1, le=200)


# Rebuild the forward reference in GenerateRequest now that GenerateOptions is defined
GenerateRequest.model_rebuild()


class GenerateResponse(BaseModel):
    """
    Response from POST /api/generate.

    Attributes:
        job_id:     UUID4 string — use this to poll status or open a WebSocket.
        status:     Always 'queued' on a fresh submission.
        created_at: ISO-8601 UTC timestamp.
        ws_url:     Convenience URL for the WebSocket stream.
    """

    job_id: str
    status: str = "queued"
    created_at: str
    ws_url: str


# ── Job state helpers ─────────────────────────────────────────────────────────

async def _init_job_state(redis, job_id: str, requirement: str) -> None:
    """
    Write the initial job record into Redis.

    We use a Redis Hash (HSET) because individual fields (status, progress)
    will be updated independently by the Celery worker as the job progresses.
    Using a Hash avoids serialising/deserialising the entire job object on
    every small status update.

    Args:
        redis:       Async Redis client from app.state.redis.
        job_id:      UUID4 string identifying this job.
        requirement: The user's plain-English requirement (stored for auditing).
    """
    now = datetime.now(timezone.utc).isoformat()

    # HSET writes multiple fields atomically
    # await: we're waiting for the Redis round-trip
    await redis.hset(
        job_key(job_id),
        mapping={
            "job_id": job_id,
            "status": "queued",
            "requirement": requirement,
            "created_at": now,
            "updated_at": now,
            "progress": "0",          # Percentage 0-100
            "current_agent": "",
            "error": "",
        },
    )

    # Set a TTL so stale jobs are automatically cleaned up after 24 hours.
    # await: waiting for the EXPIRE command acknowledgement
    await redis.expire(job_key(job_id), 86_400)

    logger.info(
        "Job state initialised in Redis",
        extra={"job_id": job_id},
    )


# ── Route ─────────────────────────────────────────────────────────────────────

# HTTP POST /api/generate — accepts a requirement, enqueues a swarm job, returns job_id
@router.post(
    "/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,   # 202 = accepted for processing, not yet complete
    summary="Start a new Swarm Factory job",
    description=(
        "Submit a plain-English software requirement. The API immediately returns "
        "a job_id. Connect to WS /ws/{job_id} to stream real-time agent updates."
    ),
)
async def generate(
    payload: GenerateRequest,
    request: Request,
) -> GenerateResponse:
    """
    Accept a software requirement and dispatch it to the 7-agent swarm.

    Flow:
        1. Mint a job_id (UUID4)
        2. Write initial state to Redis
        3. Enqueue the Celery task (non-blocking — returns immediately)
        4. Return { job_id } to the client

    The Celery worker picks up the task and calls
    orchestrator.swarm_controller.run_swarm(job_id, requirement).

    Args:
        payload: Validated GenerateRequest body.
        request: FastAPI Request — provides access to app.state.redis.

    Returns:
        GenerateResponse: Contains the job_id and convenience WebSocket URL.

    Raises:
        HTTPException 429: If the job queue is at capacity.
        HTTPException 500: If Redis is unavailable or Celery enqueue fails.
    """
    # ── 1. Mint a unique job ID ───────────────────────────────────────────────
    job_id = str(uuid.uuid4())
    logger.info(
        "New generate request received",
        extra={"job_id": job_id, "requirement_length": len(payload.requirement)},
    )

    redis = request.app.state.redis

    # ── 2. Check capacity ─────────────────────────────────────────────────────
    # Count jobs currently in 'running' state to enforce MAX_CONCURRENT_JOBS.
    # In a real system you'd use a Redis counter; this is a simple approximation.
    try:
        # await: waiting for Redis KEYS scan (use SCAN in production for large datasets)
        running_keys = await redis.keys("job:*")
        # Filter to only running jobs by checking their status field
        running_count = 0
        for key in running_keys:
            if "events" in key:
                continue
            # await: individual HGET per job key
            job_status = await redis.hget(key, "status")
            if job_status == "running":
                running_count += 1

        if running_count >= settings.MAX_CONCURRENT_JOBS:
            logger.warning(
                "Job queue at capacity, rejecting request",
                extra={"job_id": job_id, "running_count": running_count},
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "queue_full",
                    "message": (
                        f"Maximum concurrent jobs ({settings.MAX_CONCURRENT_JOBS}) reached. "
                        "Please retry in a few minutes."
                    ),
                },
            )
    except HTTPException:
        raise  # Re-raise intentional 429s
    except Exception as exc:
        logger.error(
            "Redis capacity check failed",
            extra={"job_id": job_id, "error": str(exc)},
        )
        # Non-fatal: proceed even if we can't check capacity
        pass

    # ── 3. Initialise job state in Redis ──────────────────────────────────────
    try:
        # await: writing job metadata to Redis before we enqueue the task,
        # so that the client can call GET /api/status immediately after this response.
        await _init_job_state(redis, job_id, payload.requirement)
    except Exception as exc:
        logger.error(
            "Failed to initialise job state in Redis",
            extra={"job_id": job_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "state_store_unavailable",
                "message": "Could not initialise job state. Please retry.",
            },
        )

    # ── 4. Enqueue Celery task ────────────────────────────────────────────────
    # We import here (not at module top) to avoid a circular import between
    # server.py → celery_app → config → server.py.
    # The Celery task is fire-and-forget from the API's perspective.
    try:
        from celery_app import run_swarm_task

        # .delay() is Celery's shorthand for .apply_async() with default options.
        # It is NOT an awaitable — Celery's broker communication is sync here.
        # The task runs in a separate worker process, not in this event loop.
        run_swarm_task.delay(
            job_id=job_id,
            requirement=payload.requirement,
            options=payload.options.model_dump() if payload.options else {},
        )
        logger.info(
            "Celery task enqueued",
            extra={"job_id": job_id},
        )
    except Exception as exc:
        # If Celery is down, mark the job as failed and inform the client.
        logger.error(
            "Failed to enqueue Celery task",
            extra={"job_id": job_id, "error": str(exc)},
        )
        # Update Redis so status endpoint shows failure
        try:
            await redis.hset(job_key(job_id), mapping={"status": "failed", "error": str(exc)})
        except Exception:
            pass  # Best-effort — don't mask the original error

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "task_queue_unavailable",
                "message": "Could not enqueue job. The task queue may be down.",
            },
        )

    # ── 5. Return job_id to client ────────────────────────────────────────────
    created_at = datetime.now(timezone.utc).isoformat()
    ws_url = f"/ws/{job_id}"

    logger.info(
        "Generate request accepted",
        extra={"job_id": job_id, "ws_url": ws_url},
    )

    return GenerateResponse(
        job_id=job_id,
        status="queued",
        created_at=created_at,
        ws_url=ws_url,
    )
