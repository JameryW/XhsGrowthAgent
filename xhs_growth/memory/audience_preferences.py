"""Audience preferences memory — 受众偏好"""

from langgraph.store.base import BaseStore

from xhs_growth.memory.store import MemoryManager


class AudiencePreferences:
    """管理受众偏好数据"""

    def __init__(self, account_id: str):
        self._mm = MemoryManager(account_id)

    async def record_preference(self, store: BaseStore, preference: str, data: dict) -> None:
        await self._mm.store_audience_preference(store, preference, data)

    async def get_preferences(self, store: BaseStore, query: str = "", limit: int = 3) -> list[dict]:
        return await self._mm.recall_audience_preferences(store, query=query or "audience", limit=limit)
