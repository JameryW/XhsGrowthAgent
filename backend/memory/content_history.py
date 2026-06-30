"""Content history memory — 发布内容历史"""

from typing import Any

from langgraph.store.base import BaseStore

from backend.memory.store import MemoryManager


class ContentHistory:
    """管理发布内容历史"""

    def __init__(self, account_id: str):
        self._mm = MemoryManager(account_id)

    async def record(self, store: BaseStore, post_id: str, data: dict[str, Any]) -> None:
        await self._mm.store_content_record(store, post_id, data)

    async def find_similar(
        self, store: BaseStore, topic: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        return await self._mm.recall_similar_content(store, query=topic, limit=limit)
