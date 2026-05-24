"""
architect_agent.py — Agent 2: Architect Agent for Swarm Factory.

Receives a validated PlannerOutput and returns an ArchitectOutput with
the exact tech stack, folder structure, API contracts, pip/npm dependencies,
optional database schema, and runtime environment variables.

Importable as:
    from agents.architect_agent import ArchitectAgent, ArchitectOutput
"""

import json
import logging
from typing import Any

from pydantic import BaseModel

from agents.base_agent import BaseAgent
from agents.planner_agent import PlannerOutput
from prompts.architect import ARCHITECT_SYSTEM_PROMPT, ARCHITECT_USER_TEMPLATE
from prompts.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema — validated by Pydantic after every LLM response
# ---------------------------------------------------------------------------

class ApiContract(BaseModel):
    """
    Definition of a single API endpoint.

    Attributes:
        method:          HTTP method: "GET" | "POST" | "PUT" | "DELETE" | "PATCH".
        path:            URL path, e.g. "/todos/{id}".
        description:     Human-readable description of what this endpoint does.
        request_body:    JSON Schema-style dict describing the request body, or None.
        response_schema: JSON Schema-style dict describing the success response, or None.
    """
    method: str
    path: str
    description: str
    request_body: dict | None = None
    response_schema: dict | None = None


class ArchitectOutput(BaseModel):
    """
    Structured output returned by ArchitectAgent.run().

    Attributes:
        tech_stack:       Dict mapping component names to their chosen implementations,
                          e.g. {"language": "python 3.11", "framework": "fastapi 0.104.0"}.
        folder_structure: Nested dict representing the project file tree.
                          String leaves describe file purpose; nested dicts are directories.
        dependencies:     Pinned pip/npm install strings, e.g. ["fastapi==0.104.0"].
        api_contracts:    List of ApiContract objects for every endpoint.
        database_schema:  Optional dict of table/collection definitions, or None.
        env_vars_needed:  List of env var names the generated application will need at runtime.
    """
    tech_stack: dict[str, str]
    folder_structure: dict
    dependencies: list[str]
    api_contracts: list[ApiContract]
    database_schema: dict | None = None
    env_vars_needed: list[str]


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------

class ArchitectAgent(BaseAgent):
    """
    Agent 2 in the Swarm Factory pipeline.

    Accepts a PlannerOutput and produces a complete ArchitectOutput
    technical blueprint that the coder, tester, and devops agents will
    use to generate actual source files.

    LLM call uses:
        - temperature=0.2  (consistent structured output)
        - max_tokens=3000  (larger budget for detailed folder structure + API contracts)
        - up to 3 retries  (via BaseAgent.call_llm's tenacity decorator)
    """

    name: str = "architect"

    def __init__(self) -> None:
        """Initialise base class (sets up Azure OpenAI client) and prompt builder."""
        super().__init__()
        self._user_builder = PromptBuilder(template=ARCHITECT_USER_TEMPLATE)

    async def run(self, input_data: Any) -> ArchitectOutput:
        """
        Execute the architect agent on a PlannerOutput (or compatible dict/JSON string).

        Steps:
            1. Serialise the plan to JSON so the LLM has full context.
            2. Build the user prompt by injecting the plan JSON into the template.
            3. Call the LLM (with retry logic inherited from BaseAgent).
            4. Strip markdown fences from the response.
            5. Parse JSON and validate against ArchitectOutput with Pydantic.

        Args:
            input_data: A PlannerOutput instance, a dict, or a JSON string
                        representing the planning output.

        Returns:
            A validated ArchitectOutput instance.

        Raises:
            json.JSONDecodeError: If JSON parsing fails after 3 retries.
            pydantic.ValidationError: If the parsed JSON doesn't match ArchitectOutput schema.
        """
        # Normalise input to a JSON string the prompt can embed
        if isinstance(input_data, PlannerOutput):
            plan_json = input_data.model_dump_json(indent=2)
        elif isinstance(input_data, dict):
            plan_json = json.dumps(input_data, indent=2)
        else:
            # Assume it's already a JSON string or something str() handles
            plan_json = str(input_data)

        logger.info("[architect] Starting architecture design | plan_json_len=%d", len(plan_json))

        # Build the user-side prompt by injecting the serialised plan
        user_prompt = self._user_builder.build(plan_json=plan_json)

        # Ask GPT-4o to design the complete technical blueprint for this plan
        raw_response = await self.call_llm(
            system_prompt=ARCHITECT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=3000,   # Architect needs more room: folder tree + contracts + deps
        )

        # Strip any markdown code fences the model may have wrapped the JSON in
        cleaned = self.clean_json(raw_response)

        # Parse the raw string to a dict
        parsed_dict: dict = json.loads(cleaned)

        # Validate with Pydantic — enforces schema correctness before coder agent
        # consumes this output; catches missing fields or wrong types early
        output = ArchitectOutput.model_validate(parsed_dict)

        logger.info(
            "[architect] Done | tech_stack=%s | files_approx=%d | endpoints=%d | deps=%d",
            list(output.tech_stack.values())[:2],
            len(output.folder_structure),
            len(output.api_contracts),
            len(output.dependencies),
        )
        return output
