"""
memory/session_store.py
-----------------------
Disk-based JSON session storage for Swarm Factory.

Saves and loads full pipeline job sessions as JSON files under SESSION_STORE_PATH.
All writes are atomic (write-to-temp + rename) to prevent corrupt reads on crash.

Usage:
    from memory.session_store import save, load, list_sessions, delete
"""

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Path configuration ────────────────────────────────────────────────────────
_SESSION_DIR = Path(os.environ.get("SESSION_STORE_PATH", "./sessions"))


def _ensure_dir() -> None:
    """Create the sessions directory if it does not already exist."""
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(job_id: str) -> Path:
    """Return the absolute path for a given job_id's JSON file.

    Args:
        job_id: Unique job identifier string.

    Returns:
        Path object pointing to ``{SESSION_DIR}/{job_id}.json``.
    """
    return _SESSION_DIR / f"{job_id}.json"


# ── Public API ────────────────────────────────────────────────────────────────

def save(job_id: str, session_data: dict) -> bool:
    """
    Persist a job session to disk as a JSON file.

    Uses an atomic write (temp file + rename) so partial writes never corrupt
    an existing session. Safe to call multiple times — idempotent.

    Args:
        job_id:       Unique job identifier. Used as the filename stem.
        session_data: Arbitrary dict containing the full pipeline session state.

    Returns:
        True on success, False if an error occurred.
    """
    _ensure_dir()
    target = _session_path(job_id)

    try:
        # Write to a temp file in the same directory, then rename atomically.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=_SESSION_DIR,
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(session_data, tmp, indent=2, default=str)
            tmp_path = tmp.name

        # os.replace is atomic on POSIX and Windows (NTFS).
        os.replace(tmp_path, target)
        logger.debug("[session_store] Saved session | job_id=%s | path=%s", job_id, target)
        return True

    except Exception as exc:
        logger.error("[session_store] Failed to save session | job_id=%s | error=%s", job_id, exc)
        # Clean up orphaned temp file if rename failed.
        try:
            if "tmp_path" in dir() and os.path.exists(tmp_path):  # type: ignore[name-defined]
                os.remove(tmp_path)  # type: ignore[name-defined]
        except Exception:
            pass
        return False


def load(job_id: str) -> dict | None:
    """
    Load a previously saved job session from disk.

    Args:
        job_id: Unique job identifier to look up.

    Returns:
        The session dict, or None if the session file does not exist.
    """
    path = _session_path(job_id)
    if not path.exists():
        logger.debug("[session_store] Session not found | job_id=%s", job_id)
        return None

    try:
        with path.open("r", encoding="utf-8") as fh:
            data: dict = json.load(fh)
        logger.debug("[session_store] Loaded session | job_id=%s", job_id)
        return data
    except Exception as exc:
        logger.error("[session_store] Failed to load session | job_id=%s | error=%s", job_id, exc)
        return None


def list_sessions() -> list[str]:
    """
    Return the job IDs of all persisted sessions.

    Scans SESSION_STORE_PATH for ``*.json`` files and returns their stems.

    Returns:
        Sorted list of job_id strings (empty list if directory doesn't exist).
    """
    if not _SESSION_DIR.exists():
        return []

    try:
        return sorted(p.stem for p in _SESSION_DIR.glob("*.json"))
    except Exception as exc:
        logger.error("[session_store] Failed to list sessions | error=%s", exc)
        return []


def delete(job_id: str) -> bool:
    """
    Delete a session file from disk.

    Args:
        job_id: Unique job identifier to delete.

    Returns:
        True if the file was deleted, False if it didn't exist or an error occurred.
    """
    path = _session_path(job_id)
    if not path.exists():
        logger.debug("[session_store] Delete skipped — session not found | job_id=%s", job_id)
        return False

    try:
        path.unlink()
        logger.debug("[session_store] Deleted session | job_id=%s", job_id)
        return True
    except Exception as exc:
        logger.error("[session_store] Failed to delete session | job_id=%s | error=%s", job_id, exc)
        return False
