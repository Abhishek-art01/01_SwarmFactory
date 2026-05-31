"""
api/routes/output.py
--------------------
GET /api/output/:job_id — Retrieve the final generated codebase for a complete job.

Only available when the job's status is 'complete'. Returns the merged codebase
produced by mediator_agent and the deployment URLs from devops_agent.
"""

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Output"])


class GeneratedFile(BaseModel):
    """A single file in the generated codebase."""

    filename: str
    content: str
    language: str = "plaintext"


class OutputResponse(BaseModel):
    """
    Shape of the GET /api/output/:job_id response.

    Attributes:
        job_id:     The job identifier.
        files:      Dict mapping filename → file content.
        github_url: GitHub repo URL created by devops_agent.
        azure_url:  Azure deployment URL created by devops_agent.
        coverage:   Test coverage percentage reported by test_agent.
        file_count: Number of generated files.
    """

    job_id: str
    files: dict[str, str]
    github_url: Optional[str] = None
    azure_url: Optional[str] = None
    coverage: Optional[int] = None
    file_count: int


def _extract_files(raw: Any) -> dict[str, str]:
    """
    Normalize stored job output to the API's file map contract.

    Older/generated outputs may be either:
      - {"path.py": "content"}
      - {"files": {"path.py": "content"}, "dependencies": [...], ...}
    """

    if not isinstance(raw, dict):
        return {}

    candidate = raw.get("files") if isinstance(raw.get("files"), dict) else raw
    files: dict[str, str] = {}
    for path, content in candidate.items():
        if not isinstance(path, str):
            continue
        if isinstance(content, str):
            files[path] = content
        else:
            files[path] = json.dumps(content, default=str, indent=2)
    return files


# HTTP GET /api/output/:job_id — returns the generated codebase for a completed job
@router.get(
    "/output/{job_id}",
    response_model=OutputResponse,
    summary="Get job output",
    description="Fetch the final generated codebase. Only available when status == 'complete'.",
)
async def get_output(job_id: str, request: Request) -> OutputResponse:
    """
    Return the generated files and deployment URLs for a completed job.

    Args:
        job_id:  UUID4 job identifier.
        request: FastAPI Request — provides app.state.redis.

    Returns:
        OutputResponse: Generated codebase and deployment metadata.

    Raises:
        HTTPException 404: If job_id is unknown.
        HTTPException 409: If the job is not yet complete.
        HTTPException 503: If Redis is unreachable.
    """
    redis = request.app.state.redis

    try:
        # await: fetching the job metadata hash from Redis
        job_data: dict = await redis.hgetall(f"job:{job_id}")
    except Exception as exc:
        logger.error("Redis read failed", extra={"job_id": job_id, "error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "state_store_unavailable"},
        )

    if not job_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "job_not_found", "message": f"No job with id '{job_id}'"},
        )

    if job_data.get("status") != "complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "job_not_complete",
                "message": f"Job is '{job_data.get('status')}', not 'complete'.",
                "current_status": job_data.get("status"),
            },
        )

    # The codebase is stored as a JSON-encoded dict { filename: content }
    # in Redis under the key job:{job_id}:output
    try:
        # await: fetching the (potentially large) output blob from Redis
        raw_output: Optional[str] = await redis.get(f"job:{job_id}:output")
    except Exception as exc:
        logger.error("Failed to read output", extra={"job_id": job_id, "error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "output_unavailable"},
        )

    files: dict[str, str] = {}
    if raw_output:
        try:
            files = _extract_files(json.loads(raw_output))
        except json.JSONDecodeError as exc:
            logger.error("Output JSON corrupt", extra={"job_id": job_id, "error": str(exc)})
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "output_corrupt"},
            )

    coverage_str = job_data.get("coverage", "")
    coverage = int(coverage_str) if coverage_str.isdigit() else None

    logger.info(
        "Output retrieved",
        extra={"job_id": job_id, "file_count": len(files)},
    )

    return OutputResponse(
        job_id=job_id,
        files=files,
        github_url=job_data.get("github_url") or None,
        azure_url=job_data.get("azure_url") or None,
        coverage=coverage,
        file_count=len(files),
    )
