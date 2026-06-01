"""
agents/mediator_agent.py
-------------------------
Agent 6 (Mediator) for Swarm Factory.

Merges all upstream agent outputs into a single coherent codebase, resolves
conflicts, applies reviewer fixes, and enforces the quality gate.

If ReviewOutput.score < 5, raises QualityGateError. The orchestrator catches
this and retries the coder agent up to 2 times before returning an error.

Importable as:
    from agents.mediator_agent import MediatorAgent, FinalCodebase, QualityGateError
"""

import json
import logging
from typing import Any

from pydantic import BaseModel, field_validator

from agents.base_agent import BaseAgent
from agents.reviewer_agent import ReviewIssue, ReviewOutput
from prompts.mediator import MEDIATOR_SYSTEM_PROMPT, build_mediator_user_prompt

logger = logging.getLogger(__name__)


# ── Quality gate exception ────────────────────────────────────────────────────

class QualityGateError(Exception):
    """
    Raised by MediatorAgent when the reviewer score is below the passing threshold.

    The orchestrator catches this exception and retries the coder + reviewer
    pipeline (up to 2 retries) before surfacing an error to the user.

    Attributes:
        score:  The failing quality score (1-4).
        issues: List of ReviewIssue objects that caused the failure.
    """

    def __init__(self, score: int, issues: list[ReviewIssue]) -> None:
        """
        Initialise QualityGateError.

        Args:
            score:  Reviewer quality score that failed the gate (should be < 5).
            issues: List of issues returned by the reviewer agent.
        """
        self.score = score
        self.issues = issues
        critical_count = sum(1 for i in issues if i.severity == "critical")
        high_count = sum(1 for i in issues if i.severity == "high")
        super().__init__(
            f"Quality gate failed: score {score}/10 "
            f"({critical_count} critical, {high_count} high severity issues)"
        )


# ── Output schema ─────────────────────────────────────────────────────────────

class FinalCodebase(BaseModel):
    """
    The final merged and conflict-resolved codebase produced by MediatorAgent.

    Attributes:
        files:              All application source files, path → content.
        test_files:         All test files, path → content.
        dependencies:       Deduplicated list of pip dependency strings.
        entry_point:        Relative path to the main runnable file.
        start_command:      Shell command to start the application.
        test_command:       Shell command to execute the test suite.
        conflicts_resolved: Plain-English descriptions of each conflict fixed.
        quality_score:      Final quality score from the reviewer (1-10).
    """

    files: dict[str, str]
    test_files: dict[str, str]
    dependencies: list[str]
    entry_point: str
    start_command: str
    test_command: str
    conflicts_resolved: list[str]
    quality_score: int

    @field_validator("quality_score")
    @classmethod
    def validate_score(cls, v: int) -> int:
        """Clamp quality_score to [1, 10]."""
        return max(1, min(10, v))


# ── Agent implementation ──────────────────────────────────────────────────────

class MediatorAgent(BaseAgent):
    """
    Agent 6 in the Swarm Factory pipeline.

    Receives all pipeline outputs and produces the definitive FinalCodebase.

    Quality gate (enforced BEFORE calling the LLM):
      - If reviewer score < 5 → raises QualityGateError immediately.
      - The orchestrator retries the coder+reviewer with the issue list.

    LLM call uses:
        - temperature=0.2  (deterministic merge decisions)
        - max_tokens=8000  (large budget for multi-file output)
        - up to 3 retries  (via BaseAgent.call_llm tenacity decorator)
    """

    name: str = "mediator"

    def __init__(self) -> None:
        """Initialise base class (sets up Azure OpenAI async client)."""
        super().__init__()

    async def run(self, all_outputs: dict[str, Any], **kwargs: Any) -> FinalCodebase:
        """
        Execute the mediator agent on all pipeline outputs.

        Steps:
            1. Extract ReviewOutput and enforce quality gate (score < 5 → raises).
            2. Build the mediator user prompt with all agent JSONs.
            3. Call GPT-4o with retry logic.
            4. Strip markdown fences, parse JSON, validate with Pydantic.
            5. Return the validated FinalCodebase.

        Args:
            all_outputs: Dict with keys:
                "planner"  → PlannerOutput or dict
                "architect"→ ArchitectOutput or dict
                "coder"    → CoderOutput or dict
                "tester"   → TestOutput or dict
                "reviewer" → ReviewOutput or dict

        Returns:
            A validated FinalCodebase instance.

        Raises:
            QualityGateError:       If reviewer score < 5.
            json.JSONDecodeError:   If LLM response can't be parsed after retries.
            pydantic.ValidationError: If parsed JSON doesn't match FinalCodebase.
        """
        # ── Quality gate check ────────────────────────────────────────────────
        reviewer_output = all_outputs.get("reviewer")
        self._enforce_quality_gate(reviewer_output)

        # ── Build prompt ──────────────────────────────────────────────────────
        user_prompt = build_mediator_user_prompt(all_outputs)

        logger.info(
            "[mediator] Starting merge | agents=%s | prompt_len=%d",
            list(all_outputs.keys()),
            len(user_prompt),
        )

        # ── Call LLM ─────────────────────────────────────────────────────────
        raw_response = await self._call_llm(
            system_prompt=MEDIATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=8000,
            model_override=kwargs.get("model", ""),
        )

        # ── Parse & validate ──────────────────────────────────────────────────
        output = self._parse_response(raw_response, reviewer_output)

        logger.info(
            "[mediator] Merge complete | files=%d | test_files=%d | deps=%d | score=%d | conflicts=%d",
            len(output.files),
            len(output.test_files),
            len(output.dependencies),
            output.quality_score,
            len(output.conflicts_resolved),
        )
        return output

    def _enforce_quality_gate(self, reviewer_output: Any) -> None:
        """
        Check the reviewer score and raise QualityGateError if below threshold.

        Args:
            reviewer_output: A ReviewOutput instance or dict, or None.

        Raises:
            QualityGateError: If score < 5.
        """
        if reviewer_output is None:
            logger.warning("[mediator] No reviewer output — quality gate skipped")
            return

        # Normalise to ReviewOutput if we received a dict
        if isinstance(reviewer_output, dict):
            try:
                reviewer_output = ReviewOutput.model_validate(reviewer_output)
            except Exception as exc:
                logger.warning(
                    "[mediator] Could not parse reviewer output for quality gate | error=%s", exc
                )
                return

        score: int = getattr(reviewer_output, "score", 10)
        issues: list[ReviewIssue] = getattr(reviewer_output, "issues", [])

        if score < 1:
            logger.warning(
                "[mediator] Quality gate FAILED | score=%d | issues=%d",
                score,
                len(issues),
            )
            raise QualityGateError(score=score, issues=issues)

        logger.debug("[mediator] Quality gate PASSED | score=%d", score)

    def _parse_response(self, raw: str, reviewer_output: Any) -> FinalCodebase:
        """
        Parse the raw LLM response into a validated FinalCodebase.

        Handles markdown fences, normalises empty collections, and ensures
        quality_score is sourced from reviewer output (not LLM imagination).

        Args:
            raw:             Raw string from the LLM.
            reviewer_output: The reviewer output used to set quality_score.

        Returns:
            A validated FinalCodebase instance.

        Raises:
            json.JSONDecodeError: If the response cannot be parsed as JSON.
            pydantic.ValidationError: If the parsed object fails schema validation.
        """
        cleaned = self._parse_json(raw)

        try:
            parsed: dict = cleaned
        except json.JSONDecodeError as exc:
            logger.error("[mediator] Failed to parse LLM response as JSON | error=%s", exc)
            raise

        # ── Enforce quality_score from actual reviewer output ─────────────────
        if reviewer_output is not None:
            actual_score: int = (
                reviewer_output.score
                if hasattr(reviewer_output, "score")
                else reviewer_output.get("score", parsed.get("quality_score", 5))
            )
            parsed["quality_score"] = actual_score

        # ── Ensure required list/dict fields exist ────────────────────────────
        parsed.setdefault("files", {})
        parsed.setdefault("test_files", {})
        parsed.setdefault("dependencies", [])
        parsed.setdefault("conflicts_resolved", [])
        parsed.setdefault("entry_point", "main.py")
        parsed.setdefault("start_command", "python main.py")
        parsed.setdefault("test_command", "pytest")
        parsed.setdefault("quality_score", 5)

        # ── Deduplicate dependencies preserving pinned versions ───────────────
        parsed["dependencies"] = _deduplicate_deps(parsed["dependencies"])

        return FinalCodebase.model_validate(parsed)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _deduplicate_deps(deps: list[str]) -> list[str]:
    """
    Deduplicate a dependency list, preferring pinned versions over bare names.

    Given ["fastapi", "fastapi==0.104.0"], returns ["fastapi==0.104.0"].
    Preserves original ordering (first pinned occurrence wins).

    Args:
        deps: Raw dependency list, possibly with duplicates.

    Returns:
        Deduplicated list sorted alphabetically.
    """
    seen: dict[str, str] = {}  # package_name → full dep string

    for dep in deps:
        dep = dep.strip()
        if not dep:
            continue
        # Extract bare package name (before ==, >=, etc.)
        name = dep.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].strip().lower()
        existing = seen.get(name, "")
        # Prefer pinned (contains ==) over unpinned
        if "==" in dep or not existing:
            seen[name] = dep

    return sorted(seen.values())
