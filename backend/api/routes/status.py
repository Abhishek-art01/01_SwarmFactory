"""
api/routes/status.py
--------------------
GET /api/status/:job_id — Poll the current state of a swarm job.

Clients that cannot maintain a WebSocket connection (e.g. serverless functions,
CLI tools) can use this endpoint to poll job progress. The WebSocket endpoint
is preferred for browser clients because it gives real-time push updates.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Status"])

JobStatus = Literal["queued", "running", "complete", "failed"]


class AgentProgress(BaseModel):
    """Current agent activity snapshot."""

    current_agent: str
    progress_pct: int  # 0-100


class JobStatusResponse(BaseModel):
    """
    Shape of the GET /api/status/:job_id response.

    Attributes:
        job_id:        The job identifier.
        status:        One of: queued | running | complete | failed.
        progress:      Agent progress snapshot (present while running).
        created_at:    ISO-8601 UTC timestamp of job creation.
        updated_at:    ISO-8601 UTC timestamp of last status change.
        error:         Error message if status == 'failed'.
        github_url:    Set when status == 'complete'.
        azure_url:     Set when status == 'complete'.
        coverage:      Test coverage percentage when status == 'complete'.
    """

    job_id: str
    status: JobStatus
    progress: Optional[AgentProgress] = None
    created_at: str
    updated_at: str
    error: Optional[str] = None
    github_url: Optional[str] = None
    azure_url: Optional[str] = None
    coverage: Optional[int] = None


# HTTP GET /api/status/:job_id — returns current job state from Redis
@router.get(
    "/status/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    description="Poll the current state of a swarm job by its job_id.",
)
async def get_status(job_id: str, request: Request) -> JobStatusResponse:
    """
    Fetch the current status of a job from Redis.

    Args:
        job_id:  UUID4 job identifier from the /api/generate response.
        request: FastAPI Request — provides app.state.redis.

    Returns:
        JobStatusResponse: Current job metadata and progress.

    Raises:
        HTTPException 404: If job_id is unknown.
        HTTPException 503: If Redis is unreachable.
    """
    redis = request.app.state.redis

    try:
        # await: network call to Redis to fetch the job hash
        job_data: dict = await redis.hgetall(f"job:{job_id}")
    except Exception as exc:
        logger.error("Redis read failed", extra={"job_id": job_id, "error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "state_store_unavailable", "message": "Cannot read job state."},
        )

    if not job_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "job_not_found", "message": f"No job found with id '{job_id}'"},
        )

    current_agent = job_data.get("current_agent", "")
    progress_pct_str = job_data.get("progress", "0")
    try:
        progress_pct = int(progress_pct_str)
    except ValueError:
        progress_pct = 0

    progress = (
        AgentProgress(current_agent=current_agent, progress_pct=progress_pct)
        if job_data.get("status") == "running"
        else None
    )

    coverage_str = job_data.get("coverage", "")
    coverage = int(coverage_str) if coverage_str.isdigit() else None

    logger.info("Status polled", extra={"job_id": job_id, "status": job_data.get("status")})

    return JobStatusResponse(
        job_id=job_id,
        status=job_data.get("status", "queued"),  # type: ignore[arg-type]
        progress=progress,
        created_at=job_data.get("created_at", ""),
        updated_at=job_data.get("updated_at", ""),
        error=job_data.get("error") or None,
        github_url=job_data.get("github_url") or None,
        azure_url=job_data.get("azure_url") or None,
        coverage=coverage,
    )
