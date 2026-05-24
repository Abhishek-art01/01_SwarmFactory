"""
orchestrator/fallback_chain.py
-------------------------------
Wraps every agent call with a three-tier model fallback chain:

  GPT-4o (primary)  →  Phi-4 (secondary)  →  GPT-4o-mini (tertiary)

If the primary model fails (network error, rate limit, context overflow),
we transparently retry with the next model in the chain. The agent itself
never needs to know which model is being used — the fallback is transparent.

HOW IT WORKS:
  Each agent is expected to accept an optional `model` keyword argument
  that overrides which Azure OpenAI deployment it targets. If the agent
  doesn't support this, we fall back to environment variable override.
"""

import asyncio
import logging
from typing import Any, Callable

from core.config import settings

logger = logging.getLogger(__name__)

# Ordered list: first is tried first, last is the last resort
FALLBACK_CHAIN: list[str] = [
    settings.FALLBACK_MODEL_PRIMARY,    # gpt-4o
    settings.FALLBACK_MODEL_SECONDARY,  # phi-4
    settings.FALLBACK_MODEL_TERTIARY,   # gpt-4o-mini
]

# Errors that indicate we should retry with the next model
RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)


async def with_fallback(
    agent_fn: Callable,
    *args: Any,
    job_id: str = "",
    **kwargs: Any,
) -> Any:
    """
    Call an agent function, falling back through the model chain on failure.

    Tries each model in FALLBACK_CHAIN in order. If all models fail,
    raises the last exception encountered.

    Args:
        agent_fn: The agent's async run() method, e.g. coder_agent.run.
        *args:    Positional arguments forwarded to agent_fn.
        job_id:   Job identifier for logging (keyword-only).
        **kwargs: Keyword arguments forwarded to agent_fn.

    Returns:
        Any: The return value of the first successful agent_fn call.

    Raises:
        Exception: The exception from the last model attempt if all fail.

    Example:
        result = await with_fallback(coder_agent.run, spec, job_id=job_id)
    """
    last_exc: Exception | None = None

    for attempt, model in enumerate(FALLBACK_CHAIN, start=1):
        try:
            logger.info(
                "Agent call attempt",
                extra={
                    "job_id": job_id,
                    "agent": getattr(agent_fn, "__self__", agent_fn).__class__.__name__,
                    "model": model,
                    "attempt": attempt,
                },
            )

            # Inject the model name as a kwarg so the agent can pick the right deployment.
            # If the agent doesn't accept a `model` kwarg, this will raise TypeError —
            # we catch that and fall through to the next model.
            # await: the agent performs one or more LLM API calls
            result = await agent_fn(*args, model=model, **kwargs)

            if attempt > 1:
                logger.info(
                    "Fallback model succeeded",
                    extra={"job_id": job_id, "model": model, "attempt": attempt},
                )

            return result

        except TypeError as exc:
            # Agent doesn't accept `model` kwarg — try without it
            try:
                # await: retrying without the model override
                result = await agent_fn(*args, **kwargs)
                return result
            except Exception as inner_exc:
                last_exc = inner_exc
                logger.warning(
                    "Agent call failed (no model override)",
                    extra={"job_id": job_id, "model": model, "error": str(inner_exc)},
                )

        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Agent call failed, trying next model",
                extra={
                    "job_id": job_id,
                    "model": model,
                    "attempt": attempt,
                    "error": str(exc),
                    "next_model": FALLBACK_CHAIN[attempt] if attempt < len(FALLBACK_CHAIN) else "none",
                },
            )

            # If this is the last model in the chain, don't swallow the error
            if attempt == len(FALLBACK_CHAIN):
                break

            # Small delay before trying the next model (avoid hammering on errors)
            # await: sleeping briefly to avoid a thundering-herd retry storm
            await asyncio.sleep(1.0 * attempt)

    # All models exhausted
    error_msg = f"All {len(FALLBACK_CHAIN)} models in fallback chain failed"
    logger.error(error_msg, extra={"job_id": job_id, "last_error": str(last_exc)})
    raise RuntimeError(error_msg) from last_exc
