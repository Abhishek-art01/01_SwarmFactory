"""
queue/job_processor.py
-----------------------
Thin wrapper called by the Celery task.
Imports and runs the swarm pipeline, handling top-level errors.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


def process_job(job_id: str, requirement: str, options: dict) -> str:
    """
    Synchronous entry point for Celery. Runs the async swarm pipeline.

    Args:
        job_id: UUID4 job identifier.
        requirement: Plain English requirement string.
        options: Pipeline options dict.

    Returns:
        "success" on completion.
    """
    from orchestrator.swarm_controller import run_swarm
    asyncio.run(run_swarm(job_id=job_id, requirement=requirement, options=options))
    return "success"
