"""WebSearchProvider protocol — third providers implement this interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.services.web_search.models import FetchResponse, SearchHit


@runtime_checkable
class WebSearchProvider(Protocol):
    """Unified Search / Fetch surface for DeepSeek, Tavily, or a third party."""

    @property
    def name(self) -> str:
        """Stable provider id (e.g. ``deepseek``, ``tavily``)."""
        ...

    def is_configured(self) -> bool:
        """True when the provider has credentials and can be attempted."""
        ...

    async def search(
        self,
        query: str,
        *,
        count: int = 10,
        need_content: bool = False,
        ori_question: str | None = None,
    ) -> list[SearchHit]:
        """Run a web search and return normalized hits.

        Raises:
            WebSearchError: on HTTP / provider failure after local retries.
        """
        ...

    async def fetch(self, url: str) -> FetchResponse:
        """Fetch one URL as Markdown title + body.

        Raises:
            WebSearchError: on HTTP / provider failure after local retries.
        """
        ...
