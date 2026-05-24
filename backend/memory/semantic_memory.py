"""
memory/semantic_memory.py
--------------------------
Semantic Kernel memory plugin for Swarm Factory.

Wraps Azure AI Search as a Semantic Kernel memory store so agents can
query past builds using natural language via SK's memory abstraction layer.

Usage:
    from memory.semantic_memory import SemanticMemoryPlugin, build_kernel
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ── Kernel factory ────────────────────────────────────────────────────────────

def build_kernel() -> Any:
    """
    Construct and return a configured Semantic Kernel instance.

    Attaches:
    - Azure OpenAI chat completion service (gpt-4o deployment)
    - Azure OpenAI text embedding service (ada-002 deployment)
    - Azure AI Search as the vector memory store (if configured)

    Falls back gracefully if semantic-kernel is not installed or Azure
    Search environment variables are absent.

    Returns:
        A ``semantic_kernel.Kernel`` instance, or None if SK is unavailable.
    """
    try:
        import semantic_kernel as sk
        from semantic_kernel.connectors.ai.open_ai import (
            AzureChatCompletion,
            AzureTextEmbedding,
        )

        kernel = sk.Kernel()

        # ── Chat completion service ──────────────────────────────────────────
        kernel.add_service(
            AzureChatCompletion(
                service_id="chat",
                deployment_name=os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT4O", "gpt-4o"),
                endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            )
        )

        # ── Text embedding service ────────────────────────────────────────────
        embed_deployment = os.environ.get(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002"
        )
        kernel.add_service(
            AzureTextEmbedding(
                service_id="embedding",
                deployment_name=embed_deployment,
                endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            )
        )

        logger.debug("[semantic_memory] Semantic Kernel built with chat + embedding services")
        return kernel

    except ImportError:
        logger.warning(
            "[semantic_memory] semantic-kernel not installed — SK features disabled"
        )
        return None
    except KeyError as exc:
        logger.warning(
            "[semantic_memory] Missing env var for Semantic Kernel | var=%s", exc
        )
        return None
    except Exception as exc:
        logger.error("[semantic_memory] Failed to build kernel | error=%s", exc)
        return None


# ── Memory plugin ─────────────────────────────────────────────────────────────

class SemanticMemoryPlugin:
    """
    Semantic Kernel plugin that exposes past build context as SK memory functions.

    Registers two kernel functions:
      - remember(job_id, requirement, tech_stack): Store a build in memory.
      - recall(query, max_results): Retrieve similar past builds.

    Falls back to a no-op if Semantic Kernel or Azure Search is unavailable.

    Attributes:
        kernel: The underlying SK Kernel instance (may be None in fallback mode).
        _collection: The memory collection name used in Azure AI Search.
    """

    _collection: str = "swarm-factory-sessions"

    def __init__(self) -> None:
        """Initialise the kernel and register this plugin."""
        self.kernel = build_kernel()
        self._memory_store: Any = None

        if self.kernel is not None:
            self._try_attach_memory()

    def _try_attach_memory(self) -> None:
        """
        Attempt to attach Azure AI Search as the SK vector memory store.

        Silently degrades if azure-search-documents is missing or unconfigured.
        """
        try:
            from semantic_kernel.connectors.memory.azure_ai_search import (
                AzureAISearchMemoryStore,
            )

            store = AzureAISearchMemoryStore(
                vector_size=1536,
                search_endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
                admin_key=os.environ["AZURE_SEARCH_API_KEY"],
            )
            self._memory_store = store
            logger.debug("[semantic_memory] Azure AI Search memory store attached")
        except (ImportError, KeyError, Exception) as exc:
            logger.warning(
                "[semantic_memory] Memory store not available | error=%s", exc
            )

    async def remember(self, job_id: str, requirement: str, tech_stack: dict) -> bool:
        """
        Store a completed build in Semantic Kernel memory.

        Args:
            job_id:       Unique job identifier.
            requirement:  The original user requirement string.
            tech_stack:   Dict of technology choices.

        Returns:
            True if saved successfully, False otherwise.
        """
        if self.kernel is None or self._memory_store is None:
            logger.debug("[semantic_memory] remember() skipped — no memory store")
            return False

        try:
            import json
            text = f"Requirement: {requirement}\nTech stack: {json.dumps(tech_stack)}"
            await self.kernel.memory.save_information(
                collection=self._collection,
                id=job_id,
                text=text,
            )
            logger.debug("[semantic_memory] Remembered | job_id=%s", job_id)
            return True
        except Exception as exc:
            logger.warning("[semantic_memory] remember() failed | error=%s", exc)
            return False

    async def recall(self, query: str, max_results: int = 3) -> list[dict]:
        """
        Retrieve past builds semantically similar to ``query``.

        Args:
            query:       Natural language query (usually the current requirement).
            max_results: Maximum number of results to return.

        Returns:
            List of dicts with keys: job_id, requirement, tech_stack.
            Empty list if memory store is unavailable or no results found.
        """
        if self.kernel is None or self._memory_store is None:
            return []

        try:
            results = await self.kernel.memory.search(
                collection=self._collection,
                query=query,
                limit=max_results,
                min_relevance_score=0.6,
            )
            parsed: list[dict] = []
            for r in results:
                # Parse the stored text back into structured fields
                lines = r.text.split("\n") if r.text else []
                requirement_line = next(
                    (l.replace("Requirement: ", "") for l in lines if l.startswith("Requirement:")),
                    "",
                )
                parsed.append(
                    {
                        "job_id": r.id,
                        "requirement": requirement_line,
                        "tech_stack": {},
                        "relevance": r.relevance,
                    }
                )
            return parsed
        except Exception as exc:
            logger.warning("[semantic_memory] recall() failed | error=%s", exc)
            return []
