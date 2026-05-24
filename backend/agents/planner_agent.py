"""
planner_agent.py — Agent 1: Planner Agent for Swarm Factory.

Receives a plain-English software requirement string and returns a
PlannerOutput with a classified task type, complexity score, language/
framework choice, and a dependency-ordered task graph.

Importable as:
    from agents.planner_agent import PlannerAgent, PlannerOutput
"""

import json
import logging
from typing import Any

from pydantic import BaseModel

from agents.base_agent import BaseAgent
from prompts.planner import PLANNER_SYSTEM_PROMPT, PLANNER_USER_TEMPLATE
from prompts.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema — validated by Pydantic after every LLM response
# ---------------------------------------------------------------------------

class Task(BaseModel):
    """
    A single atomic unit of work in the project task graph.

    Attributes:
        id:         Unique sequential identifier, e.g. "t1", "t2".
        name:       Short imperative description of what to do.
        agent:      Which downstream agent owns this task: "coder" | "tester" | "devops".
        depends_on: List of task IDs that must complete before this one starts.
        priority:   Execution priority; 1 is highest.
    """
    id: str
    name: str
    agent: str
    depends_on: list[str]
    priority: int


class PlannerOutput(BaseModel):
    """
    Structured output returned by PlannerAgent.run().

    Attributes:
        task_type:  Project category: "api" | "frontend" | "cli" | "fullstack" | "library".
        complexity: Estimated complexity score from 1 (trivial) to 10 (enterprise).
        language:   Primary programming language, e.g. "python", "typescript".
        framework:  Primary framework, e.g. "fastapi", "react", "gin".
        tasks:      Ordered list of Task objects forming the task graph.
        summary:    One-sentence description of what will be built.
    """
    task_type: str
    complexity: int
    language: str
    framework: str
    tasks: list[Task]
    summary: str


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------

class PlannerAgent(BaseAgent):
    """
    Agent 1 in the Swarm Factory pipeline.

    Classifies the user's requirement into a project type, scores complexity,
    selects language/framework, and decomposes the work into a dependency-
    ordered task graph.

    LLM call uses:
        - temperature=0.2  (consistent structured output)
        - max_tokens=2000  (sufficient for 5-10 tasks with metadata)
        - up to 3 retries  (via BaseAgent.call_llm's tenacity decorator)
    """

    name: str = "planner"

    def __init__(self) -> None:
        """Initialise base class (sets up Azure OpenAI client) and prompt builder."""
        super().__init__()
        self._user_builder = PromptBuilder(template=PLANNER_USER_TEMPLATE)

    async def run(self, input_data: Any) -> PlannerOutput:
        """
        Execute the planner agent on a plain-English requirement string.

        Steps:
            1. Build the user prompt by injecting the requirement into the template.
            2. Call the LLM (with retry logic inherited from BaseAgent).
            3. Strip markdown fences from the response.
            4. Parse JSON and validate against PlannerOutput with Pydantic.

        Args:
            input_data: A plain-English string describing what should be built.

        Returns:
            A validated PlannerOutput instance.

        Raises:
            json.JSONDecodeError: If JSON parsing fails after 3 retries.
            pydantic.ValidationError: If the parsed JSON doesn't match PlannerOutput schema.
        """
        requirement: str = str(input_data).strip()
        logger.info("[planner] Starting planning for requirement (%d chars)", len(requirement))

        # Build the user-side prompt by injecting the requirement
        user_prompt = self._user_builder.build(requirement=requirement)

        # Ask GPT-4o to classify the requirement and produce a task graph
        raw_response = await self.call_llm(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=2000,
        )

        # Strip any markdown code fences the model may have wrapped the JSON in
        cleaned = self.clean_json(raw_response)

        # Parse the raw string to a dict
        parsed_dict: dict = json.loads(cleaned)

        # Validate with Pydantic — ensures all required fields are present and typed
        # correctly before any downstream agent attempts to consume this output
        output = PlannerOutput.model_validate(parsed_dict)

        logger.info(
            "[planner] Done | task_type=%s | complexity=%d | tasks=%d",
            output.task_type,
            output.complexity,
            len(output.tasks),
        )
        return output
