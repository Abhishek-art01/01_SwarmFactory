"""
orchestrator/quality_gate.py
-----------------------------
Validates agent outputs before they reach the mediator.

Checks performed:
  1. Reviewer score above minimum threshold
  2. No empty code files
  3. No obviously malformed files (e.g. only whitespace)
  4. Required entry-point files present (main.py / app.py / index.py)

Returns (passed: bool, issues: list[str]).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Minimum reviewer score to pass the gate (out of 100)
MIN_REVIEW_SCORE = 50

# At least one of these must be present in the generated files
REQUIRED_ENTRYPOINTS = {"main.py", "app.py", "index.py", "server.py", "__init__.py"}


def _normalise_review_score(score: Any) -> int:
    """Return reviewer score on the 0-100 scale used by the quality gate."""
    try:
        numeric_score = int(score)
    except (TypeError, ValueError):
        return 0

    if 1 <= numeric_score <= 10:
        return numeric_score * 10
    return max(0, min(100, numeric_score))


def check_quality(
    code_files: dict[str, str],
    review_result: dict[str, Any],
    job_id: str = "",
) -> tuple[bool, list[str]]:
    """
    Run quality checks on the generated code before mediator merging.

    Args:
        code_files:    { filename: code_string } from coder_agent.
        review_result: { score: int, issues: list } from reviewer_agent.
        job_id:        UUID4 for logging.

    Returns:
        tuple[bool, list[str]]:
            - True if all checks pass (or issues are non-blocking)
            - List of issue strings (empty if gate passes cleanly)
    """
    issues: list[str] = []

    # ── Check 1: reviewer score ───────────────────────────────────────────────
    score = _normalise_review_score(review_result.get("score", 0))
    if score < MIN_REVIEW_SCORE:
        issues.append(f"Review score {score}/100 is below threshold ({MIN_REVIEW_SCORE})")

    # ── Check 2: non-empty output ─────────────────────────────────────────────
    if not code_files:
        issues.append("coder_agent produced zero files")
        logger.error("Quality gate: zero files generated", extra={"job_id": job_id})
        return False, issues  # Hard fail — nothing to work with

    # ── Check 3: no blank files ───────────────────────────────────────────────
    blank_files = [f for f, content in code_files.items() if not content.strip()]
    if blank_files:
        issues.append(f"Blank files detected: {', '.join(blank_files[:5])}")

    # ── Check 4: entry point present ─────────────────────────────────────────
    file_names = {f.split("/")[-1] for f in code_files}
    if not file_names.intersection(REQUIRED_ENTRYPOINTS):
        issues.append(
            f"No recognisable entry point found. Expected one of: {REQUIRED_ENTRYPOINTS}"
        )

    passed = len(issues) == 0
    log_fn = logger.info if passed else logger.warning
    log_fn(
        "Quality gate result",
        extra={"job_id": job_id, "passed": passed, "issue_count": len(issues)},
    )

    return passed, issues
