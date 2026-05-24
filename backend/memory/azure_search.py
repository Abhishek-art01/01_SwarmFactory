"""
memory/azure_search.py
----------------------
Azure AI Search integration for Swarm Factory memory system.

Provides vector-based similarity search over past build sessions.
All public functions return empty results / False on connection error so the
rest of the system continues working even when Azure Search is unavailable.

Usage:
    from memory.azure_search import search_similar, upsert_document
"""

import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Lazy client singleton ─────────────────────────────────────────────────────
_search_client: Any = None
_embed_client: Any = None


def _get_search_client() -> Any:
    """
    Return a cached Azure SearchClient, creating it on first call.

    Returns:
        azure.search.documents.SearchClient instance.

    Raises:
        ImportError:  If azure-search-documents is not installed.
        KeyError:     If required environment variables are missing.
        Exception:    On any Azure SDK initialisation failure.
    """
    global _search_client
    if _search_client is not None:
        return _search_client

    from azure.search.documents import SearchClient
    from azure.core.credentials import AzureKeyCredential

    endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
    api_key = os.environ["AZURE_SEARCH_API_KEY"]
    index_name = os.environ["AZURE_SEARCH_INDEX_NAME"]

    _search_client = SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(api_key),
    )
    logger.debug("[azure_search] SearchClient initialised | index=%s", index_name)
    return _search_client


def _get_embed_client() -> Any:
    """
    Return a cached AsyncAzureOpenAI client for generating embeddings.

    Returns:
        openai.AzureOpenAI instance.

    Raises:
        ImportError: If openai is not installed.
        KeyError:    If required env vars are missing.
    """
    global _embed_client
    if _embed_client is not None:
        return _embed_client

    from openai import AzureOpenAI

    _embed_client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    )
    logger.debug("[azure_search] Embedding client initialised")
    return _embed_client


def _embed(text: str) -> list[float]:
    """
    Generate a text embedding vector using Azure OpenAI.

    Falls back to a deterministic SHA-256-based pseudo-vector if the
    embedding call fails, so callers always receive a usable vector.

    Args:
        text: Input text to embed.

    Returns:
        List of floats representing the embedding vector.
    """
    try:
        client = _get_embed_client()
        deployment = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002")
        response = client.embeddings.create(input=[text], model=deployment)
        return response.data[0].embedding
    except Exception as exc:
        logger.warning("[azure_search] Embedding generation failed | error=%s", exc)
        # Deterministic fallback: hash the text into a 1536-dim pseudo-vector.
        digest = hashlib.sha256(text.encode()).digest()
        # Repeat digest bytes to fill 1536 floats, normalised to [0, 1]
        repeated = (digest * (1536 // len(digest) + 1))[:1536]
        return [b / 255.0 for b in repeated]


def _doc_id(job_id: str) -> str:
    """Return a safe Azure Search document key derived from job_id."""
    return job_id.replace("-", "")


# ── Public API ────────────────────────────────────────────────────────────────

def search_similar(requirement: str, top_k: int = 3) -> list[dict]:
    """
    Search the Azure AI Search index for past sessions similar to ``requirement``.

    Performs a hybrid keyword + vector search. Falls back gracefully on any
    connection or SDK error — callers should treat an empty list as "no results".

    Args:
        requirement: The current user requirement string to match against.
        top_k:       Maximum number of results to return.

    Returns:
        List of dicts with keys: job_id, requirement, tech_stack.
        Returns [] on any error.
    """
    if not requirement or not requirement.strip():
        return []

    try:
        client = _get_search_client()

        # Try vector search first; fall back to plain keyword search
        # if the index doesn't have a vector field configured.
        try:
            from azure.search.documents.models import VectorizedQuery

            vector = _embed(requirement)
            vector_query = VectorizedQuery(
                vector=vector,
                k_nearest_neighbors=top_k,
                fields="requirement_vector",
            )
            results = client.search(
                search_text=requirement,
                vector_queries=[vector_query],
                top=top_k,
                select=["job_id", "requirement", "tech_stack"],
            )
        except Exception:
            # Plain keyword search as fallback
            results = client.search(
                search_text=requirement,
                top=top_k,
                select=["job_id", "requirement", "tech_stack"],
            )

        entries: list[dict] = []
        for result in results:
            tech_stack = result.get("tech_stack", {})
            if isinstance(tech_stack, str):
                try:
                    tech_stack = json.loads(tech_stack)
                except Exception:
                    tech_stack = {"raw": tech_stack}
            entries.append(
                {
                    "job_id": result.get("job_id", ""),
                    "requirement": result.get("requirement", ""),
                    "tech_stack": tech_stack,
                }
            )

        logger.debug("[azure_search] search_similar | query_len=%d | results=%d", len(requirement), len(entries))
        return entries

    except Exception as exc:
        logger.warning("[azure_search] search_similar failed | error=%s", exc)
        return []


def upsert_document(job_id: str, requirement: str, tech_stack: dict) -> bool:
    """
    Insert or update a session document in the Azure AI Search index.

    Generates a vector embedding for the requirement text and stores it
    alongside the structured metadata for future similarity searches.

    Args:
        job_id:      Unique job identifier — used as the document key.
        requirement: The original user requirement string.
        tech_stack:  Dict of technology choices made during the pipeline.

    Returns:
        True on success, False on any error.
    """
    try:
        client = _get_search_client()
        vector = _embed(requirement)

        document = {
            "id": _doc_id(job_id),
            "job_id": job_id,
            "requirement": requirement,
            "tech_stack": json.dumps(tech_stack),
            "requirement_vector": vector,
        }

        client.upload_documents(documents=[document])
        logger.debug("[azure_search] upsert_document | job_id=%s", job_id)
        return True

    except Exception as exc:
        logger.warning("[azure_search] upsert_document failed | job_id=%s | error=%s", job_id, exc)
        return False


def delete_document(job_id: str) -> bool:
    """
    Delete a session document from the Azure AI Search index.

    Args:
        job_id: Unique job identifier of the document to remove.

    Returns:
        True on success or if document didn't exist, False on error.
    """
    try:
        client = _get_search_client()
        client.delete_documents(documents=[{"id": _doc_id(job_id)}])
        logger.debug("[azure_search] delete_document | job_id=%s", job_id)
        return True
    except Exception as exc:
        logger.warning("[azure_search] delete_document failed | job_id=%s | error=%s", job_id, exc)
        return False


def ensure_index_exists() -> bool:
    """
    Create the Azure AI Search index if it does not already exist.

    This is a best-effort setup helper. The index schema includes:
      - id (key), job_id, requirement, tech_stack (keyword fields)
      - requirement_vector (vector field, 1536 dims for ada-002)

    Returns:
        True if the index exists or was created. False on any error.
    """
    try:
        from azure.search.documents.indexes import SearchIndexClient
        from azure.search.documents.indexes.models import (
            SearchIndex,
            SimpleField,
            SearchableField,
            SearchFieldDataType,
            VectorSearch,
            HnswAlgorithmConfiguration,
            VectorSearchProfile,
            SearchField,
        )
        from azure.core.credentials import AzureKeyCredential

        endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
        api_key = os.environ["AZURE_SEARCH_API_KEY"]
        index_name = os.environ["AZURE_SEARCH_INDEX_NAME"]

        index_client = SearchIndexClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key),
        )

        # Check if index already exists
        existing = [idx.name for idx in index_client.list_indexes()]
        if index_name in existing:
            logger.debug("[azure_search] Index already exists | name=%s", index_name)
            return True

        # Define the index schema
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="job_id", type=SearchFieldDataType.String, filterable=True),
            SearchableField(name="requirement", type=SearchFieldDataType.String),
            SimpleField(name="tech_stack", type=SearchFieldDataType.String),
            SearchField(
                name="requirement_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=1536,
                vector_search_profile_name="default-profile",
            ),
        ]

        vector_search = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="default-hnsw")],
            profiles=[
                VectorSearchProfile(
                    name="default-profile",
                    algorithm_configuration_name="default-hnsw",
                )
            ],
        )

        index = SearchIndex(name=index_name, fields=fields, vector_search=vector_search)
        index_client.create_index(index)
        logger.info("[azure_search] Created index | name=%s", index_name)
        return True

    except Exception as exc:
        logger.warning("[azure_search] ensure_index_exists failed | error=%s", exc)
        return False
