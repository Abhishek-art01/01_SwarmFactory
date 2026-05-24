"""
celery_app.py
--------------
Celery application definition and the run_swarm_task task.

Celery is used here as a process-isolated job queue. When the FastAPI route
calls run_swarm_task.delay(...), Celery:
  1. Serialises the arguments to JSON
  2. Pushes them to the Redis broker
  3. A Celery worker process (separate from the FastAPI process) picks them up
  4. Calls run_swarm_task in the worker process
  5. run_swarm_task runs the asyncio swarm pipeline via asyncio.run()

WHY CELERY INSTEAD OF BACKGROUND TASKS?
  - FastAPI BackgroundTasks run in the same process as the API server.
    If the API server restarts, in-flight jobs are lost.
  - Celery workers are separate processes / pods that survive API restarts.
  - Celery gives us retries, time limits, and result persistence for free.

STARTING THE WORKER:
    celery -A celery_app worker --loglevel=info --concurrency=4
"""

import asyncio
import logging

from celery import Celery

from core.config import settings

logger = logging.getLogger(__name__)

# ── Celery app ────────────────────────────────────────────────────────────────
celery_app = Celery(
    "swarm_factory",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    # Serialise tasks as JSON (not pickle — safer for cross-service communication)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Hard time limit: kill the task if it runs longer than JOB_TIMEOUT_SECONDS
    task_time_limit=settings.JOB_TIMEOUT_SECONDS,

    # Soft limit: raise SoftTimeLimitExceeded 30s before the hard limit
    # so the task can clean up gracefully
    task_soft_time_limit=settings.JOB_TIMEOUT_SECONDS - 30,

    # Route all tasks to the default queue
    task_default_queue="swarm",

    # Retry failed tasks up to 2 times with exponential backoff
    task_max_retries=2,
    task_default_retry_delay=10,  # seconds

    # Store task results for 1 hour
    result_expires=3600,

    # Timezone
    timezone="UTC",
    enable_utc=True,
)


# ── Task definition ───────────────────────────────────────────────────────────

@celery_app.task(
    name="swarm_factory.run_swarm",
    bind=True,           # `self` is the task instance (gives access to self.retry)
    max_retries=2,
    default_retry_delay=10,
)
def run_swarm_task(self, job_id: str, requirement: str, options: dict | None = None) -> str:
    """
    Celery task that runs the full 7-agent swarm pipeline.

    This is a synchronous Celery task that bridges into async code by calling
    asyncio.run(). Each task invocation gets its own event loop because
    asyncio.run() creates a new loop, runs until completion, and closes it.

    Args:
        self:        Celery task instance (bound task — used for self.retry).
        job_id:      UUID4 identifying the job in Redis.
        requirement: Plain-English requirement string.
        options:     Optional pipeline config dict.

    Returns:
        str: "success" on completion (stored in Celery result backend).

    Raises:
        Retries the task on exception, up to max_retries times.
    """
    logger.info("Celery task started", extra={"job_id": job_id})

    try:
        # Import here to avoid circular imports at module level
        from orchestrator.swarm_controller import run_swarm

        # asyncio.run() creates a new event loop, runs the coroutine to completion,
        # and closes the loop. This is the standard pattern for calling async code
        # from a synchronous Celery task.
        asyncio.run(
            run_swarm(
                job_id=job_id,
                requirement=requirement,
                options=options or {},
            )
        )

        logger.info("Celery task completed successfully", extra={"job_id": job_id})
        return "success"

    except Exception as exc:
        logger.error(
            "Celery task failed",
            extra={"job_id": job_id, "error": str(exc), "retries": self.request.retries},
        )

        # Retry up to max_retries times; after that, Celery marks the task as FAILED
        try:
            raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1))
        except self.MaxRetriesExceededError:
            logger.error(
                "Max retries exceeded for job",
                extra={"job_id": job_id},
            )
            # Update Redis job status to failed
            try:
                import redis as sync_redis
                r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
                r.hset(f"job:{job_id}", mapping={"status": "failed", "error": str(exc)})
                r.close()
            except Exception:
                pass
            raise
