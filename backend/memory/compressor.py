"""
memory/compressor.py
---------------------
Summarises old session data with Phi-4 to keep the memory store lean.

Old sessions accumulate large code blobs and test results that bloat the
context index. The compressor strips them down to a compact summary that
still carries enough signal for context_injector to return useful matches.

Usage:
    from memory.compressor import compress_session, compress_all_old_sessions
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from memory.session_store import load, save, list_sessions

logger = logging.getLogger(__name__)

# ── LLM client (Phi-4 via Azure OpenAI) ──────────────────────────────────────

def _get_phi4_client() -> Any:
    """
    Return an Azure OpenAI async client pointed at the Phi-4 deployment.

    Returns:
        openai.AsyncAzureOpenAI instance.

    Raises:
        ImportError: If openai is not installed.
        KeyError:    If required env vars are missing.
    """
    from openai import AsyncAzureOpenAI

    return AsyncAzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    )


# ── Core summariser ───────────────────────────────────────────────────────────

_COMPRESS_SYSTEM_PROMPT = """You are a technical documentation assistant.
You receive a JSON object describing a software build session (code files, dependencies, test results, etc.).
Your task: produce a compact JSON summary that keeps only the information useful for recommending technologies in future builds.

Return ONLY a valid JSON object with these fields:
{
  "requirement": "<original requirement in one sentence>",
  "tech_stack": {
    "language": "<primary language>",
    "framework": "<primary framework>",
    "database": "<database used or null>",
    "deployment": "<cloud/platform or null>"
  },
  "key_decisions": ["<decision 1>", "<decision 2>"],
  "outcome": "success" | "failure",
  "quality_score": <integer 1-10 or null>
}

Do NOT include file contents, test code, or raw logs. Be concise."""


@retry(
    retry=retry_if_exception_type((json.JSONDecodeError, ValueError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _call_phi4(session_json: str) -> dict:
    """
    Call Phi-4 to summarise a session JSON blob.

    Args:
        session_json: JSON-serialised session data string.

    Returns:
        Parsed summary dict matching the schema in _COMPRESS_SYSTEM_PROMPT.

    Raises:
        json.JSONDecodeError: If Phi-4's response can't be parsed.
        ValueError:           If the parsed object is missing required keys.
    """
    client = _get_phi4_client()
    phi4_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_PHI4", "phi-4")

    response = await client.chat.completions.create(
        model=phi4_deployment,
        temperature=0.2,
        max_tokens=500,
        messages=[
            {"role": "system", "content": _COMPRESS_SYSTEM_PROMPT},
            {"role": "user", "content": f"Summarise this session:\n\n{session_json}"},
        ],
    )

    raw: str = response.choices[0].message.content or ""
    # Strip markdown fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    summary: dict = json.loads(raw)

    # Validate required keys
    required = {"requirement", "tech_stack", "key_decisions", "outcome"}
    missing = required - summary.keys()
    if missing:
        raise ValueError(f"Phi-4 summary missing keys: {missing}")

    return summary


def _is_compressible(session: dict) -> bool:
    """
    Return True if a session is large enough to warrant compression.

    Compression is skipped if:
    - The session has already been compressed (has a 'compressed' flag).
    - The session is small (total JSON < 10 KB).

    Args:
        session: The raw session dict loaded from disk.

    Returns:
        True if the session should be compressed.
    """
    if session.get("compressed", False):
        return False

    raw_size = len(json.dumps(session))
    return raw_size > 10_000  # 10 KB threshold


# ── Public API ────────────────────────────────────────────────────────────────

async def compress_session(job_id: str) -> bool:
    """
    Summarise a single session with Phi-4 and write the compact version back to disk.

    The original code blobs and test output are replaced with the summary.
    The 'compressed' flag is set so this session is not processed again.

    Args:
        job_id: Unique job identifier of the session to compress.

    Returns:
        True if compressed and saved successfully, False otherwise.
    """
    session = load(job_id)
    if session is None:
        logger.warning("[compressor] Session not found | job_id=%s", job_id)
        return False

    if not _is_compressible(session):
        logger.debug("[compressor] Session skipped (not compressible) | job_id=%s", job_id)
        return True  # Not an error — nothing to do

    logger.info("[compressor] Compressing session | job_id=%s", job_id)

    try:
        # Truncate the session to avoid sending megabytes to Phi-4.
        # Keep planner/architect outputs (rich signal); strip raw code blobs.
        compact_input = {
            "job_id": session.get("job_id", job_id),
            "requirement": session.get("requirement", ""),
            "planner": session.get("planner", {}),
            "architect": session.get("architect", {}),
            "dependencies": session.get("dependencies", []),
            "quality_score": session.get("quality_score"),
            "status": session.get("status", "unknown"),
        }
        session_json = json.dumps(compact_input, indent=2)[:8000]  # cap at 8 KB

        summary = await _call_phi4(session_json)

        # Preserve metadata fields, replace large payloads with summary
        compressed_session = {
            "job_id": job_id,
            "requirement": session.get("requirement", summary.get("requirement", "")),
            "summary": summary,
            "compressed": True,
            "compressed_at": datetime.now(timezone.utc).isoformat(),
            # Keep original timestamps if present
            "created_at": session.get("created_at"),
            "completed_at": session.get("completed_at"),
        }

        ok = save(job_id, compressed_session)
        if ok:
            logger.info(
                "[compressor] Session compressed | job_id=%s | size_before=%d",
                job_id,
                len(session_json),
            )
        return ok

    except Exception as exc:
        logger.error(
            "[compressor] Failed to compress session | job_id=%s | error=%s", job_id, exc
        )
        return False


async def compress_all_old_sessions(older_than_days: int = 7) -> dict[str, bool]:
    """
    Compress all sessions older than ``older_than_days`` days.

    Skips sessions that are already compressed or too small to bother.
    Designed to run as a periodic background task (e.g., Celery beat).

    Args:
        older_than_days: Sessions with 'completed_at' older than this many
                         days will be compressed. Defaults to 7 days.

    Returns:
        Dict mapping job_id → True (compressed) / False (failed).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    job_ids = list_sessions()
    results: dict[str, bool] = {}

    for job_id in job_ids:
        session = load(job_id)
        if session is None:
            continue

        # Skip already-compressed sessions
        if session.get("compressed", False):
            continue

        # Only compress sessions older than the cutoff
        completed_at_str = session.get("completed_at")
        if completed_at_str:
            try:
                completed_at = datetime.fromisoformat(completed_at_str)
                if completed_at.tzinfo is None:
                    completed_at = completed_at.replace(tzinfo=timezone.utc)
                if completed_at > cutoff:
                    continue  # Too recent, skip
            except ValueError:
                pass  # Malformed timestamp — compress it anyway

        results[job_id] = await compress_session(job_id)

    logger.info(
        "[compressor] Bulk compression complete | processed=%d | succeeded=%d",
        len(results),
        sum(v for v in results.values()),
    )
    return results
