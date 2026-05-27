"""Memory mixin for context recall."""

from langgraph.store.base import BaseStore
from backend.memory.store import MemoryManager


class MemoryMixin:
    """记忆召回能力"""

    async def recall_context(
        self,
        store: BaseStore,
        account_id: str,
        query: str,
        namespace: str = "performance_insights",
        limit: int = 5
    ) -> list[dict]:
        """从记忆存储召回相关上下文"""
        mm = MemoryManager(account_id)
        ns_map = {
            "content_history": mm.content_history_ns,
            "audience_preferences": mm.audience_ns,
            "performance_insights": mm.insights_ns,
            "strategy_notes": mm.strategy_ns,
        }
        ns = ns_map.get(namespace, mm.insights_ns)
        items = await store.asearch(ns, query=query, limit=limit)
        return [item.value for item in items]