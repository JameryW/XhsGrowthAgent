"""Web search facade: DeepSeek first, Tavily fallback when configured."""

from __future__ import annotations

import logging
import os
from typing import Any

from backend.services.web_search.deepseek import DeepSeekWebSearchProvider
from backend.services.web_search.models import (
    FetchResponse,
    SearchResponse,
    WebSearchError,
)
from backend.services.web_search.protocol import WebSearchProvider
from backend.services.web_search.tavily import TavilyWebSearchProvider

logger = logging.getLogger("xhs_growth.services.web_search")


def _env_configured(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def provider_config_status() -> dict[str, Any]:
    """Key presence + which provider the facade would try first.

    Used by ``/api/system/health`` ``search_api`` — no network probe.
    """
    deepseek = _env_configured("DEEPSEEK_API_KEY")
    tavily = _env_configured("TAVILY_API_KEY")
    if deepseek:
        active = "deepseek"
    elif tavily:
        active = "tavily"
    else:
        active = None
    configured = deepseek or tavily
    if deepseek and tavily:
        message = "DeepSeek Search 优先，Tavily 备用已配置"
    elif deepseek:
        message = "DeepSeek Search/Fetch 已配置（无 Tavily 备用）"
    elif tavily:
        message = "Tavily Search/Extract 已配置（DeepSeek 未配置）"
    else:
        message = "缺少 DEEPSEEK_API_KEY / TAVILY_API_KEY（趋势发现将使用 LLM 生成数据）"
    return {
        "status": "ok" if configured else "warning",
        "configured": configured,
        "active_provider": active,
        "providers": {
            "deepseek": {"configured": deepseek},
            "tavily": {"configured": tavily},
        },
        "message": message,
    }


class WebSearchRouter:
    """Ordered provider facade: DeepSeek → Tavily on retryable / missing primary."""

    def __init__(
        self,
        *,
        primary: WebSearchProvider | None = None,
        fallback: WebSearchProvider | None = None,
    ) -> None:
        self._primary = primary if primary is not None else DeepSeekWebSearchProvider()
        self._fallback = fallback if fallback is not None else TavilyWebSearchProvider()

    @property
    def active_provider_name(self) -> str | None:
        if self._primary.is_configured():
            return self._primary.name
        if self._fallback.is_configured():
            return self._fallback.name
        return None

    def is_configured(self) -> bool:
        return self._primary.is_configured() or self._fallback.is_configured()

    def _chain(self) -> list[tuple[WebSearchProvider, bool]]:
        """(provider, is_fallback) in attempt order."""
        chain: list[tuple[WebSearchProvider, bool]] = []
        if self._primary.is_configured():
            chain.append((self._primary, False))
            if self._fallback.is_configured():
                chain.append((self._fallback, True))
        elif self._fallback.is_configured():
            chain.append((self._fallback, False))
        return chain

    async def search(
        self,
        query: str,
        *,
        count: int = 10,
        need_content: bool = False,
        ori_question: str | None = None,
    ) -> SearchResponse:
        chain = self._chain()
        if not chain:
            return SearchResponse(
                results=[],
                provider="",
                fallback_used=False,
                error="no_search_provider_configured",
            )

        last_error = ""
        for provider, is_fallback in chain:
            try:
                hits = await provider.search(
                    query,
                    count=count,
                    need_content=need_content,
                    ori_question=ori_question,
                )
                if is_fallback:
                    logger.info(
                        f"Web search fallback to {provider.name} succeeded "
                        f"(query_len={len(query)}, hits={len(hits)})"
                    )
                return SearchResponse(
                    results=hits,
                    provider=provider.name,
                    fallback_used=is_fallback,
                )
            except WebSearchError as e:
                last_error = str(e)
                logger.warning(f"Web search via {provider.name} failed: {type(e).__name__}: {e}")
                # Always try the next configured provider (unconfigured primary
                # is already skipped; primary failures of any kind fall through).
                continue
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(f"Web search via {provider.name} unexpected error: {last_error}")
                continue

        return SearchResponse(
            results=[],
            provider="",
            fallback_used=len(chain) > 1,
            error=last_error or "search_failed",
        )

    async def fetch(self, url: str) -> FetchResponse:
        chain = self._chain()
        if not chain:
            return FetchResponse(
                url=url,
                error="no_search_provider_configured",
            )

        last_error = ""
        for provider, is_fallback in chain:
            try:
                result = await provider.fetch(url)
                if is_fallback:
                    logger.info(f"Web fetch fallback to {provider.name} succeeded")
                return FetchResponse(
                    title=result.title,
                    content=result.content,
                    url=result.url or url,
                    provider=provider.name,
                    fallback_used=is_fallback,
                )
            except WebSearchError as e:
                last_error = str(e)
                logger.warning(f"Web fetch via {provider.name} failed: {type(e).__name__}: {e}")
                continue
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(f"Web fetch via {provider.name} unexpected error: {last_error}")
                continue

        return FetchResponse(
            url=url,
            provider="",
            fallback_used=len(chain) > 1,
            error=last_error or "fetch_failed",
        )


_default_router: WebSearchRouter | None = None


def get_web_search_router() -> WebSearchRouter:
    """Process-wide default router (keys read from env at call time per provider)."""
    global _default_router
    if _default_router is None:
        _default_router = WebSearchRouter()
    return _default_router


def reset_web_search_router() -> None:
    """Test helper — drop the cached singleton."""
    global _default_router
    _default_router = None
