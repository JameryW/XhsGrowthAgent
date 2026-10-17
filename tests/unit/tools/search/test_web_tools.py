"""Gateway tool wrappers for search.web / search.fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.services.web_search.models import FetchResponse, SearchHit, SearchResponse
from backend.tools.search.web import web_fetch, web_search


@pytest.mark.asyncio
async def test_web_search_tool_returns_dict() -> None:
    router = AsyncMock()
    router.search = AsyncMock(
        return_value=SearchResponse(
            results=[SearchHit(title="t", url="https://u", snippet="s", provider="deepseek")],
            provider="deepseek",
        )
    )
    with patch(
        "backend.services.web_search.get_web_search_router",
        return_value=router,
    ):
        out = await web_search.ainvoke({"query": "hello", "count": 3})
    assert out["provider"] == "deepseek"
    assert out["results"][0]["title"] == "t"
    router.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_web_fetch_tool_returns_dict() -> None:
    router = AsyncMock()
    router.fetch = AsyncMock(
        return_value=FetchResponse(
            title="Page",
            content="# Page",
            url="https://u",
            provider="tavily",
            fallback_used=True,
        )
    )
    with patch(
        "backend.services.web_search.get_web_search_router",
        return_value=router,
    ):
        out = await web_fetch.ainvoke({"url": "https://u"})
    assert out["fallback_used"] is True
    assert out["content"] == "# Page"
