"""Unit tests for Tavily Search/Extract mapped onto unified models."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.services.web_search.models import WebSearchError
from backend.services.web_search.tavily import TavilyWebSearchProvider


def _response(status: int, payload: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = ""
    return resp


class TestTavilySearch:
    @pytest.mark.asyncio
    async def test_maps_search_results(self) -> None:
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(
            return_value=_response(
                200,
                {
                    "results": [
                        {
                            "title": "Tavily Hit",
                            "url": "https://tavily.example",
                            "content": "snippet text",
                            "score": 0.91,
                        }
                    ]
                },
            )
        )
        provider = TavilyWebSearchProvider(api_key="tvly-test", client=client)
        hits = await provider.search("query", count=3)
        assert len(hits) == 1
        assert hits[0].title == "Tavily Hit"
        assert hits[0].snippet == "snippet text"
        assert hits[0].summary == "snippet text"
        assert hits[0].score == 0.91
        assert hits[0].provider == "tavily"
        body = client.post.await_args.kwargs["json"]
        assert body["max_results"] == 3
        assert "api_key" in body

    @pytest.mark.asyncio
    async def test_missing_key_raises(self) -> None:
        provider = TavilyWebSearchProvider(api_key="")
        with pytest.raises(WebSearchError, match="not configured"):
            await provider.search("q")


class TestTavilyFetch:
    @pytest.mark.asyncio
    async def test_extract_maps_to_fetch(self) -> None:
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(
            return_value=_response(
                200,
                {
                    "results": [
                        {
                            "url": "https://example.com",
                            "title": "Page",
                            "raw_content": "# Page\n\nMarkdown",
                        }
                    ]
                },
            )
        )
        provider = TavilyWebSearchProvider(api_key="tvly-test", client=client)
        result = await provider.fetch("https://example.com")
        assert result.title == "Page"
        assert "Markdown" in result.content
        assert result.provider == "tavily"

    @pytest.mark.asyncio
    async def test_empty_extract_raises(self) -> None:
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(
            return_value=_response(200, {"results": [], "failed_results": ["blocked"]})
        )
        provider = TavilyWebSearchProvider(api_key="tvly-test", client=client)
        with pytest.raises(WebSearchError, match="blocked"):
            await provider.fetch("https://example.com")
