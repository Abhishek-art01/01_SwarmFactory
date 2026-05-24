"""
coder_agent.py — Agent 3: Coder Agent for Swarm Factory.

Receives a validated ArchitectOutput and returns a CoderOutput containing
the complete source code for every file in the project, along with pinned
dependencies, the entry-point file, and the start command.

Importable as:
    from agents.coder_agent import CoderAgent, CoderOutput
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agents.base_agent import BaseAgent
from agents.architect_agent import ArchitectOutput
from prompts.coder import CODER_SYSTEM_PROMPT, CODER_USER_TEMPLATE
from tools.file_writer import write_files
from tools.linter import lint_and_fix

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class CoderOutput(BaseModel):
    """
    Structured output returned by CoderAgent.run().

    Attributes:
        files:         Mapping of relative file paths to their complete content.
                       Example: {"main.py": "from fastapi import FastAPI\\n..."}
        dependencies:  Pinned pip install strings consumed by devops agent.
                       Example: ["fastapi==0.104.0", "sqlalchemy==2.0.0"]
        entry_point:   Relative path to the main runnable file, e.g. "main.py".
        start_command: Shell command to start the application, e.g.
                       "uvicorn main:app --host 0.0.0.0 --port 8000".
    """

    files: dict[str, str]
    dependencies: list[str]
    entry_point: str
    start_command: str


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------

class CoderAgent(BaseAgent):
    """
    Agent 3 in the Swarm Factory pipeline.

    Accepts an ArchitectOutput and produces complete, runnable source code
    for every file defined in the architect's folder structure.

    After receiving the LLM response the agent:
    1. Parses and validates the JSON with Pydantic.
    2. Writes every file atomically via file_writer.
    3. Runs ruff auto-fix (lint_and_fix) on every Python file.

    LLM call uses:
        - temperature=0.2  (consistent, deterministic code output)
        - max_tokens=8000  (large budget for multi-file code generation)
        - up to 3 retries  (via BaseAgent.call_llm's tenacity decorator)
    """

    name: str = "coder"

    def __init__(self) -> None:
        """Initialise base class (sets up Azure OpenAI client)."""
        super().__init__()

    async def run(self, input_data: Any) -> CoderOutput:
        """
        Execute the coder agent on an ArchitectOutput (or compatible input).

        Steps:
            1. Serialise the architect spec to JSON for the LLM prompt.
            2. Call the LLM with retry logic.
            3. Strip markdown fences, then attempt JSON parse.
            4. Validate the parsed data against CoderOutput with Pydantic.
            5. Write all files atomically to disk.
            6. Run ruff --fix on every generated Python file.

        Args:
            input_data: An ArchitectOutput instance, a dict, or a JSON string
                        representing the architect's blueprint.

        Returns:
            A validated CoderOutput instance with all generated source files.

        Raises:
            json.JSONDecodeError: If JSON parsing fails after 3 retries.
            pydantic.ValidationError: If the parsed JSON doesn't match CoderOutput.
        """
        # ---- Normalise input -----------------------------------------------
        if isinstance(input_data, ArchitectOutput):
            architect_json = input_data.model_dump_json(indent=2)
        elif isinstance(input_data, dict):
            architect_json = json.dumps(input_data, indent=2)
        else:
            architect_json = str(input_data)

        logger.info(
            "[coder] Starting code generation | spec_len=%d chars", len(architect_json)
        )

        # ---- Build prompt & call LLM ---------------------------------------
        user_prompt = CODER_USER_TEMPLATE.format(architect_json=architect_json)

        raw_response = await self.call_llm(
            system_prompt=CODER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=8000,
        )

        # ---- Parse response ------------------------------------------------
        output = self._parse_response(raw_response)

        # ---- Write files to disk -------------------------------------------
        # Use a temp workspace under /tmp so downstream agents and tests can
        # inspect the generated files without polluting the repo working tree.
        workspace = "/tmp/swarm_factory_workspace"
        write_results = write_files(output.files, base_path=workspace)

        failed_writes = [p for p, ok in write_results.items() if not ok]
        if failed_writes:
            logger.warning("[coder] %d file(s) failed to write: %s", len(failed_writes), failed_writes)

        # ---- Lint & auto-fix Python files ----------------------------------
        for rel_path in output.files:
            if rel_path.endswith(".py"):
                abs_path = str(Path(workspace) / rel_path)
                clean = lint_and_fix(abs_path)
                if not clean:
                    logger.warning("[coder] Unfixable lint issues in %s", rel_path)

        logger.info(
            "[coder] Done | files=%d | entry=%s | deps=%d",
            len(output.files),
            output.entry_point,
            len(output.dependencies),
        )
        return output

    def _parse_response(self, raw: str) -> CoderOutput:
        """
        Parse the raw LLM response into a validated CoderOutput.

        Handles two cases:
        - The model returned a JSON object with a ``files`` key → normal path.
        - The model returned bare code (not JSON) → treat the entire response
          as the content of a single ``main.py`` file.

        Args:
            raw: Raw string from the LLM, possibly with markdown fences.

        Returns:
            A validated CoderOutput instance.

        Raises:
            json.JSONDecodeError: If the response looks like JSON but can't be parsed.
            pydantic.ValidationError: If the parsed JSON doesn't match CoderOutput.
        """
        cleaned = self.clean_json(raw)

        # Try to parse as JSON first
        try:
            parsed: dict = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback: treat entire response as a single file's content
            logger.warning(
                "[coder] Response is not JSON — treating as bare code for main.py"
            )
            return CoderOutput(
                files={"main.py": raw},
                dependencies=[],
                entry_point="main.py",
                start_command="python main.py",
            )

        # Validate with Pydantic
        return CoderOutput.model_validate(parsed)
