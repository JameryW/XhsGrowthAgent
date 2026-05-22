"""Long-term memory manager — namespace-based memory with semantic search."""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.store.base import BaseStore


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

    async def store_content_record(self, store: BaseStore, post_id: str, record: dict[str, Any]) -> None:
        await store.aput(self.content_history_ns, key=post_id, value=record)

    async def store_insight(self, store: BaseStore, insight: str, metadata: dict[str, Any]) -> None:
        await store.aput(self.insights_ns, key=str(uuid.uuid4()), value={"insight": insight, **metadata})

    async def store_audience_preference(self, store: BaseStore, preference: str, data: dict[str, Any]) -> None:
        await store.aput(self.audience_ns, key=str(uuid.uuid4()), value={"preference": preference, **data})

    async def store_strategy_note(self, store: BaseStore, note: str, data: dict[str, Any]) -> None:
        await store.aput(self.strategy_ns, key=str(uuid.uuid4()), value={"note": note, **data})

    # ── Read (semantic search) ──

    async def recall_similar_content(self, store: BaseStore, query: str, limit: int = 5) -> list[dict]:
        items = await store.asearch(self.content_history_ns, query=query, limit=limit)
        return [item.value for item in items]

    async def recall_audience_preferences(self, store: BaseStore, query: str, limit: int = 3) -> list[dict]:
        items = await store.asearch(self.audience_ns, query=query, limit=limit)
        return [item.value for item in items]

    async def recall_insights(self, store: BaseStore, query: str, limit: int = 5) -> list[dict]:
        items = await store.asearch(self.insights_ns, query=query, limit=limit)
        return [item.value for item in items]

    async def recall_strategy_notes(self, store: BaseStore, query: str, limit: int = 3) -> list[dict]:
        items = await store.asearch(self.strategy_ns, query=query, limit=limit)
        return [item.value for item in items]
