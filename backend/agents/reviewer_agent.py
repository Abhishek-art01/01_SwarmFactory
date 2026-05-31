"""
agents/reviewer_agent.py
-------------------------
Agent 5 (Reviewer) for Swarm Factory.

Audits generated code for bugs, security vulnerabilities, and quality issues.
Returns a ReviewOutput with a 1-10 quality score, approval decision, and a
detailed list of ReviewIssue objects.

Importable as:
    from agents.reviewer_agent import ReviewerAgent, ReviewOutput, ReviewIssue
"""

import json
import logging
from typing import Any

from pydantic import BaseModel, field_validator

from agents.base_agent import BaseAgent
from prompts.reviewer import REVIEWER_SYSTEM_PROMPT, build_reviewer_user_prompt

logger = logging.getLogger(__name__)


# ── Output schemas ────────────────────────────────────────────────────────────

class ReviewIssue(BaseModel):
    """
    A single issue found during code review.

    Attributes:
        file:     Relative path of the affected file, e.g. "main.py".
        line:     Line number if known, None if the issue is file-level.
        severity: One of "critical" | "high" | "medium" | "low".
        issue:    Human-readable description of the problem.
        fix:      Concrete, actionable suggestion to resolve the issue.
    """

    file: str
    line: int | None = None
    severity: str
    issue: str
    fix: str

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        """Normalise severity to lowercase and validate allowed values."""
        v = v.lower().strip()
        allowed = {"critical", "high", "medium", "low"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}, got '{v}'")
        return v


class ReviewOutput(BaseModel):
    """
    Structured output returned by ReviewerAgent.run().

    Attributes:
        score:    Quality score from 1 (dangerous) to 10 (perfect).
        approved: True if score >= 5, False otherwise.
        issues:   List of ReviewIssue objects found during the review.
        summary:  One-paragraph summary of overall findings and risk level.
    """

    score: int
    approved: bool
    issues: list[ReviewIssue]
    summary: str

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: int) -> int:
        """Clamp score to [1, 10] range."""
        return max(1, min(10, v))


# ── Agent implementation ──────────────────────────────────────────────────────

class ReviewerAgent(BaseAgent):
    """
    Agent 5 in the Swarm Factory pipeline.

    Receives a CoderOutput (or compatible dict) and returns a ReviewOutput
    containing a quality score, approval flag, and all identified issues.

    LLM call uses:
        - temperature=0.2  (consistent, deterministic audit results)
        - max_tokens=3000  (enough for multi-file review with many issues)
        - up to 3 retries  (via BaseAgent.call_llm's tenacity decorator)
    """

    name: str = "reviewer"

    def __init__(self) -> None:
        """Initialise base class (sets up Azure OpenAI async client)."""
        super().__init__()

    async def run(self, input_data: Any) -> ReviewOutput:
        """
        Execute the reviewer agent on a CoderOutput or compatible dict.

        Steps:
            1. Normalise input_data to a plain dict.
            2. Build the reviewer user prompt with line-numbered file contents.
            3. Call GPT-4o with retry logic.
            4. Strip markdown fences and parse the JSON response.
            5. Validate the parsed data against ReviewOutput with Pydantic.
            6. Compute the 'approved' flag (True if score >= 5).

        Args:
            input_data: A CoderOutput instance, a dict with keys
                        {files, dependencies, entry_point, start_command},
                        or a JSON string.

        Returns:
            A validated ReviewOutput instance.

        Raises:
            json.JSONDecodeError: If JSON parsing fails after 3 retries.
            pydantic.ValidationError: If the parsed JSON doesn't match ReviewOutput.
        """
        # ── Normalise input ──────────────────────────────────────────────────
        if hasattr(input_data, "model_dump"):
            data = input_data.model_dump()
        elif isinstance(input_data, dict):
            data = input_data
        elif isinstance(input_data, str):
            data = json.loads(input_data)
        else:
            raise TypeError(f"ReviewerAgent.run() received unsupported input type: {type(input_data)}")

        files: dict[str, str] = data.get("files", {})
        dependencies: list[str] = data.get("dependencies", [])
        entry_point: str = data.get("entry_point", "")
        start_command: str = data.get("start_command", "")

        logger.info(
            "[reviewer] Starting review | files=%d | deps=%d",
            len(files),
            len(dependencies),
        )

        # ── Build prompt ─────────────────────────────────────────────────────
        user_prompt = build_reviewer_user_prompt(
            files=files,
            dependencies=dependencies,
            entry_point=entry_point,
            start_command=start_command,
        )

        # ── Call LLM ─────────────────────────────────────────────────────────
        raw_response = await self._call_llm(
            system_prompt=REVIEWER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=3000,
        )

        # ── Parse & validate response ────────────────────────────────────────
        output = self._parse_response(raw_response)

        logger.info(
            "[reviewer] Review complete | score=%d | approved=%s | issues=%d",
            output.score,
            output.approved,
            len(output.issues),
        )
        return output

    def _parse_response(self, raw: str) -> ReviewOutput:
        """
        Parse the raw LLM response into a validated ReviewOutput.

        Handles markdown fences, partial JSON, and missing fields gracefully.
        If the score vs approved flag are inconsistent, recalculates approved.

        Args:
            raw: Raw string from the LLM, possibly with markdown fences.

        Returns:
            A validated ReviewOutput instance.

        Raises:
            json.JSONDecodeError: If the response cannot be parsed as JSON.
            pydantic.ValidationError: If the parsed object fails schema validation.
        """
        cleaned = self._parse_json(raw)

        try:
            parsed: dict = cleaned
        except json.JSONDecodeError as exc:
            logger.error("[reviewer] Failed to parse LLM response as JSON | error=%s", exc)
            raise

        # Ensure 'approved' is always consistent with score
        score: int = parsed.get("score", 1)
        parsed["approved"] = score >= 5

        # Validate issues list — drop any malformed entries
        raw_issues = parsed.get("issues", [])
        valid_issues: list[dict] = []
        for item in raw_issues:
            if isinstance(item, dict) and "issue" in item and "severity" in item:
                valid_issues.append(item)
            else:
                logger.warning("[reviewer] Dropping malformed issue entry: %s", item)
        parsed["issues"] = valid_issues

        return ReviewOutput.model_validate(parsed)
