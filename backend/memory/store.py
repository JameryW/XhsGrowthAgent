"""Long-term memory manager — namespace-based memory with semantic + keyword search."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # BaseStore only appears in annotations. Importing langgraph.store.base at
    # module load pulls langchain_core.runnables (~0.4s) on every import of
    # backend.memory.store (pulled by agents.base → MemoryManager). Deferred.
    from langgraph.store.base import BaseStore


def _keyword_filter(items: list[Any], keywords: list[str]) -> list[Any]:
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
    #
    # 失败即抛（票 5m）：这四个方法原来各自 ``except Exception: return []``，
    # 而 ``[]`` 同时也是"读到了、确实没有"的答案 —— 调用方无法区分"没有记忆"
    # 与"记忆库挂了"。现在空列表只表示前一个事实；读失败原样上抛，由调用方
    # 决定降级（上层 ``context.retrieval`` 的 ``RetrievalResult`` 就是这样做的，
    # 它会给出 DEGRADED 而不是 EMPTY）。

    async def recall_similar_content(
        self,
        store: BaseStore,
        query: str,
        limit: int = 5,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
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

    async def recall_audience_preferences(
        self,
        store: BaseStore,
        query: str,
        limit: int = 3,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
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

    async def recall_insights(
        self,
        store: BaseStore,
        query: str,
        limit: int = 5,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
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

    async def recall_strategy_notes(
        self,
        store: BaseStore,
        query: str,
        limit: int = 3,
        *,
        keywords: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
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
