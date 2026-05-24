"""
tools/web_search.py
-------------------
Bing Search API wrapper for Swarm Factory.

Used by the DevOps agent to look up current best-practice examples for
Dockerfiles, CI/CD configs, and Azure deployment patterns.

Returns an empty list on any error — callers must not depend on results.

Usage:
    from tools.web_search import search
"""

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
_TIMEOUT = 10  # seconds


def search(query: str, count: int = 5) -> list[dict[str, str]]:
    """
    Search Bing for relevant results.

    Args:
        query: The search query string.
        count: Maximum number of results to return (1-50).

    Returns:
        List of result dicts, each with keys ``title``, ``url``, ``snippet``.
        Returns an empty list on any error — never raises.
    """
    api_key = os.environ.get("BING_SEARCH_API_KEY", "")
    if not api_key:
        logger.warning("BING_SEARCH_API_KEY not set — skipping web search")
        return []

    params: dict[str, Any] = {
        "q": query,
        "count": max(1, min(50, count)),
        "mkt": "en-US",
        "safeSearch": "Moderate",
    }
    headers = {"Ocp-Apim-Subscription-Key": api_key}

    try:
        logger.info("Calling Bing Search", extra={"query": query, "count": count})
        response = requests.get(
            _BING_ENDPOINT,
            headers=headers,
            params=params,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        results: list[dict[str, str]] = []
        for item in data.get("webPages", {}).get("value", []):
            results.append(
                {
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                }
            )

        logger.info(
            "Bing Search returned results",
            extra={"query": query, "result_count": len(results)},
        )
        return results

    except requests.exceptions.Timeout:
        logger.warning("Bing Search timed out", extra={"query": query})
        return []
    except requests.exceptions.HTTPError as exc:
        logger.warning(
            "Bing Search HTTP error",
            extra={"query": query, "status": exc.response.status_code},
        )
        return []
    except Exception as exc:
        logger.warning(
            "Bing Search unexpected error",
            extra={"query": query, "error": str(exc)},
        )
        return []
