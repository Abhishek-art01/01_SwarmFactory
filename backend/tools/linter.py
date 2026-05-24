"""
linter.py — Ruff linter wrapper for Swarm Factory generated code.

Runs ruff (https://docs.astral.sh/ruff/) as a subprocess so that generated
Python files are checked and, where possible, auto-fixed before they are
committed to the output repo.

Importable as:
    from tools.linter import lint_file, lint_and_fix
"""

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def lint_file(filepath: str) -> list[dict]:
    """
    Run ruff on a single Python file and return a list of lint issues.

    Uses ``ruff check --output-format=json`` so that results are machine-
    readable and stable across ruff versions.

    Args:
        filepath: Absolute or relative path to the Python file to lint.

    Returns:
        List of issue dicts, each containing:
            - ``line``    (int)  : 1-based line number of the issue.
            - ``col``     (int)  : 1-based column number of the issue.
            - ``code``    (str)  : Ruff rule code, e.g. ``"E501"``.
            - ``message`` (str)  : Human-readable description of the issue.
        Returns an empty list if the file is clean or ruff is not installed.
    """
    path = Path(filepath)
    if not path.exists():
        logger.warning("[linter] File not found: %s", filepath)
        return []

    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=json", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        logger.error("[linter] ruff not found — install with: pip install ruff")
        return []
    except subprocess.TimeoutExpired:
        logger.error("[linter] ruff timed out on %s", filepath)
        return []

    # ruff exits 0 (clean) or 1 (issues found); both produce valid JSON on stdout
    raw_json = result.stdout.strip()
    if not raw_json:
        return []

    try:
        raw_issues: list[dict] = json.loads(raw_json)
    except json.JSONDecodeError:
        logger.error("[linter] Could not parse ruff JSON output for %s", filepath)
        return []

    issues: list[dict] = []
    for item in raw_issues:
        location = item.get("location", {})
        issues.append(
            {
                "line": location.get("row", 0),
                "col": location.get("column", 0),
                "code": item.get("code", ""),
                "message": item.get("message", ""),
            }
        )

    logger.debug("[linter] %s: %d issue(s) found", filepath, len(issues))
    return issues


def lint_and_fix(filepath: str) -> bool:
    """
    Run ``ruff check --fix`` on a file and verify it is clean afterwards.

    Auto-fixes safe, machine-correctable issues (unused imports, whitespace,
    etc.). After fixing, runs a second check pass to determine whether any
    unfixable issues remain.

    Args:
        filepath: Absolute or relative path to the Python file to fix.

    Returns:
        True  if the file has zero remaining lint issues after fixing.
        False if unfixable issues remain or ruff could not be executed.
    """
    path = Path(filepath)
    if not path.exists():
        logger.warning("[linter] File not found for fixing: %s", filepath)
        return False

    try:
        subprocess.run(
            ["ruff", "check", "--fix", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        logger.error("[linter] ruff not found — install with: pip install ruff")
        return False
    except subprocess.TimeoutExpired:
        logger.error("[linter] ruff --fix timed out on %s", filepath)
        return False

    # Re-run a clean check to see if any issues remain after auto-fixing
    remaining = lint_file(filepath)
    if remaining:
        logger.warning(
            "[linter] %d unfixable issue(s) remain in %s after ruff --fix",
            len(remaining),
            filepath,
        )
        return False

    logger.debug("[linter] %s is clean after ruff --fix", filepath)
    return True
