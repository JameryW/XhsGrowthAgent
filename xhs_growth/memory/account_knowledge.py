"""Account knowledge memory — 长期账号画像"""

from langgraph.store.base import BaseStore

from xhs_growth.memory.store import MemoryManager


class AccountKnowledge:
    """管理账号长期画像数据"""

    def __init__(self, account_id: str):
        self._mm = MemoryManager(account_id)

    async def get_profile(self, store: BaseStore) -> dict:
        items = await store.asearch(self._mm.account_ns, query="account profile", limit=1)
        return items[0].value if items else {}

    async def update_profile(self, store: BaseStore, profile: dict) -> None:
        await store.aput(self._mm.account_ns, key="profile", value=profile)
