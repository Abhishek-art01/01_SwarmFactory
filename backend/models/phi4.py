"""
models/phi4.py
--------------
Phi-4 wrapper for fast, low-complexity generation tasks in Swarm Factory.

Phi-4 is routed to by model_router for mid-complexity tasks (Dockerfiles,
CI/CD configs) where speed matters more than GPT-4o's reasoning depth.

Usage:
    from models.phi4 import Phi4Model
"""

import logging
import os
import time
from typing import Any

from openai import AzureOpenAI, APIStatusError, APIConnectionError, RateLimitError

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.5


class Phi4Error(Exception):
    """Raised when all retry attempts to the Phi-4 deployment fail."""


class Phi4Model:
    """
    Thin wrapper around the Azure-hosted Phi-4 chat completion endpoint.

    Shares the same Azure OpenAI client infrastructure as AzureOpenAIModel
    but targets the Phi-4 deployment and uses slightly different defaults
    suited to fast, deterministic generation.

    Attributes:
        deployment: Azure OpenAI deployment name for Phi-4.
        max_tokens: Maximum tokens per completion.
        temperature: Sampling temperature.
    """

    def __init__(
        self,
        deployment: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> None:
        """
        Initialise the Phi-4 wrapper.

        Args:
            deployment: Azure deployment name.  Defaults to env var
                ``AZURE_OPENAI_DEPLOYMENT_PHI4``.
            max_tokens: Token budget for completions.
            temperature: Sampling temperature (lower = more deterministic).
        """
        self.deployment: str = deployment or os.environ["AZURE_OPENAI_DEPLOYMENT_PHI4"]
        self.max_tokens = max_tokens
        self.temperature = temperature

        self._client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """
        Run a chat completion against the Phi-4 deployment.

        Retries up to ``_MAX_RETRIES`` times on transient errors.

        Args:
            system_prompt: The system message.
            user_prompt: The user message.

        Returns:
            The assistant's response text.

        Raises:
            Phi4Error: When all retry attempts fail.
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        delay = _RETRY_BASE_DELAY
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                logger.info(
                    "Calling Phi-4",
                    extra={"deployment": self.deployment, "attempt": attempt},
                )
                response = self._client.chat.completions.create(
                    model=self.deployment,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                content = response.choices[0].message.content or ""
                logger.info(
                    "Phi-4 response received",
                    extra={
                        "deployment": self.deployment,
                        "tokens": response.usage.total_tokens,
                    },
                )
                return content

            except RateLimitError as exc:
                logger.warning(
                    "Phi-4 rate limited",
                    extra={"attempt": attempt, "wait": delay},
                )
                last_exc = exc
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    logger.warning(
                        "Phi-4 server error",
                        extra={"status": exc.status_code, "attempt": attempt},
                    )
                    last_exc = exc
                else:
                    raise Phi4Error(
                        f"Phi-4 client error {exc.status_code}: {exc.message}"
                    ) from exc
            except APIConnectionError as exc:
                logger.warning(
                    "Phi-4 connection error",
                    extra={"attempt": attempt},
                )
                last_exc = exc

            if attempt < _MAX_RETRIES:
                time.sleep(delay)
                delay *= 2

        raise Phi4Error(
            f"Phi-4 deployment '{self.deployment}' failed after {_MAX_RETRIES} attempts"
        ) from last_exc
