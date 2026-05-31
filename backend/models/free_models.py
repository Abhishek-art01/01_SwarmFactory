"""
models/free_models.py
----------------------
5 free model wrappers used as fallback tiers 2 and 3.

HIERARCHY (in order of preference):
  TIER 1 — Azure OpenAI (PRIMARY — Microsoft stack — mandatory for hackathon)
    1. gpt-4o          (azure_openai.py)
    2. phi-4           (phi4.py)
    3. gpt-4o-mini     (azure_openai.py)

  TIER 2 — Free models (fallback when Azure quota exhausted)
    4. Groq / Llama-3.3-70b    → fastest free inference, great for code
    5. Groq / Mixtral-8x7b     → strong reasoning, good fallback
    6. Google Gemini 1.5 Flash → free tier, large context window
    7. Cohere Command-R        → free tier, strong for structured output
    8. Mistral via OpenRouter  → free tier, lightweight

  TIER 3 — Final resort
    9. Cached template output  → system NEVER crashes

FREE API KEYS (all no credit card needed):
  Groq:       https://console.groq.com/keys
  Gemini:     https://aistudio.google.com/apikey
  Cohere:     https://dashboard.cohere.com/api-keys
  OpenRouter: https://openrouter.ai/keys (for Mistral free)

All clients expose the SAME interface as Azure OpenAI:
  client.complete(system_prompt, user_prompt) -> str
So the fallback chain needs zero changes to use them.
"""

import os
import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

class FreeModelError(Exception):
    """Raised when a free model API call fails after retries."""


# ══════════════════════════════════════════════════════════════════════════════
# MODEL 4 — Groq / Llama-3.3-70b  (fastest free inference)
# ══════════════════════════════════════════════════════════════════════════════

class GroqLlamaModel:
    """
    Groq API — Llama 3.3 70B Versatile.

    Why Groq: runs inference on custom LPU chips — 10x faster than GPU.
    Free tier: 14,400 requests/day, 6,000 tokens/minute.
    Best for: code generation, structured JSON output.

    Get key: https://console.groq.com/keys
    Env var: GROQ_API_KEY
    """

    API_URL       = "https://api.groq.com/openai/v1/chat/completions"
    MODEL_NAME    = "llama-3.3-70b-versatile"
    PROVIDER_NAME = "groq-llama3.3-70b"

    def __init__(self) -> None:
        self.api_key = os.environ.get("GROQ_API_KEY", "")

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
    def complete(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.2, max_tokens: int = 2000) -> str:
        if not self.api_key:
            raise FreeModelError("GROQ_API_KEY not set")
        try:
            import httpx as _httpx
            r = _httpx.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={"model": self.MODEL_NAME,
                      "messages": [{"role": "system", "content": system_prompt},
                                   {"role": "user",   "content": user_prompt}],
                      "temperature": temperature, "max_tokens": max_tokens},
                timeout=60.0,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            raise FreeModelError(f"Groq Llama failed: {e}") from e


# ══════════════════════════════════════════════════════════════════════════════
# MODEL 5 — Groq / Mixtral-8x7b  (strong reasoning)
# ══════════════════════════════════════════════════════════════════════════════

class GroqMixtralModel:
    """
    Groq API — Mixtral 8x7B Instruct.

    Why Mixtral: Mixture-of-Experts model, strong at reasoning and structured output.
    Free tier: same as Groq Llama above.
    Best for: architecture decisions, complex planning tasks.

    Get key: https://console.groq.com/keys  (same key as Llama)
    Env var: GROQ_API_KEY
    """

    API_URL       = "https://api.groq.com/openai/v1/chat/completions"
    MODEL_NAME    = "mixtral-8x7b-32768"
    PROVIDER_NAME = "groq-mixtral-8x7b"

    def __init__(self) -> None:
        self.api_key = os.environ.get("GROQ_API_KEY", "")

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
    def complete(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.2, max_tokens: int = 2000) -> str:
        if not self.api_key:
            raise FreeModelError("GROQ_API_KEY not set")
        try:
            import httpx as _httpx
            r = _httpx.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={"model": self.MODEL_NAME,
                      "messages": [{"role": "system", "content": system_prompt},
                                   {"role": "user",   "content": user_prompt}],
                      "temperature": temperature, "max_tokens": max_tokens},
                timeout=60.0,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            raise FreeModelError(f"Groq Mixtral failed: {e}") from e


# ══════════════════════════════════════════════════════════════════════════════
# MODEL 6 — Google Gemini 1.5 Flash  (large context, free tier)
# ══════════════════════════════════════════════════════════════════════════════

class GeminiFlashModel:
    """
    Google Gemini 1.5 Flash.

    Why Gemini Flash: 1M token context window — great for large codebase review.
    Free tier: 15 requests/minute, 1 million tokens/day.
    Best for: reviewing large codebases, long-context tasks.

    Get key: https://aistudio.google.com/apikey
    Env var: GEMINI_API_KEY
    """

    API_URL       = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    PROVIDER_NAME = "google-gemini-1.5-flash"

    def __init__(self) -> None:
        self.api_key = os.environ.get("GEMINI_API_KEY", "")

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
    def complete(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.2, max_tokens: int = 2000) -> str:
        if not self.api_key:
            raise FreeModelError("GEMINI_API_KEY not set")
        try:
            import httpx as _httpx
            r = _httpx.post(
                self.API_URL,
                params={"key": self.api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "generationConfig": {"temperature": temperature,
                                        "maxOutputTokens": max_tokens},
                },
                timeout=60.0,
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            raise FreeModelError(f"Gemini Flash failed: {e}") from e


# ══════════════════════════════════════════════════════════════════════════════
# MODEL 7 — Cohere Command-R  (structured output specialist)
# ══════════════════════════════════════════════════════════════════════════════

class CohereCommandRModel:
    """
    Cohere Command-R.

    Why Cohere: trained specifically for RAG and structured output — very reliable JSON.
    Free tier: 1,000 API calls/month (enough for hackathon demo).
    Best for: code review, structured JSON generation, planner output.

    Get key: https://dashboard.cohere.com/api-keys
    Env var: COHERE_API_KEY
    """

    API_URL       = "https://api.cohere.com/v2/chat"
    PROVIDER_NAME = "cohere-command-r"

    def __init__(self) -> None:
        self.api_key = os.environ.get("COHERE_API_KEY", "")

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
    def complete(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.2, max_tokens: int = 2000) -> str:
        if not self.api_key:
            raise FreeModelError("COHERE_API_KEY not set")
        try:
            import httpx as _httpx
            r = _httpx.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={"model": "command-r",
                      "messages": [{"role": "system", "content": system_prompt},
                                   {"role": "user",   "content": user_prompt}],
                      "temperature": temperature,
                      "max_tokens": max_tokens},
                timeout=60.0,
            )
            r.raise_for_status()
            data = r.json()
            # Cohere v2 response format
            return data["message"]["content"][0]["text"]
        except Exception as e:
            raise FreeModelError(f"Cohere Command-R failed: {e}") from e


# ══════════════════════════════════════════════════════════════════════════════
# MODEL 8 — Mistral 7B via OpenRouter  (lightweight, always available)
# ══════════════════════════════════════════════════════════════════════════════

class MistralOpenRouterModel:
    """
    Mistral 7B Instruct via OpenRouter.

    Why OpenRouter: aggregates 100+ models, Mistral 7B has a free tier.
    Free tier: depends on model — Mistral 7B is free with rate limits.
    Best for: simple tasks, README generation, .gitignore, config files.

    Get key: https://openrouter.ai/keys
    Env var: OPENROUTER_API_KEY
    """

    API_URL       = "https://openrouter.ai/api/v1/chat/completions"
    MODEL_NAME    = "mistralai/mistral-7b-instruct:free"
    PROVIDER_NAME = "openrouter-mistral-7b"

    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
    def complete(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.2, max_tokens: int = 2000) -> str:
        if not self.api_key:
            raise FreeModelError("OPENROUTER_API_KEY not set")
        try:
            import httpx as _httpx
            r = _httpx.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json",
                         "HTTP-Referer": "https://github.com/swarm-factory",
                         "X-Title": "Swarm Factory"},
                json={"model": self.MODEL_NAME,
                      "messages": [{"role": "system", "content": system_prompt},
                                   {"role": "user",   "content": user_prompt}],
                      "temperature": temperature, "max_tokens": max_tokens},
                timeout=60.0,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            raise FreeModelError(f"Mistral OpenRouter failed: {e}") from e


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRY — easy access for model_router
# ══════════════════════════════════════════════════════════════════════════════

def get_free_model(name: str):
    """
    Factory function — returns the free model instance by name.

    Args:
        name: One of groq-llama, groq-mixtral, gemini-flash, cohere, mistral

    Returns:
        Model instance with a .complete(system, user) method
    """
    models = {
        "groq-llama":    GroqLlamaModel,
        "groq-mixtral":  GroqMixtralModel,
        "gemini-flash":  GeminiFlashModel,
        "cohere":        CohereCommandRModel,
        "mistral":       MistralOpenRouterModel,
    }
    if name not in models:
        raise ValueError(f"Unknown free model: {name}. Valid: {list(models.keys())}")
    return models[name]()


# Ordered fallback list — used by extended model_router
FREE_MODEL_FALLBACK_ORDER = [
    "groq-llama",    # fastest
    "groq-mixtral",  # strong reasoning
    "gemini-flash",  # large context
    "cohere",        # structured output
    "mistral",       # lightweight last resort
]
