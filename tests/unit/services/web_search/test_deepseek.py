"""Unit tests for DeepSeek Search/Fetch HTTP client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services.web_search.deepseek import DeepSeekWebSearchProvider
from backend.services.web_search.models import WebSearchError


def _response(status: int, payload: dict | str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    if isinstance(payload, dict):
        resp.json.return_value = payload
        resp.text = ""
    else:
        resp.json.side_effect = ValueError("not json")
        resp.text = payload
    return resp


class TestDeepSeekConfigured:
    def test_missing_key_not_configured(self) -> None:
        provider = DeepSeekWebSearchProvider(api_key="")
        assert provider.is_configured() is False
        assert provider.name == "deepseek"

    @pytest.mark.asyncio
    async def test_search_requires_key(self) -> None:
        provider = DeepSeekWebSearchProvider(api_key="")
        with pytest.raises(WebSearchError, match="not configured"):
            await provider.search("test")


class TestDeepSeekSearch:
    @pytest.mark.asyncio
    async def test_parses_official_result_shape(self) -> None:
        payload = {
            "results": [
                {
                    "rerank_score": 2.4,
                    "title": "Example",
                    "url": "https://example.com",
                    "snippet": "short",
                    "summary": "longer summary",
                    "content": "",
                    "site_name": "Example",
                    "date": "2026-06-01T00:00:00+00:00",
                }
            ]
        }
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(return_value=_response(200, payload))

        provider = DeepSeekWebSearchProvider(api_key="sk-test", client=client)
        hits = await provider.search("DeepSeek", count=5)

        assert len(hits) == 1
        assert hits[0].title == "Example"
        assert hits[0].url == "https://example.com"
        assert hits[0].summary == "longer summary"
        assert hits[0].score == 2.4
        assert hits[0].provider == "deepseek"
        body = client.post.await_args.kwargs["json"]
        assert body["query"] == "DeepSeek"
        assert body["count"] == 5
        assert body["need_content"] is False

    @pytest.mark.asyncio
    async def test_empty_results_ok(self) -> None:
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(return_value=_response(200, {"results": []}))
        provider = DeepSeekWebSearchProvider(api_key="sk-test", client=client)
        hits = await provider.search("nope")
        assert hits == []

    @pytest.mark.asyncio
    async def test_query_truncated_to_128(self) -> None:
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(return_value=_response(200, {"results": []}))
        provider = DeepSeekWebSearchProvider(api_key="sk-test", client=client)
        long_query = "汉" * 200
        await provider.search(long_query)
        body = client.post.await_args.kwargs["json"]
        assert len(body["query"]) == 128

    @pytest.mark.asyncio
    async def test_blank_query_rejected(self) -> None:
        provider = DeepSeekWebSearchProvider(api_key="sk-test", client=MagicMock())
        with pytest.raises(WebSearchError, match="non-empty"):
            await provider.search("   ")

    @pytest.mark.asyncio
    async def test_retries_429_then_succeeds(self) -> None:
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(
            side_effect=[
                _response(429, {"error": {"message": "rate limited"}}),
                _response(200, {"results": [{"title": "ok", "url": "https://x"}]}),
            ]
        )
        provider = DeepSeekWebSearchProvider(api_key="sk-test", client=client, max_retries=3)
        with patch("backend.services.web_search.deepseek.asyncio.sleep", new_callable=AsyncMock):
            hits = await provider.search("q")
        assert len(hits) == 1
        assert client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_4xx_raises(self) -> None:
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(return_value=_response(400, {"error": {"message": "bad count"}}))
        provider = DeepSeekWebSearchProvider(api_key="sk-test", client=client)
        with pytest.raises(WebSearchError, match="bad count") as exc_info:
            await provider.search("q")
        assert exc_info.value.status_code == 400
        assert exc_info.value.retryable is False
        assert client.post.await_count == 1


class TestDeepSeekFetch:
    @pytest.mark.asyncio
    async def test_parses_markdown_body(self) -> None:
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(
            return_value=_response(200, {"title": "Article", "content": "# Article\n\nBody"})
        )
        provider = DeepSeekWebSearchProvider(api_key="sk-test", client=client)
        result = await provider.fetch("https://example.com/a")
        assert result.title == "Article"
        assert "Body" in result.content
        assert result.provider == "deepseek"
        assert result.url == "https://example.com/a"
