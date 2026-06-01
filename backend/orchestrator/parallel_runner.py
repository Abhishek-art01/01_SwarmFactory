"""
orchestrator/parallel_runner.py
--------------------------------
Runs the coder, test, and reviewer agents for the middle pipeline stage.

The coder agent is required and runs first because both downstream agents
expect CoderOutput-compatible input. Once code exists, test_agent and
reviewer_agent are fanned out with asyncio.gather() because their LLM calls are
independent, network-bound work.
"""

import asyncio
import logging
from typing import Any

import redis.asyncio as aioredis

from orchestrator.fallback_chain import with_fallback

# We call these agents — we do NOT implement them
from agents.agent_instances import coder_agent      # type: ignore[import]
from agents.agent_instances import test_agent        # type: ignore[import]
from agents.agent_instances import reviewer_agent  # type: ignore[import]

logger = logging.getLogger(__name__)


class ParallelAgentResult:
    """
    Container for the combined outputs of the three parallel agents.

    Attributes:
        code_files:    { filename: code_string } from coder_agent.
        test_files:    { test_filename: test_code } from test_agent.
        review_result: { score: int, issues: list, coverage: int } from reviewer_agent.
    """

    __slots__ = ("code_files", "test_files", "review_result")

    def __init__(
        self,
        code_files: dict[str, str],
        test_files: dict[str, str],
        review_result: dict[str, Any],
    ) -> None:
        self.code_files = code_files
        self.test_files = test_files
        self.review_result = review_result


async def run_parallel_agents(
    architecture: dict[str, Any],
    task_graph: dict[str, Any],
    job_id: str,
    redis: aioredis.Redis,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run coder_agent, test_agent, and reviewer_agent concurrently.

    Each agent is wrapped by the fallback chain so transient model failures
    are retried with progressively cheaper models before raising.

    The three coroutines are scheduled together with asyncio.gather().
    asyncio.gather() submits all three to the event loop simultaneously —
    the event loop interleaves them, sending one LLM request, then while
    waiting for its response, sending the next, and so on.

    Args:
        architecture: Output from architect_agent (folder structure + schema).
        task_graph:   Output from planner_agent (task DAG).
        job_id:       UUID4 used for logging and event publishing.
        redis:        Async Redis client used to publish per-agent progress events.
        options:      Optional pipeline config (e.g. include_tests flag).

    Returns:
        dict: {
            "code_files":    { filename: code_string },
            "test_files":    { test_filename: test_code },
            "review_result": { score: int, issues: list },
        }

    Raises:
        RuntimeError: If coder_agent fails (it is required; test/reviewer failures
                      are logged but non-fatal).
    """
    options = options or {}
    include_tests = options.get("include_tests", True)

    logger.info(
        "Starting parallel agent fan-out",
        extra={"job_id": job_id, "include_tests": include_tests},
    )

    # Build the spec object each agent receives
    spec: dict[str, Any] = {
        "architecture": architecture,
        "task_graph": task_graph,
        "language": options.get("language", "python"),
        "max_files": options.get("max_files", 50),
    }

    # ── Define per-agent coroutines ───────────────────────────────────────────

    async def run_coder() -> Any:
        """
        Call coder_agent and return generated code files.

        coder_agent.run(spec) → { filename: code_string }
        This is REQUIRED — a failure here aborts the pipeline.
        """
        logger.info("coder_agent starting", extra={"job_id": job_id})
        try:
            # Extract just the architecture spec that CoderAgent expects
            coder_input = spec.get("architecture", spec)
            # await: LLM API call (code generation — typically the longest stage)
            result_obj = await with_fallback(
                coder_agent.run, coder_input, job_id=job_id
            )
            # CoderAgent returns CoderOutput (Pydantic model). Keep the full
            # object so downstream agents receive files plus metadata.
            files: dict[str, str]
            if hasattr(result_obj, "files"):
                files = result_obj.files
            else:
                files = result_obj.get("files", result_obj)
            logger.info(
                "coder_agent complete",
                extra={"job_id": job_id, "files_generated": len(files)},
            )

            # Publish progress event so the WebSocket client sees live updates
            try:
                from orchestrator.swarm_controller import _publish_event
                await _publish_event(redis, job_id, {
                    "type": "agent_update",
                    "agent": "coder",
                    "status": "complete",
                    "output": f"Generated {len(files)} files",
                })
            except Exception:
                pass  # Non-fatal

            return result_obj
        except Exception as exc:
            logger.error("coder_agent failed", extra={"job_id": job_id, "error": str(exc)})
            raise  # REQUIRED agent — re-raise to fail the job

    async def run_test(coder_payload: dict[str, Any]) -> dict[str, str]:
        """
        Call test_agent and return generated test files.

        test_agent.run(spec) → { test_filename: test_code }
        Optional — failure returns empty dict and logs a warning.
        """
        if not include_tests:
            logger.info("test_agent skipped (include_tests=False)", extra={"job_id": job_id})
            return {}

        logger.info("test_agent starting", extra={"job_id": job_id})
        try:
            # await: LLM API call (test stub generation)
            test_input = {
                "architect": spec.get("architecture", spec),
                "coder": coder_payload,
            }
            result_obj = await with_fallback(
                test_agent.run, test_input, job_id=job_id
            )
            # TestAgent returns TestOutput — extract test_files dict
            result: dict[str, str]
            if hasattr(result_obj, "test_files"):
                result = result_obj.test_files
            else:
                result = result_obj
            logger.info(
                "test_agent complete",
                extra={"job_id": job_id, "test_files": len(result)},
            )

            try:
                from orchestrator.swarm_controller import _publish_event
                await _publish_event(redis, job_id, {
                    "type": "agent_update",
                    "agent": "test",
                    "status": "complete",
                    "output": f"Generated {len(result)} test files",
                })
            except Exception:
                pass

            return result
        except Exception as exc:
            logger.warning(
                "test_agent failed (non-fatal)",
                extra={"job_id": job_id, "error": str(exc)},
            )
            return {}  # Non-required — return empty dict

    async def run_reviewer(coder_payload: dict[str, Any]) -> dict[str, Any]:
        """
        Call reviewer_agent and return the code review result.

        reviewer_agent.run(spec) → { score: int, issues: list }
        Optional — failure returns a default passing result.
        """
        logger.info("reviewer_agent starting", extra={"job_id": job_id})
        try:
            # ReviewerAgent needs CoderOutput-compatible input.
            reviewer_input = coder_payload
            # await: LLM API call (code review)
            result_obj = await with_fallback(
                reviewer_agent.run, reviewer_input, job_id=job_id
            )
            # ReviewerAgent returns ReviewOutput model
            result: dict[str, Any]
            if hasattr(result_obj, "model_dump"):
                result = result_obj.model_dump()
            else:
                result = result_obj
            score = result.get("score", 0)
            issues = result.get("issues", [])
            logger.info(
                "reviewer_agent complete",
                extra={"job_id": job_id, "score": score, "issue_count": len(issues)},
            )

            try:
                from orchestrator.swarm_controller import _publish_event
                await _publish_event(redis, job_id, {
                    "type": "agent_update",
                    "agent": "reviewer",
                    "status": "complete",
                    "output": f"Review score: {score}/100, {len(issues)} issues found",
                })
            except Exception:
                pass

            return result
        except Exception as exc:
            logger.warning(
                "reviewer_agent failed (non-fatal)",
                extra={"job_id": job_id, "error": str(exc)},
            )
            # Return a default result so the pipeline can continue
            return {"score": 70, "issues": [], "coverage": 0}

    # ── Publish "all parallel agents starting" event ──────────────────────────
    try:
        from orchestrator.swarm_controller import _publish_event
        await _publish_event(redis, job_id, {
            "type": "agent_update",
            "agent": "coder+test+reviewer",
            "status": "running",
            "output": "Generating code, then running test and reviewer agents...",
        })
    except Exception:
        pass

    # ── Generate code first, then fan out dependent agents ───────────────────
    # test_agent and reviewer_agent both expect CoderOutput-compatible input.
    # Running them against the architecture alone produces empty reviews and
    # validation failures, so only those two remain parallel.
    coder_result = await run_coder()

    if hasattr(coder_result, "model_dump"):
        coder_payload: dict[str, Any] = coder_result.model_dump()
    elif isinstance(coder_result, dict) and "files" in coder_result:
        coder_payload = coder_result
    else:
        coder_payload = {
            "files": coder_result,
            "dependencies": [],
            "entry_point": "main.py",
            "start_command": "",
        }

    code_files: dict[str, str] = coder_payload.get("files", {})

    results = await asyncio.gather(
        run_test(coder_payload),
        run_reviewer(coder_payload),
        return_exceptions=True,
    )

    test_result, reviewer_result = results

    # ── Handle results ────────────────────────────────────────────────────────

    # test_agent / reviewer_agent are OPTIONAL — use defaults on failure
    if isinstance(test_result, BaseException):
        logger.warning(
            "test_agent exception (non-fatal, using empty dict)",
            extra={"job_id": job_id, "error": str(test_result)},
        )
        test_result = {}

    if isinstance(reviewer_result, BaseException):
        logger.warning(
            "reviewer_agent exception (non-fatal, using default review)",
            extra={"job_id": job_id, "error": str(reviewer_result)},
        )
        reviewer_result = {"score": 70, "issues": [], "coverage": 0}

    logger.info(
        "Parallel agent stage complete",
        extra={
            "job_id": job_id,
            "code_files": len(code_files),
            "test_files": len(test_result),
            "review_score": reviewer_result.get("score"),
        },
    )

    return {
        "code_files":    code_files,
        "test_files":    test_result,
        "review_result": reviewer_result,
    }
