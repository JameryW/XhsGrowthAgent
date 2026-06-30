"""Long-term memory manager — namespace-based memory with semantic + keyword search."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langgraph.store.base import BaseStore

logger = logging.getLogger("xhs_growth.memory.store")


def _keyword_filter(items: list, keywords: list[str]) -> list:
    """Post-filter asearch results by keywords — all keywords must appear in any value field."""
    if not keywords:
        return items
    kw_lower = [k.lower() for k in keywords]
    filtered = []
    for item in items:
        # Concatenate all string values for keyword matching
        text = " ".join(
            str(v) for v in item.value.values() if isinstance(v, (str, int, float, bool))
        ).lower()
        if all(kw in text for kw in kw_lower):
            filtered.append(item)
    return filtered


class MemoryManager:
    """管理小红书增长引擎的长期记忆"""

    def __init__(self, account_id: str):
        self.account_id = account_id

    # ── Namespace helpers ──

    @property
    def account_ns(self) -> tuple[str, str]:
        return ("accounts", self.account_id)

    @property
    def content_history_ns(self) -> tuple[str, str, str]:
        return ("accounts", self.account_id, "content_history")

    @property
    def audience_ns(self) -> tuple[str, str, str]:
        return ("accounts", self.account_id, "audience_preferences")

    @property
    def insights_ns(self) -> tuple[str, str, str]:
        return ("accounts", self.account_id, "performance_insights")

    @property
    def strategy_ns(self) -> tuple[str, str, str]:
        return ("accounts", self.account_id, "strategy_notes")

    # ── Write ──

    async def store_content_record(
        self, store: BaseStore, post_id: str, record: dict[str, Any]
    ) -> None:
        await store.aput(self.content_history_ns, key=post_id, value=record)

    async def store_insight(self, store: BaseStore, insight: str, metadata: dict[str, Any]) -> None:
        await store.aput(
            self.insights_ns,
            key=str(uuid.uuid4()),
            value={"insight": insight, **metadata},
        )

    async def store_audience_preference(
        self, store: BaseStore, preference: str, data: dict[str, Any]
    ) -> None:
        await store.aput(
            self.audience_ns,
            key=str(uuid.uuid4()),
            value={"preference": preference, **data},
        )

    async def store_strategy_note(self, store: BaseStore, note: str, data: dict[str, Any]) -> None:
        await store.aput(
            self.strategy_ns,
            key=str(uuid.uuid4()),
            value={"note": note, **data},
        )

    # ── Read (semantic search + keyword filter) ──

    async def recall_similar_content(
        self,
        store: BaseStore,
        query: str,
        limit: int = 5,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[dict]:
        try:
            # Over-fetch to compensate for keyword filtering
            fetch_limit = limit * 2 if keywords else limit
            items = await store.asearch(
                self.content_history_ns,
                query=query,
                limit=fetch_limit,
                filter=filter,
            )
            if keywords:
                items = _keyword_filter(items, keywords)
            return [item.value for item in items[:limit]]
        except Exception as e:
            logger.warning(f"recall_similar_content failed: {e}")
            return []

    async def recall_audience_preferences(
        self,
        store: BaseStore,
        query: str,
        limit: int = 3,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[dict]:
        try:
            fetch_limit = limit * 2 if keywords else limit
            items = await store.asearch(
                self.audience_ns,
                query=query,
                limit=fetch_limit,
                filter=filter,
            )
            if keywords:
                items = _keyword_filter(items, keywords)
            return [item.value for item in items[:limit]]
        except Exception as e:
            logger.warning(f"recall_audience_preferences failed: {e}")
            return []

    async def recall_insights(
        self,
        store: BaseStore,
        query: str,
        limit: int = 5,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[dict]:
        try:
            fetch_limit = limit * 2 if keywords else limit
            items = await store.asearch(
                self.insights_ns,
                query=query,
                limit=fetch_limit,
                filter=filter,
            )
            if keywords:
                items = _keyword_filter(items, keywords)
            return [item.value for item in items[:limit]]
        except Exception as e:
            logger.warning(f"recall_insights failed: {e}")
            return []

    async def recall_strategy_notes(
        self,
        store: BaseStore,
        query: str,
        limit: int = 3,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[dict]:
        try:
            fetch_limit = limit * 2 if keywords else limit
            items = await store.asearch(
                self.strategy_ns,
                query=query,
                limit=fetch_limit,
                filter=filter,
            )
            if keywords:
                items = _keyword_filter(items, keywords)
            return [item.value for item in items[:limit]]
        except Exception as e:
            logger.warning(f"recall_strategy_notes failed: {e}")
            return []
