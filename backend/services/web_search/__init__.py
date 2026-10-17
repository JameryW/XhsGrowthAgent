"""Web Search / Fetch facade — DeepSeek primary, Tavily fallback."""

from __future__ import annotations

from backend.services.web_search.deepseek import DeepSeekWebSearchProvider
from backend.services.web_search.models import (
    FetchResponse,
    SearchHit,
    SearchResponse,
    WebSearchError,
)
from backend.services.web_search.protocol import WebSearchProvider
from backend.services.web_search.router import (
    WebSearchRouter,
    get_web_search_router,
    provider_config_status,
    reset_web_search_router,
)
from backend.services.web_search.tavily import TavilyWebSearchProvider

__all__ = [
    "DeepSeekWebSearchProvider",
    "FetchResponse",
    "SearchHit",
    "SearchResponse",
    "TavilyWebSearchProvider",
    "WebSearchError",
    "WebSearchProvider",
    "WebSearchRouter",
    "get_web_search_router",
    "provider_config_status",
    "reset_web_search_router",
]
