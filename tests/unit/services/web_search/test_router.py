"""Unit tests for WebSearchRouter fallback and health status helper."""

from __future__ import annotations

from typing import Any

import pytest

from backend.services.web_search.models import FetchResponse, SearchHit, WebSearchError
from backend.services.web_search.router import (
    WebSearchRouter,
    provider_config_status,
    reset_web_search_router,
)


class _FakeProvider:
    def __init__(
        self,
        name: str,
        *,
        configured: bool = True,
        hits: list[SearchHit] | None = None,
        error: WebSearchError | None = None,
        fetch: FetchResponse | None = None,
        fetch_error: WebSearchError | None = None,
    ) -> None:
        self._name = name
        self._configured = configured
        self._hits = hits or []
        self._error = error
        self._fetch = fetch
        self._fetch_error = fetch_error
        self.search_calls = 0
        self.fetch_calls = 0

    @property
    def name(self) -> str:
        return self._name

    def is_configured(self) -> bool:
        return self._configured

    async def search(
        self,
        query: str,
        *,
        count: int = 10,
        need_content: bool = False,
        ori_question: str | None = None,
    ) -> list[SearchHit]:
        del query, count, need_content, ori_question
        self.search_calls += 1
        if self._error:
            raise self._error
        return self._hits

    async def fetch(self, url: str) -> FetchResponse:
        del url
        self.fetch_calls += 1
        if self._fetch_error:
            raise self._fetch_error
        assert self._fetch is not None
        return self._fetch


class TestProviderConfigStatus:
    def test_neither_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        status = provider_config_status()
        assert status["configured"] is False
        assert status["active_provider"] is None
        assert status["status"] == "warning"
        assert status["providers"]["deepseek"]["configured"] is False
        assert status["providers"]["tavily"]["configured"] is False

    def test_deepseek_primary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        status = provider_config_status()
        assert status["configured"] is True
        assert status["active_provider"] == "deepseek"
        assert status["status"] == "ok"

    def test_tavily_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("TAVILY_API_KEY", "tvly")
        status = provider_config_status()
        assert status["active_provider"] == "tavily"
        assert status["providers"]["tavily"]["configured"] is True

    def test_both_keys_prefer_deepseek(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("TAVILY_API_KEY", "tvly")
        status = provider_config_status()
        assert status["active_provider"] == "deepseek"
        assert "备用" in status["message"]


class TestWebSearchRouter:
    @pytest.mark.asyncio
    async def test_primary_success(self) -> None:
        primary = _FakeProvider(
            "deepseek",
            hits=[SearchHit(title="a", url="https://a", provider="deepseek")],
        )
        fallback = _FakeProvider("tavily", hits=[])
        router = WebSearchRouter(primary=primary, fallback=fallback)
        result = await router.search("q")
        assert result.provider == "deepseek"
        assert result.fallback_used is False
        assert len(result.results) == 1
        assert fallback.search_calls == 0

    @pytest.mark.asyncio
    async def test_fallback_on_primary_429(self) -> None:
        primary = _FakeProvider(
            "deepseek",
            error=WebSearchError("rate", provider="deepseek", status_code=429, retryable=True),
        )
        fallback = _FakeProvider(
            "tavily",
            hits=[SearchHit(title="b", url="https://b", provider="tavily")],
        )
        router = WebSearchRouter(primary=primary, fallback=fallback)
        result = await router.search("q")
        assert result.provider == "tavily"
        assert result.fallback_used is True
        assert primary.search_calls == 1
        assert fallback.search_calls == 1

    @pytest.mark.asyncio
    async def test_unconfigured_primary_uses_tavily(self) -> None:
        primary = _FakeProvider("deepseek", configured=False)
        fallback = _FakeProvider(
            "tavily",
            hits=[SearchHit(title="c", url="https://c", provider="tavily")],
        )
        router = WebSearchRouter(primary=primary, fallback=fallback)
        result = await router.search("q")
        assert result.provider == "tavily"
        assert result.fallback_used is False
        assert primary.search_calls == 0

    @pytest.mark.asyncio
    async def test_both_fail_returns_error_not_raise(self) -> None:
        primary = _FakeProvider(
            "deepseek",
            error=WebSearchError("boom", provider="deepseek", retryable=True),
        )
        fallback = _FakeProvider(
            "tavily",
            error=WebSearchError("boom2", provider="tavily", retryable=True),
        )
        router = WebSearchRouter(primary=primary, fallback=fallback)
        result = await router.search("q")
        assert result.results == []
        assert result.error
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_no_provider_configured(self) -> None:
        router = WebSearchRouter(
            primary=_FakeProvider("deepseek", configured=False),
            fallback=_FakeProvider("tavily", configured=False),
        )
        result = await router.search("q")
        assert result.error == "no_search_provider_configured"

    @pytest.mark.asyncio
    async def test_fetch_fallback(self) -> None:
        primary = _FakeProvider(
            "deepseek",
            fetch_error=WebSearchError("fail", provider="deepseek", retryable=True),
        )
        fallback = _FakeProvider(
            "tavily",
            fetch=FetchResponse(title="T", content="# T", url="https://x", provider="tavily"),
        )
        router = WebSearchRouter(primary=primary, fallback=fallback)
        result = await router.fetch("https://x")
        assert result.provider == "tavily"
        assert result.fallback_used is True
        assert result.content.startswith("#")


class TestSystemHealthWiring:
    def test_check_search_uses_facade(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk")
        monkeypatch.setenv("TAVILY_API_KEY", "tv")
        reset_web_search_router()
        from backend.api.routes.system import _check_search

        status: dict[str, Any] = _check_search()
        assert status["active_provider"] == "deepseek"
        assert status["providers"]["tavily"]["configured"] is True
