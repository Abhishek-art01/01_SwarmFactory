"""
base_agent.py — Abstract base class for all Swarm Factory agents.

All 7 agents inherit from BaseAgent and must implement run().
Provides shared LLM call logic with retry, logging, and error handling.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from dotenv import load_dotenv
from openai import AsyncAzureOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

load_dotenv()

logger = logging.getLogger(__name__)


def clean_json(raw: str) -> str:
    """
    Strip markdown code fences from LLM output before JSON parsing.

    LLMs sometimes wrap JSON in ```json ... ``` blocks.
    This function removes those wrappers so json.loads() can parse cleanly.

    Args:
        raw: Raw string from LLM response.

    Returns:
        Cleaned string ready for json.loads().
    """
    raw = raw.strip()
    if raw.startswith("```"):
        # Split on ``` and take the inner block
        raw = raw.split("```")[1]
        # Strip the optional "json" language tag on the opening fence
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


class BaseAgent(ABC):
    """
    Abstract base class for all Swarm Factory agents.

    Provides:
    - Shared Azure OpenAI async client (initialized once per instance)
    - call_llm() with retry logic and structured logging
    - clean_json() utility exposed as a static method
    - Abstract run() that every subclass must implement

    Attributes:
        name: Human-readable agent identifier (set by subclass).
        model: Azure OpenAI deployment name to use for this agent.
    """

    name: str = "base"
    model: str = ""

    def __init__(self) -> None:
        """Initialize the Azure OpenAI async client from environment variables."""
        self._client = AsyncAzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
        # Default to the gpt-4o deployment unless subclass overrides self.model
        if not self.model:
            self.model = os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT4O", "gpt-4o")

    @abstractmethod
    async def run(self, input_data: Any) -> Any:
        """
        Execute the agent's core logic.

        Every agent must implement this method. It receives the output of the
        previous pipeline stage and returns a validated Pydantic model.

        Args:
            input_data: Output from the upstream agent (or raw user string for Agent 1).

        Returns:
            A validated Pydantic model specific to this agent's OutputSchema.
        """
        ...

    @retry(
        retry=retry_if_exception_type((json.JSONDecodeError, ValueError, KeyError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def call_llm(self, system_prompt: str, user_prompt: str, max_tokens: int = 2000) -> str:
        """
        Make an async Azure OpenAI chat completion call with retry logic.

        Retries up to 3 times on JSON parse errors, value errors, or key errors.
        Uses temperature=0.2 for consistent, structured JSON output.
        Logs the request at DEBUG level and any retry attempts at WARNING.

        Args:
            system_prompt: The ROLE + TASK + OUTPUT FORMAT instructions for the model.
            user_prompt:   The specific user request / context for this call.
            max_tokens:    Maximum tokens in the response (default 2000).

        Returns:
            Raw response content string from the model (may contain markdown fences).

        Raises:
            openai.APIError: On unrecoverable API-level failures.
            tenacity.RetryError: If all 3 retry attempts are exhausted.
        """
        logger.debug(
            "[%s] Calling LLM | model=%s | max_tokens=%d | system_len=%d | user_len=%d",
            self.name,
            self.model,
            max_tokens,
            len(system_prompt),
            len(user_prompt),
        )

        # Ask the model to respond with structured JSON output
        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=0.2,          # Low temperature for reliable JSON output
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )

        raw_content: str = response.choices[0].message.content or ""
        logger.debug("[%s] LLM response received | chars=%d", self.name, len(raw_content))
        return raw_content

    @staticmethod
    def clean_json(raw: str) -> str:
        """
        Static alias for the module-level clean_json utility.

        Exposed on the class so agents can call self.clean_json() without an import.

        Args:
            raw: Raw LLM output string, possibly wrapped in markdown fences.

        Returns:
            Clean JSON string ready for json.loads().
        """
        return clean_json(raw)
