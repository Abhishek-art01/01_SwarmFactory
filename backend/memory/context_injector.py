"""
memory/context_injector.py
--------------------------
Retrieves relevant past build context to inject into agent prompts.

Primary path:  Azure AI Search (vector similarity).
Fallback path: Simple keyword overlap over local session JSON files.

The system works correctly with or without Azure AI Search configured.

Usage:
    from memory.context_injector import get_relevant_context, save_context
"""

import json
import logging
import os
from pathlib import Path

from memory.session_store import list_sessions, load

logger = logging.getLogger(__name__)

# ── Context index file (lightweight local index used by fallback) ─────────────
_SESSION_DIR = Path(os.environ.get("SESSION_STORE_PATH", "./sessions"))
_CONTEXT_INDEX_FILE = _SESSION_DIR / "_context_index.json"

# ── Azure Search availability check ──────────────────────────────────────────
def _azure_search_configured() -> bool:
    """Return True if all Azure AI Search environment variables are present."""
    return bool(
        os.environ.get("AZURE_SEARCH_ENDPOINT")
        and os.environ.get("AZURE_SEARCH_API_KEY")
        and os.environ.get("AZURE_SEARCH_INDEX_NAME")
    )


# ── Local fallback: keyword overlap ──────────────────────────────────────────

def _load_context_index() -> list[dict]:
    """
    Load the local context index JSON file.

    Returns:
        List of context entry dicts. Empty list if file doesn't exist or is corrupt.
    """
    if not _CONTEXT_INDEX_FILE.exists():
        return []
    try:
        with _CONTEXT_INDEX_FILE.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("[context_injector] Failed to load context index | error=%s", exc)
        return []


def _save_context_index(entries: list[dict]) -> bool:
    """
    Atomically write the context index to disk.

    Args:
        entries: List of context entry dicts.

    Returns:
        True on success, False on error.
    """
    import tempfile
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=_SESSION_DIR,
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(entries, tmp, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, _CONTEXT_INDEX_FILE)
        return True
    except Exception as exc:
        logger.error("[context_injector] Failed to save context index | error=%s", exc)
        return False


def _keyword_score(requirement: str, entry_requirement: str) -> int:
    """
    Compute a simple keyword overlap score between two requirement strings.

    Args:
        requirement:       The current requirement to match.
        entry_requirement: A stored past requirement.

    Returns:
        Count of shared lowercase words (excluding short stop words).
    """
    stop_words = {"a", "an", "the", "with", "and", "or", "for", "to", "of", "in", "on"}
    current_words = {w.lower() for w in requirement.split() if w.lower() not in stop_words}
    past_words = {w.lower() for w in entry_requirement.split() if w.lower() not in stop_words}
    return len(current_words & past_words)


def _local_search(requirement: str, max_sessions: int) -> list[dict]:
    """
    Search local session context index by keyword overlap.

    Args:
        requirement:  The current user requirement string.
        max_sessions: Maximum number of results to return.

    Returns:
        List of best-matching context entry dicts, sorted by score descending.
    """
    entries = _load_context_index()
    if not entries:
        return []

    scored = [
        (entry, _keyword_score(requirement, entry.get("requirement", "")))
        for entry in entries
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [entry for entry, score in scored if score > 0][:max_sessions]


def _azure_search_similar(requirement: str, max_sessions: int) -> list[dict]:
    """
    Search Azure AI Search for semantically similar past requirements.

    Imports azure_search lazily so the module loads cleanly even when
    Azure Search is not configured.

    Args:
        requirement:  The current user requirement string.
        max_sessions: Maximum number of results to return.

    Returns:
        List of matching context dicts. Empty list on any error.
    """
    try:
        from memory.azure_search import search_similar  # lazy import
        results = search_similar(requirement, top_k=max_sessions)
        return results
    except Exception as exc:
        logger.warning(
            "[context_injector] Azure Search query failed, falling back to local | error=%s", exc
        )
        return []


def _format_context(entries: list[dict]) -> str:
    """
    Format a list of context entries into the prompt injection string.

    Args:
        entries: List of dicts with 'requirement' and 'tech_stack' keys.

    Returns:
        Formatted multi-line string, or empty string if entries is empty.
    """
    if not entries:
        return ""

    lines = ["PAST CONTEXT:"]
    for entry in entries:
        req = entry.get("requirement", "unknown requirement")
        tech = entry.get("tech_stack", {})
        if isinstance(tech, dict):
            tech_str = ", ".join(f"{k}: {v}" for k, v in tech.items() if v)
        else:
            tech_str = str(tech)
        lines.append(f"- Built a project for: {req!r} using: {tech_str}")

    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def get_relevant_context(requirement: str, max_sessions: int = 3) -> str:
    """
    Search past sessions for similar requirements and return a formatted context string.

    Tries Azure AI Search first (if configured), falls back to local keyword
    similarity over the context index file. Always returns a string — empty
    string if no relevant context exists.

    Args:
        requirement:  Current user requirement string.
        max_sessions: Maximum number of past sessions to include (default 3).

    Returns:
        Formatted context string like:
          "PAST CONTEXT:\\n- Built a FastAPI auth API using: Python, FastAPI, PostgreSQL\\n..."
        or "" if no relevant context is found.
    """
    if not requirement or not requirement.strip():
        return ""

    try:
        if _azure_search_configured():
            entries = _azure_search_similar(requirement, max_sessions)
            if entries:
                logger.debug(
                    "[context_injector] Azure Search returned %d results", len(entries)
                )
                return _format_context(entries)
            # Fall through to local search if Azure returned nothing
            logger.debug("[context_injector] Azure Search returned 0 results, trying local")

        entries = _local_search(requirement, max_sessions)
        logger.debug("[context_injector] Local search returned %d results", len(entries))
        return _format_context(entries)

    except Exception as exc:
        logger.error("[context_injector] get_relevant_context failed | error=%s", exc)
        return ""


def save_context(job_id: str, requirement: str, tech_stack: dict) -> bool:
    """
    Save a completed build's requirement + tech stack to the local context index.

    Called after a successful pipeline run so future jobs can benefit from
    what was learned. Also upserts the entry into Azure AI Search if configured.

    Args:
        job_id:      Unique job identifier (used to deduplicate entries).
        requirement: The original user requirement string.
        tech_stack:  Dict of technology choices, e.g. {"language": "python",
                     "framework": "fastapi", "database": "postgresql"}.

    Returns:
        True on success, False on any error.
    """
    if not job_id or not requirement:
        logger.warning("[context_injector] save_context called with empty job_id or requirement")
        return False

    entry = {
        "job_id": job_id,
        "requirement": requirement,
        "tech_stack": tech_stack,
    }

    # ---- Update local context index ----------------------------------------
    try:
        entries = _load_context_index()
        # Upsert: remove existing entry for this job_id, then append updated one
        entries = [e for e in entries if e.get("job_id") != job_id]
        entries.append(entry)
        local_ok = _save_context_index(entries)
    except Exception as exc:
        logger.error("[context_injector] Failed to update local context index | error=%s", exc)
        local_ok = False

    # ---- Upsert into Azure AI Search (best-effort) -------------------------
    if _azure_search_configured():
        try:
            from memory.azure_search import upsert_document  # lazy import
            upsert_document(job_id=job_id, requirement=requirement, tech_stack=tech_stack)
            logger.debug("[context_injector] Upserted into Azure Search | job_id=%s", job_id)
        except Exception as exc:
            logger.warning(
                "[context_injector] Azure Search upsert failed (non-fatal) | error=%s", exc
            )

    return local_ok
