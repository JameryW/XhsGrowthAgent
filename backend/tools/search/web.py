"""Gateway tools: ``search.web`` and ``search.fetch`` via the web_search facade."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger("xhs_growth.tools.search")


@tool
async def web_search(
    query: str,
    count: int = 10,
    need_content: bool = False,
    ori_question: str = "",
) -> dict[str, Any]:
    """Search the open web (DeepSeek Search, Tavily fallback).

    Args:
        query: Search query (1–128 chars recommended for DeepSeek).
        count: Max results (1–50 DeepSeek / 1–20 Tavily).
        need_content: When True, request fuller page text when the provider supports it.
        ori_question: Optional original user question for intent (DeepSeek only).

    Returns:
        Normalized ``{results, provider, fallback_used, error}`` dict. Empty
        ``results`` with ``error`` set means both providers failed or none
        configured — callers should degrade, not abort.
    """
    from backend.services.web_search import get_web_search_router

    router = get_web_search_router()
    response = await router.search(
        query,
        count=count,
        need_content=need_content,
        ori_question=ori_question or None,
    )
    if response.error and not response.results:
        logger.warning(f"web_search degraded: {response.error}")
    return response.to_dict()


@tool
async def web_fetch(url: str) -> dict[str, Any]:
    """Fetch one URL as Markdown (DeepSeek Fetch, Tavily Extract fallback).

    Args:
        url: Absolute HTTP/HTTPS URL to fetch.

    Returns:
        Normalized ``{title, content, url, provider, fallback_used, error}``.
        On failure ``content`` is empty and ``error`` is set — callers degrade.
    """
    from backend.services.web_search import get_web_search_router

    router = get_web_search_router()
    response = await router.fetch(url)
    if response.error and not response.content:
        logger.warning(f"web_fetch degraded: {response.error}")
    return response.to_dict()
