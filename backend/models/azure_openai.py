"""
models/azure_openai.py
----------------------
GPT-4o wrapper with retry logic and exponential back-off for Swarm Factory.

Handles transient Azure OpenAI errors (rate limits, 5xx) automatically.
Falls back to gpt-4o-mini when the primary deployment is unavailable.

Usage:
    from models.azure_openai import AzureOpenAIModel
"""

import logging
import os
import time
from typing import Any

from openai import AzureOpenAI, APIStatusError, APIConnectionError, RateLimitError

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds, doubles on each retry


class AzureOpenAIError(Exception):
    """Raised when all retry attempts to Azure OpenAI fail."""


class AzureOpenAIModel:
    """
    Thin wrapper around the Azure OpenAI chat completion API.

    Automatically retries on rate-limit and transient server errors with
    exponential back-off.  Falls back to the mini deployment if the primary
    GPT-4o deployment fails on every attempt.

    Attributes:
        deployment: Azure OpenAI deployment name to use as primary.
        fallback_deployment: Deployment name used if primary exhausts retries.
        max_tokens: Maximum tokens for each completion.
        temperature: Sampling temperature (0 = deterministic).
    """

    def __init__(
        self,
        deployment: str | None = None,
        fallback_deployment: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> None:
        """
        Initialise the wrapper.

        Args:
            deployment: Azure deployment name.  Defaults to env var
                ``AZURE_OPENAI_DEPLOYMENT_GPT4O``.
            fallback_deployment: Deployment tried when primary fails.  Defaults
                to env var ``AZURE_OPENAI_DEPLOYMENT_MINI``.
            max_tokens: Token budget for completions.
            temperature: Sampling temperature.
        """
        self.deployment: str = deployment or os.environ["AZURE_OPENAI_DEPLOYMENT_GPT4O"]
        self.fallback_deployment: str = (
            fallback_deployment or os.environ["AZURE_OPENAI_DEPLOYMENT_MINI"]
        )
        self.max_tokens = max_tokens
        self.temperature = temperature

        self._client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        deployment_override: str | None = None,
    ) -> str:
        """
        Run a chat completion with retry + fallback.

        Args:
            system_prompt: The system message.
            user_prompt: The user message.
            deployment_override: Optional deployment name to use instead of
                ``self.deployment``.

        Returns:
            The assistant's response text.

        Raises:
            AzureOpenAIError: When all attempts (including fallback) fail.
        """
        primary = deployment_override or self.deployment
        for attempt, deployment in enumerate([primary, self.fallback_deployment], start=1):
            result = self._attempt_with_retries(system_prompt, user_prompt, deployment)
            if result is not None:
                return result
            logger.warning(
                "Deployment exhausted retries",
                extra={"deployment": deployment, "attempt": attempt},
            )

        raise AzureOpenAIError(
            f"All deployments failed: primary={primary}, "
            f"fallback={self.fallback_deployment}"
        )

    # ── internals ─────────────────────────────────────────────────────────────

    def _attempt_with_retries(
        self,
        system_prompt: str,
        user_prompt: str,
        deployment: str,
    ) -> str | None:
        """
        Try a single deployment up to ``_MAX_RETRIES`` times.

        Returns the response text on success, or None if all retries fail.
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        delay = _RETRY_BASE_DELAY
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                logger.info(
                    "Calling Azure OpenAI",
                    extra={"deployment": deployment, "attempt": attempt},
                )
                response = self._client.chat.completions.create(
                    model=deployment,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                content = response.choices[0].message.content or ""
                logger.info(
                    "Azure OpenAI response received",
                    extra={"deployment": deployment, "tokens": response.usage.total_tokens},
                )
                return content

            except RateLimitError:
                logger.warning(
                    "Rate limited by Azure OpenAI",
                    extra={"deployment": deployment, "attempt": attempt, "wait": delay},
                )
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    logger.warning(
                        "Azure OpenAI server error",
                        extra={"deployment": deployment, "status": exc.status_code},
                    )
                else:
                    # 4xx errors won't recover with retries
                    logger.error(
                        "Azure OpenAI client error — not retrying",
                        extra={"deployment": deployment, "status": exc.status_code},
                    )
                    return None
            except APIConnectionError:
                logger.warning(
                    "Azure OpenAI connection error",
                    extra={"deployment": deployment, "attempt": attempt},
                )

            if attempt < _MAX_RETRIES:
                time.sleep(delay)
                delay *= 2

        return None
