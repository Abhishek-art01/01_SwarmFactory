"""
orchestrator/swarm_controller.py
---------------------------------
AutoGen GroupChat orchestration layer for the 7-agent swarm.

This module is the central nervous system of the generation pipeline. It:
  1. Receives a job_id + requirement from the Celery task
  2. Calls each agent in the correct order (with parallelism where safe)
  3. Publishes progress events to Redis Pub/Sub after each stage
  4. Writes the final merged codebase to Redis
  5. Updates the job's status hash at every state transition

AGENT EXECUTION ORDER:
  ┌─────────────────────────────────────────────────────────────┐
  │  1. planner_agent     → task graph (DAG)                    │
  │  2. architect_agent   → folder structure + schema           │
  │  3. coder_agent   ┐                                         │
  │     test_agent    ├── parallel (asyncio.gather)             │
  │     reviewer_agent┘                                         │
  │  4. mediator_agent    → final merged codebase               │
  │  5. devops_agent      → github_url + azure_url              │
  └─────────────────────────────────────────────────────────────┘

The quality gate (quality_gate.py) runs between steps 3 and 4.
The fallback chain (fallback_chain.py) wraps every agent call.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from core.config import settings
from orchestrator.parallel_runner import run_parallel_agents
from orchestrator.quality_gate import check_quality
from orchestrator.fallback_chain import with_fallback
from orchestrator.merger import merge_outputs

# We call these agents — we do NOT implement them (backend/agents/ is off-limits)
from agents.agent_instances import planner_agent      # type: ignore[import]
from agents.agent_instances import architect_agent  # type: ignore[import]
from agents.agent_instances import coder_agent          # type: ignore[import]
from agents.agent_instances import test_agent            # type: ignore[import]
from agents.agent_instances import reviewer_agent    # type: ignore[import]
from agents.agent_instances import mediator_agent    # type: ignore[import]
from agents.agent_instances import devops_agent        # type: ignore[import]

logger = logging.getLogger(__name__)

# ── Progress weights ──────────────────────────────────────────────────────────
# Each stage contributes a fixed percentage to overall job progress (0-100).
STAGE_WEIGHTS: dict[str, int] = {
    "planner":    10,
    "architect":  20,
    "parallel":   50,   # coder + test + reviewer combined
    "mediator":   65,
    "devops":     85,
    "complete":   100,
}


# ── Redis helpers ─────────────────────────────────────────────────────────────

async def _publish_event(redis: aioredis.Redis, job_id: str, event: dict) -> None:
    """
    Publish a JSON event to the Redis channel that the WebSocket handler subscribes to.

    The WebSocket handler (api/websocket.py) subscribes to 'job:{job_id}:events'
    and forwards every message it receives directly to the connected client.

    Args:
        redis:  Async Redis client.
        job_id: UUID4 job identifier.
        event:  Dict to serialise and publish.
    """
    channel = f"job:{job_id}:events"
    payload = json.dumps(event)
    try:
        # await: network call to Redis PUBLISH command
        await redis.publish(channel, payload)
        logger.debug("Event published", extra={"job_id": job_id, "event_type": event.get("type")})
    except Exception as exc:
        # Non-fatal — events are best-effort
        logger.warning("Failed to publish event", extra={"job_id": job_id, "error": str(exc)})


async def _update_job(redis: aioredis.Redis, job_id: str, **fields) -> None:
    """
    Update the job's Redis Hash with new field values and bump updated_at.

    Args:
        redis:   Async Redis client.
        job_id:  UUID4 job identifier.
        **fields: Key-value pairs to merge into the job hash.
    """
    now = datetime.now(timezone.utc).isoformat()
    # await: writing updated fields to Redis HSET
    await redis.hset(
        f"job:{job_id}",
        mapping={"updated_at": now, **{k: str(v) for k, v in fields.items()}},
    )


async def _check_cancelled(redis: aioredis.Redis, job_id: str) -> bool:
    """
    Return True if the job has been marked as cancelled by the client.

    The WebSocket handler writes status='cancelled' to Redis when the client
    sends a cancel message. We check this at every stage boundary.

    Args:
        redis:  Async Redis client.
        job_id: UUID4 job identifier.

    Returns:
        bool: True if the job should be aborted.
    """
    # await: reading the current status from Redis
    current_status = await redis.hget(f"job:{job_id}", "status")
    return current_status == "cancelled"


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def run_swarm(job_id: str, requirement: str, options: dict[str, Any] | None = None) -> None:
    """
    Execute the full 7-agent swarm pipeline for a given requirement.

    This is the top-level coroutine called by the Celery task. It runs the
    entire pipeline sequentially (with internal parallelism for the coder/test/
    reviewer stage) and publishes real-time events to Redis as each agent runs.

    Args:
        job_id:      UUID4 identifying this job in Redis.
        requirement: Plain-English description of what to build.
        options:     Optional pipeline config dict from the generate request.

    Returns:
        None — results are written to Redis and published as events.
    """
    options = options or {}
    logger.info("Swarm pipeline starting", extra={"job_id": job_id})

    # Open a Redis client for this coroutine's lifetime
    # await: establishing TCP connection to Redis
    redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)

    try:
        # Mark job as running
        await _update_job(redis, job_id, status="running", current_agent="planner", progress=5)

        # ── STAGE 1: Planner ──────────────────────────────────────────────────
        logger.info("Stage 1: planner_agent", extra={"job_id": job_id})
        await _publish_event(redis, job_id, {
            "type": "agent_update",
            "agent": "planner",
            "status": "running",
            "output": "Analysing requirement and building task graph...",
        })

        if await _check_cancelled(redis, job_id):
            return

        try:
            # await: calling planner_agent (LLM call — may take several seconds)
            task_graph: dict = await with_fallback(
                planner_agent.run, requirement, job_id=job_id
            )
        except Exception as exc:
            await _handle_agent_failure(redis, job_id, "planner", exc)
            return

        await _update_job(redis, job_id, current_agent="architect", progress=STAGE_WEIGHTS["planner"])
        await _publish_event(redis, job_id, {
            "type": "agent_update",
            "agent": "planner",
            "status": "complete",
            "output": f"Task graph: {len(task_graph.get('tasks', []))} tasks identified",
        })

        # ── STAGE 2: Architect ────────────────────────────────────────────────
        logger.info("Stage 2: architect_agent", extra={"job_id": job_id})
        await _publish_event(redis, job_id, {
            "type": "agent_update",
            "agent": "architect",
            "status": "running",
            "output": "Designing folder structure and data schemas...",
        })

        if await _check_cancelled(redis, job_id):
            return

        try:
            # await: calling architect_agent (LLM call)
            architecture: dict = await with_fallback(
                architect_agent.run, task_graph, job_id=job_id
            )
        except Exception as exc:
            await _handle_agent_failure(redis, job_id, "architect", exc)
            return

        await _update_job(redis, job_id, current_agent="coder+test+reviewer", progress=STAGE_WEIGHTS["architect"])
        await _publish_event(redis, job_id, {
            "type": "agent_update",
            "agent": "architect",
            "status": "complete",
            "output": f"Architecture: {len(architecture.get('folders', []))} top-level directories",
        })

        # ── STAGE 3: Parallel — coder, test, reviewer ─────────────────────────
        # These three agents can run simultaneously because:
        #   - coder_agent needs the architecture spec
        #   - test_agent needs the architecture spec (it will later update with code)
        #   - reviewer_agent needs the architecture spec
        # The parallel_runner merges their outputs before we proceed.
        logger.info("Stage 3: parallel agents", extra={"job_id": job_id})

        if await _check_cancelled(redis, job_id):
            return

        try:
            # await: fan-out to coder, test, and reviewer agents in parallel
            parallel_results = await run_parallel_agents(
                architecture=architecture,
                task_graph=task_graph,
                job_id=job_id,
                redis=redis,
                options=options,
            )
        except Exception as exc:
            await _handle_agent_failure(redis, job_id, "parallel_stage", exc)
            return

        code_files: dict[str, str] = parallel_results["code_files"]
        test_files: dict[str, str] = parallel_results["test_files"]
        review_result: dict = parallel_results["review_result"]

        # Publish individual file-written events for every generated file
        for filename in code_files:
            await _publish_event(redis, job_id, {
                "type": "file_written",
                "filename": filename,
            })

        # ── Quality Gate ──────────────────────────────────────────────────────
        logger.info("Quality gate check", extra={"job_id": job_id})
        gate_passed, gate_issues = check_quality(
            code_files=code_files,
            review_result=review_result,
            job_id=job_id,
        )

        if not gate_passed:
            logger.warning(
                "Quality gate failed",
                extra={"job_id": job_id, "issues": gate_issues},
            )
            await _publish_event(redis, job_id, {
                "type": "agent_update",
                "agent": "quality_gate",
                "status": "warning",
                "output": f"Quality issues: {'; '.join(gate_issues)}",
            })
            # We log and warn but don't hard-fail — mediator will attempt to fix issues.

        await _update_job(redis, job_id, current_agent="mediator", progress=STAGE_WEIGHTS["parallel"])

        # ── STAGE 4: Mediator ─────────────────────────────────────────────────
        logger.info("Stage 4: mediator_agent", extra={"job_id": job_id})
        await _publish_event(redis, job_id, {
            "type": "agent_update",
            "agent": "mediator",
            "status": "running",
            "output": "Merging and deduplicating all agent outputs...",
        })

        if await _check_cancelled(redis, job_id):
            return

        all_outputs = {
            "planner":   task_graph,
            "architect": architecture,
            "coder":     {"files": code_files, "dependencies": [], "entry_point": "main.py", "start_command": ""},
            "tester":    {"test_files": test_files, "coverage_target": 80, "test_command": "pytest tests/"},
            "reviewer":  review_result,
        }

        try:
            # await: calling mediator_agent (LLM call — often the longest stage)
            final_codebase: dict[str, str] = await with_fallback(
                mediator_agent.run, all_outputs, job_id=job_id
            )
        except Exception as exc:
            await _handle_agent_failure(redis, job_id, "mediator", exc)
            return

        # Merge using our local merger utility (deduplicates across code + tests)
        # Merge: if mediator returned a FinalCodebase model, extract dicts
        if hasattr(final_codebase, "files"):
            fc_files = final_codebase.files
            fc_tests = final_codebase.test_files if hasattr(final_codebase, "test_files") else test_files
        else:
            fc_files = final_codebase
            fc_tests = test_files
        final_codebase_dict = merge_outputs(fc_files, fc_tests, job_id=job_id)
        # Rebuild as a dict for downstream use
        if hasattr(final_codebase, "model_dump"):
            final_codebase_dict_full = final_codebase.model_dump()
            final_codebase_dict_full["files"] = final_codebase_dict
        else:
            final_codebase_dict_full = {"files": final_codebase_dict}
        final_codebase = type("FC", (), {"model_dump": lambda self: final_codebase_dict_full, "files": final_codebase_dict_full.get("files", {})})()

        await _update_job(redis, job_id, current_agent="devops", progress=STAGE_WEIGHTS["mediator"])
        await _publish_event(redis, job_id, {
            "type": "agent_update",
            "agent": "mediator",
            "status": "complete",
            "output": f"Merged codebase: {len(final_codebase)} files",
        })

        # ── STAGE 5: DevOps ───────────────────────────────────────────────────
        logger.info("Stage 5: devops_agent", extra={"job_id": job_id})
        await _publish_event(redis, job_id, {
            "type": "agent_update",
            "agent": "devops",
            "status": "running",
            "output": "Pushing to GitHub and deploying to Azure...",
        })

        if await _check_cancelled(redis, job_id):
            return

        devops_result: dict = {"github_url": "", "azure_url": ""}
        if options.get("include_devops", True):
            try:
                # await: calling devops_agent (git push + cloud deploy — slow)
                devops_result = await with_fallback(
                    devops_agent.run, final_codebase.model_dump() if hasattr(final_codebase, 'model_dump') else final_codebase, job_id=job_id
                )
            except Exception as exc:
                # Non-fatal: log the error but don't fail the whole job
                logger.error(
                    "devops_agent failed (non-fatal)",
                    extra={"job_id": job_id, "error": str(exc)},
                )
                devops_result = {"github_url": "", "azure_url": ""}

        # ── Persist output ────────────────────────────────────────────────────
        coverage = review_result.get("coverage", 0)

        try:
            # await: writing the full codebase JSON to Redis (may be large)
            await redis.set(
                f"job:{job_id}:output",
                json.dumps(final_codebase.model_dump() if hasattr(final_codebase, "model_dump") else final_codebase),
                ex=86_400,  # 24-hour TTL
            )
        except Exception as exc:
            logger.error(
                "Failed to persist output to Redis",
                extra={"job_id": job_id, "error": str(exc)},
            )

        # ── Mark complete ─────────────────────────────────────────────────────
        await _update_job(
            redis,
            job_id,
            status="complete",
            current_agent="",
            progress=STAGE_WEIGHTS["complete"],
            github_url=devops_result.get("github_url", ""),
            azure_url=devops_result.get("azure_url", ""),
            coverage=str(coverage),
        )

        await _publish_event(redis, job_id, {
            "type": "complete",
            "github_url": devops_result.get("github_url", ""),
            "azure_url":  devops_result.get("azure_url", ""),
            "coverage":   coverage,
        })

        logger.info(
            "Swarm pipeline complete",
            extra={
                "job_id": job_id,
                "files": len(final_codebase),
                "coverage": coverage,
            },
        )

    except Exception as exc:
        # Catch-all: something unexpected crashed the pipeline
        logger.exception(
            "Unhandled exception in swarm pipeline",
            extra={"job_id": job_id, "error": str(exc)},
        )
        try:
            await _update_job(redis, job_id, status="failed", error=str(exc))
            await _publish_event(redis, job_id, {
                "type": "error",
                "message": f"Pipeline failed: {str(exc)}",
            })
        except Exception:
            pass  # Best-effort — the main error is already logged

    finally:
        # Always close the Redis connection we opened for this pipeline run
        # await: closing the TCP connection
        await redis.aclose()


async def _handle_agent_failure(
    redis: aioredis.Redis,
    job_id: str,
    agent_name: str,
    exc: Exception,
) -> None:
    """
    Handle an agent failure: log it, update Redis, and publish an error event.

    Args:
        redis:      Async Redis client.
        job_id:     UUID4 job identifier.
        agent_name: Name of the agent that failed.
        exc:        The exception that was raised.
    """
    error_msg = f"{agent_name} failed: {str(exc)}"
    logger.error(
        "Agent failure",
        extra={"job_id": job_id, "agent": agent_name, "error": str(exc)},
    )
    try:
        await _update_job(redis, job_id, status="failed", error=error_msg)
        await _publish_event(redis, job_id, {
            "type": "error",
            "agent": agent_name,
            "message": error_msg,
        })
    except Exception as inner_exc:
        logger.error(
            "Failed to report agent failure",
            extra={"job_id": job_id, "error": str(inner_exc)},
        )
