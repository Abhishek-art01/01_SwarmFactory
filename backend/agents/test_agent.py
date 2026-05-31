"""
test_agent.py — Agent 4: Test Agent for Swarm Factory.

Receives a CoderOutput (generated source files) plus the original ArchitectOutput
and returns a TestOutput containing a complete pytest test suite targeting ≥80%
line coverage.

Importable as:
    from agents.test_agent import TestAgent, TestOutput
"""

import json
import logging
from typing import Any

from pydantic import BaseModel

from agents.base_agent import BaseAgent
from agents.architect_agent import ArchitectOutput
from agents.coder_agent import CoderOutput
from prompts.test_writer import TEST_WRITER_SYSTEM_PROMPT, TEST_WRITER_USER_TEMPLATE
from tools.file_writer import write_files
from tools.linter import lint_and_fix
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestOutput(BaseModel):
    """
    Structured output returned by TestAgent.run().

    Attributes:
        test_files:      Mapping of relative file paths to their complete content.
                         Example: {"tests/test_main.py": "import pytest\\n..."}
        coverage_target: Minimum line-coverage percentage the suite must achieve.
                         Always 80 unless the LLM negotiates a higher target.
        test_command:    Shell command to execute the full test suite with coverage.
                         Example: "pytest tests/ --cov=. --cov-report=term-missing"
    """

    test_files: dict[str, str]
    coverage_target: int
    test_command: str


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------

class TestAgent(BaseAgent):
    """
    Agent 4 in the Swarm Factory pipeline.

    Accepts a CoderOutput (and optionally the ArchitectOutput for contract
    context) and returns a complete pytest test suite.

    After receiving the LLM response the agent:
    1. Parses and validates the JSON with Pydantic.
    2. Writes every test file atomically via file_writer.
    3. Runs ruff auto-fix on every generated test file.

    LLM call uses:
        - temperature=0.2  (consistent, deterministic test output)
        - max_tokens=8000  (large budget for multi-file test generation)
        - up to 3 retries  (via BaseAgent.call_llm's tenacity decorator)
    """

    name: str = "test"

    def __init__(self) -> None:
        """Initialise base class (sets up Azure OpenAI client)."""
        super().__init__()

    async def run(self, input_data: Any) -> TestOutput:
        """
        Execute the test agent on the pipeline output.

        ``input_data`` can be:
        - A ``CoderOutput`` instance (architect context will be empty).
        - A tuple of ``(ArchitectOutput, CoderOutput)`` for full context.
        - A dict with keys ``"architect"`` and ``"coder"`` holding the respective
          model instances or their JSON-serialisable dict representations.

        Steps:
            1. Normalise input and serialise both specs to JSON.
            2. Call the LLM with retry logic.
            3. Strip markdown fences, parse JSON, validate with Pydantic.
            4. Write test files atomically to disk alongside the source files.
            5. Run ruff --fix on every generated test file.

        Args:
            input_data: CoderOutput, (ArchitectOutput, CoderOutput) tuple, or
                        dict with "architect" and "coder" keys.

        Returns:
            A validated TestOutput instance.

        Raises:
            json.JSONDecodeError: If JSON parsing fails after 3 retries.
            pydantic.ValidationError: If the parsed JSON doesn't match TestOutput.
        """
        # ---- Normalise input -----------------------------------------------
        architect_json, coder_output = self._unpack_input(input_data)

        files_json = json.dumps(coder_output.files, indent=2)
        logger.info(
            "[test] Starting test generation | source_files=%d | spec_len=%d",
            len(coder_output.files),
            len(architect_json),
        )

        # ---- Build prompt & call LLM ---------------------------------------
        user_prompt = TEST_WRITER_USER_TEMPLATE.format(
            architect_json=architect_json,
            files_json=files_json,
        )

        raw_response = await self._call_llm(
            system_prompt=TEST_WRITER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=8000,
        )

        # ---- Parse response ------------------------------------------------
        output = self._parse_response(raw_response)

        # ---- Write test files to disk ---------------------------------------
        workspace = "/tmp/swarm_factory_workspace"
        write_results = write_files(output.test_files, base_path=workspace)

        failed_writes = [p for p, ok in write_results.items() if not ok]
        if failed_writes:
            logger.warning(
                "[test] %d test file(s) failed to write: %s",
                len(failed_writes),
                failed_writes,
            )

        # ---- Lint & auto-fix test files ------------------------------------
        for rel_path in output.test_files:
            if rel_path.endswith(".py"):
                abs_path = str(Path(workspace) / rel_path)
                clean = lint_and_fix(abs_path)
                if not clean:
                    logger.warning("[test] Unfixable lint issues in %s", rel_path)

        logger.info(
            "[test] Done | test_files=%d | coverage_target=%d%% | cmd=%s",
            len(output.test_files),
            output.coverage_target,
            output.test_command,
        )
        return output

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _unpack_input(self, input_data: Any) -> tuple[str, CoderOutput]:
        """
        Normalise the various accepted input shapes into (architect_json, CoderOutput).

        Args:
            input_data: See run() docstring for accepted shapes.

        Returns:
            Tuple of (architect_json_string, CoderOutput).
        """
        architect_json: str = "{}"

        # Tuple: (ArchitectOutput, CoderOutput)
        if isinstance(input_data, tuple) and len(input_data) == 2:
            arch, coder = input_data
            if isinstance(arch, ArchitectOutput):
                architect_json = arch.model_dump_json(indent=2)
            elif isinstance(arch, dict):
                architect_json = json.dumps(arch, indent=2)
            coder_output = coder if isinstance(coder, CoderOutput) else CoderOutput.model_validate(coder)
            return architect_json, coder_output

        # Dict: {"architect": ..., "coder": ...}
        if isinstance(input_data, dict) and "coder" in input_data:
            arch = input_data.get("architect")
            if isinstance(arch, ArchitectOutput):
                architect_json = arch.model_dump_json(indent=2)
            elif isinstance(arch, dict):
                architect_json = json.dumps(arch, indent=2)
            coder_raw = input_data["coder"]
            coder_output = coder_raw if isinstance(coder_raw, CoderOutput) else CoderOutput.model_validate(coder_raw)
            return architect_json, coder_output

        # Bare CoderOutput
        if isinstance(input_data, CoderOutput):
            return architect_json, input_data

        # Last resort: try Pydantic validation
        coder_output = CoderOutput.model_validate(input_data)
        return architect_json, coder_output

    def _parse_response(self, raw: str) -> TestOutput:
        """
        Parse the raw LLM response into a validated TestOutput.

        Falls back to a minimal TestOutput with the raw text stored in a
        single conftest.py if the response cannot be parsed as JSON.

        Args:
            raw: Raw string from the LLM, possibly with markdown fences.

        Returns:
            A validated TestOutput instance.
        """
        cleaned = self._parse_json(raw)

        try:
            parsed: dict = cleaned
        except json.JSONDecodeError:
            logger.warning(
                "[test] Response is not valid JSON — wrapping as bare conftest.py"
            )
            return TestOutput(
                test_files={"tests/conftest.py": raw},
                coverage_target=80,
                test_command="pytest tests/ --cov=. --cov-report=term-missing",
            )

        return TestOutput.model_validate(parsed)
