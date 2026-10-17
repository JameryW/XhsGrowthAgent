"""DeepSeek Search & Fetch REST client (``/v1/tools/search``, ``/v1/tools/fetch``)."""

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

logger = logging.getLogger("xhs_growth.services.web_search.deepseek")

_BASE_URL = "https://api.deepseek.com"
_SEARCH_PATH = "/v1/tools/search"
_FETCH_PATH = "/v1/tools/fetch"
_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class DeepSeekWebSearchProvider:
    """Standalone DeepSeek Search/Fetch REST — reuses ``DEEPSEEK_API_KEY``."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = _BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        env_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self._api_key = (api_key if api_key is not None else env_key).strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client

    @property
    def name(self) -> str:
        return "deepseek"

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None and not self._client.is_closed:
            return self._client
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout, connect=10.0),
            headers=self._headers(),
        )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise WebSearchError(
                "DEEPSEEK_API_KEY not configured",
                provider=self.name,
                retryable=False,
            )

        client = await self._get_client()
        last_error: WebSearchError | None = None

        for attempt in range(self._max_retries):
            try:
                resp = await client.post(path, json=body, headers=self._headers())
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_error = WebSearchError(
                    f"DeepSeek transport error: {type(e).__name__}: {e}",
                    provider=self.name,
                    retryable=True,
                )
                logger.warning(
                    f"DeepSeek {path} transport failure (attempt {attempt + 1}): {type(e).__name__}"
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                raise last_error from e

            if resp.status_code == 200:
                data = resp.json()
                if not isinstance(data, dict):
                    raise WebSearchError(
                        "DeepSeek returned non-object JSON",
                        provider=self.name,
                        status_code=200,
                        retryable=False,
                    )
                return data

            retryable = resp.status_code in _RETRYABLE_STATUS
            message = _error_message(resp)
            last_error = WebSearchError(
                message,
                provider=self.name,
                status_code=resp.status_code,
                retryable=retryable,
            )
            if retryable and attempt < self._max_retries - 1:
                logger.warning(
                    f"DeepSeek {path} HTTP {resp.status_code} (attempt {attempt + 1}): {message}"
                )
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            raise last_error

        raise last_error or WebSearchError(
            "DeepSeek request failed",
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
        # Official Search API: query is 1–128 Unicode chars, not all whitespace.
        # Truncate here so callers (trend_scout, Gateway) cannot trip a 400.
        normalized = (query or "").strip()
        if not normalized:
            raise WebSearchError(
                "query must be non-empty",
                provider=self.name,
                status_code=400,
                retryable=False,
            )
        body: dict[str, Any] = {
            "query": normalized[:128],
            "count": max(1, min(count, 50)),
            "need_content": need_content,
        }
        if ori_question:
            hint = ori_question.strip()
            if hint:
                body["ori_question"] = hint[:128]

        data = await self._post_json(_SEARCH_PATH, body)
        raw_results = data.get("results") or []
        hits: list[SearchHit] = []
        if not isinstance(raw_results, list):
            return hits
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            hits.append(
                SearchHit(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("snippet") or ""),
                    summary=str(item.get("summary") or ""),
                    content=str(item.get("content") or ""),
                    site_name=_optional_str(item.get("site_name")),
                    date=_optional_str(item.get("date")),
                    score=_optional_float(item.get("rerank_score")),
                    provider=self.name,
                )
            )
        return hits

    async def fetch(self, url: str) -> FetchResponse:
        data = await self._post_json(_FETCH_PATH, {"url": url})
        return FetchResponse(
            title=str(data.get("title") or ""),
            content=str(data.get("content") or ""),
            url=url,
            provider=self.name,
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


def _error_message(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:200]
        if payload.get("message"):
            return str(payload["message"])[:200]
    text = (resp.text or "").strip()
    if text:
        return text[:200]
    return f"HTTP {resp.status_code}"
