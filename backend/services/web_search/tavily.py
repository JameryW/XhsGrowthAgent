"""Tavily Search + Extract client mapped onto the unified Search / Fetch models."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from backend.services.web_search.models import (
    FetchResponse,
    SearchHit,
    WebSearchError,
)

logger = logging.getLogger("xhs_growth.services.web_search.tavily")

_SEARCH_URL = "https://api.tavily.com/search"
_EXTRACT_URL = "https://api.tavily.com/extract"
_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class TavilyWebSearchProvider:
    """Tavily Search → ``search``, Extract → ``fetch``."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        env_key = os.environ.get("TAVILY_API_KEY", "")
        self._api_key = (api_key if api_key is not None else env_key).strip()
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client

    @property
    def name(self) -> str:
        return "tavily"

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None and not self._client.is_closed:
            return self._client
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise WebSearchError(
                "TAVILY_API_KEY not configured",
                provider=self.name,
                retryable=False,
            )

        client = await self._get_client()
        payload = {**body, "api_key": self._api_key}
        last_error: WebSearchError | None = None

        for attempt in range(self._max_retries):
            try:
                resp = await client.post(url, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_error = WebSearchError(
                    f"Tavily transport error: {type(e).__name__}: {e}",
                    provider=self.name,
                    retryable=True,
                )
                logger.warning(
                    f"Tavily transport failure (attempt {attempt + 1}): {type(e).__name__}"
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                raise last_error from e

            if resp.status_code == 200:
                data = resp.json()
                if not isinstance(data, dict):
                    raise WebSearchError(
                        "Tavily returned non-object JSON",
                        provider=self.name,
                        status_code=200,
                        retryable=False,
                    )
                return data

            retryable = resp.status_code in _RETRYABLE_STATUS
            message = (resp.text or f"HTTP {resp.status_code}")[:200]
            last_error = WebSearchError(
                message,
                provider=self.name,
                status_code=resp.status_code,
                retryable=retryable,
            )
            if retryable and attempt < self._max_retries - 1:
                logger.warning(f"Tavily HTTP {resp.status_code} (attempt {attempt + 1}): {message}")
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            raise last_error

        raise last_error or WebSearchError(
            "Tavily request failed",
            provider=self.name,
            retryable=True,
        )

    async def search(
        self,
        query: str,
        *,
        count: int = 10,
        need_content: bool = False,
        ori_question: str | None = None,
    ) -> list[SearchHit]:
        del ori_question  # DeepSeek-only hint; Tavily has no equivalent field.
        normalized = (query or "").strip()
        if not normalized:
            raise WebSearchError(
                "query must be non-empty",
                provider=self.name,
                status_code=400,
                retryable=False,
            )
        body: dict[str, Any] = {
            "query": normalized,
            "max_results": max(1, min(count, 20)),
            "include_raw_content": need_content,
        }
        data = await self._post_json(_SEARCH_URL, body)
        raw_results = data.get("results") or []
        hits: list[SearchHit] = []
        if not isinstance(raw_results, list):
            return hits
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            content = str(item.get("raw_content") or item.get("content") or "")
            snippet = str(item.get("content") or "")
            hits.append(
                SearchHit(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    snippet=snippet,
                    summary=snippet,
                    content=content if need_content else "",
                    site_name=None,
                    date=_optional_str(item.get("published_date")),
                    score=_optional_float(item.get("score")),
                    provider=self.name,
                )
            )
        return hits

    async def fetch(self, url: str) -> FetchResponse:
        data = await self._post_json(_EXTRACT_URL, {"urls": [url]})
        results = data.get("results") or []
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                return FetchResponse(
                    title=str(first.get("title") or ""),
                    content=str(first.get("raw_content") or first.get("content") or ""),
                    url=str(first.get("url") or url),
                    provider=self.name,
                )
        failed = data.get("failed_results") or []
        detail = ""
        if isinstance(failed, list) and failed:
            detail = str(failed[0])[:200]
        raise WebSearchError(
            detail or "Tavily extract returned no content",
            provider=self.name,
            status_code=404,
            retryable=False,
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
