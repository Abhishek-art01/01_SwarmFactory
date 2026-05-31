"""
agents/base_agent.py
---------------------
Abstract base class for all 7 Swarm Factory agents.

MULTIMODEL DESIGN (Microsoft Azure stack):
  - Every agent call goes through model_router.py
  - model_router picks: gpt-4o | phi-4 | gpt-4o-mini based on task complexity
  - fallback_chain.py handles failures: gpt-4o → phi-4 → gpt-4o-mini → cache
  - All 3 models are Azure OpenAI deployments — 100% Microsoft stack
"""
import os
import json
import logging
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from openai import AsyncAzureOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

load_dotenv()
logger = logging.getLogger(__name__)


def _get_azure_client(deployment: str) -> AsyncAzureOpenAI:
    """
    Create an Azure OpenAI client for a specific model deployment.

    Args:
        deployment: The Azure deployment name (gpt-4o, phi-4, gpt-4o-mini)

    Returns:
        AsyncAzureOpenAI client pointed at the correct deployment
    """
    return AsyncAzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    )


class BaseAgent(ABC):
    """
    Abstract base for all 7 agents.

    Multimodel usage:
      self.model         = primary model for this agent (set per-agent)
      self._call_llm()   = makes the actual API call with retry
      fallback_chain     = handles model switching when primary fails

    Each agent sets self.model in their class body. The orchestrator's
    fallback_chain.py handles switching between models on failure.
    """

    # Subclasses set this to choose their primary model
    model: str = ""

    def __init__(self) -> None:
        """
        Initialize Azure OpenAI clients for all 3 models.
        All agents have access to all 3 models — model_router decides which to use.
        """
        # Primary model (set by subclass)
        primary = self.model or os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT4O", "gpt-4o")
        self.model = primary

        # Three clients — one per Azure deployment
        # model_router and fallback_chain use these to switch models
        self._client_gpt4o     = _get_azure_client(os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT4O", "gpt-4o"))
        self._client_phi4      = _get_azure_client(os.environ.get("AZURE_OPENAI_DEPLOYMENT_PHI4", "phi-4"))
        self._client_mini      = _get_azure_client(os.environ.get("AZURE_OPENAI_DEPLOYMENT_MINI", "gpt-4o-mini"))

        # Default client = primary model
        self._client = self._client_gpt4o

        logger.info("Agent initialized | agent=%s | model=%s", self.__class__.__name__, self.model)

    @abstractmethod
    async def run(self, input_data) -> object:
        """Every agent must implement this. Input and output types vary per agent."""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        model_override: str = "",
    ) -> str:
        """
        Make an Azure OpenAI API call with automatic retry.

        Uses the agent's primary model by default.
        fallback_chain.py calls this with model_override to switch models.

        Args:
            system_prompt:  The system instruction for GPT
            user_prompt:    The user message / task description
            temperature:    0.2 = consistent/structured, 0.7 = creative
            max_tokens:     Max tokens in response
            model_override: Force a specific model (used by fallback chain)

        Returns:
            Raw string response from the model
        """
        # Pick the right client based on model
        use_model = model_override or self.model
        if use_model == os.environ.get("AZURE_OPENAI_DEPLOYMENT_PHI4", "phi-4"):
            client = self._client_phi4
        elif use_model == os.environ.get("AZURE_OPENAI_DEPLOYMENT_MINI", "gpt-4o-mini"):
            client = self._client_mini
        else:
            client = self._client_gpt4o

        logger.debug("LLM call | agent=%s | model=%s", self.__class__.__name__, use_model)

        response = await client.chat.completions.create(
            model=use_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content
        logger.debug("LLM response | agent=%s | chars=%d", self.__class__.__name__, len(content))
        return content

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """
        Safely parse JSON from LLM output.
        LLMs sometimes wrap JSON in ```json ... ``` markdown — this strips it.

        Args:
            raw: Raw string from LLM

        Returns:
            Parsed dict

        Raises:
            ValueError: If JSON cannot be parsed after cleaning
        """
        cleaned = raw.strip()

        # Strip markdown code fences if present
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json or ```) and last line (```)
            cleaned = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse LLM JSON output: {exc}\nRaw: {raw[:200]}") from exc
