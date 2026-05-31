"""
queue/job_store.py
------------------
Redis-backed job state storage.
All job state reads/writes go through here — single place to change the schema.
"""
import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

JOB_TTL = 86_400  # 24 hours


def job_key(job_id: str) -> str:
    return f"job:{job_id}"


def output_key(job_id: str) -> str:
    return f"job:{job_id}:output"


async def get_job_status(redis: aioredis.Redis, job_id: str) -> dict | None:
    """Return job hash as dict, or None if not found."""
    try:
        data = await redis.hgetall(job_key(job_id))
        return dict(data) if data else None
    except Exception as exc:
        logger.error("Failed to get job status", extra={"job_id": job_id, "error": str(exc)})
        return None


async def get_job_output(redis: aioredis.Redis, job_id: str) -> dict | None:
    """Return final job output JSON, or None if not ready."""
    try:
        raw = await redis.get(output_key(job_id))
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.error("Failed to get job output", extra={"job_id": job_id, "error": str(exc)})
        return None


async def set_job_output(redis: aioredis.Redis, job_id: str, output: dict) -> bool:
    """Persist final output to Redis with 24h TTL."""
    try:
        await redis.set(output_key(job_id), json.dumps(output), ex=JOB_TTL)
        return True
    except Exception as exc:
        logger.error("Failed to set job output", extra={"job_id": job_id, "error": str(exc)})
        return False
