"""Shared result models for web Search / Fetch providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchHit:
    """One web search hit, normalized across providers."""

    title: str
    url: str
    snippet: str = ""
    summary: str = ""
    content: str = ""
    site_name: str | None = None
    date: str | None = None
    score: float | None = None
    provider: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "summary": self.summary,
            "content": self.content,
            "site_name": self.site_name,
            "date": self.date,
            "score": self.score,
            "provider": self.provider,
        }


@dataclass(frozen=True)
class SearchResponse:
    """Normalized search response from the active (or fallback) provider."""

    results: list[SearchHit] = field(default_factory=list)
    provider: str = ""
    fallback_used: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [hit.to_dict() for hit in self.results],
            "provider": self.provider,
            "fallback_used": self.fallback_used,
            "error": self.error,
        }


@dataclass(frozen=True)
class FetchResponse:
    """Normalized page fetch → Markdown body."""

    title: str = ""
    content: str = ""
    url: str = ""
    provider: str = ""
    fallback_used: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "provider": self.provider,
            "fallback_used": self.fallback_used,
            "error": self.error,
        }


class WebSearchError(Exception):
    """Provider-level failure after retries (caller may fallback)."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
