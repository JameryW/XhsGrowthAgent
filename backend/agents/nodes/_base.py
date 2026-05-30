"""Base classes for graph nodes."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.state.schema import XHSGrowthState


class NodeContext:
    """节点执行上下文"""

    def __init__(self, state: XHSGrowthState, store: BaseStore | None):
        self.state = state
        self.store = store


class NodeResult:
    """节点执行结果封装"""

    def __init__(self, updates: dict[str, Any], agent_name: str = ""):
        self.updates = updates
        self.agent_name = agent_name

    def to_dict(self) -> dict[str, Any]:
        """转换为状态更新字典"""
        result = self.updates.copy()
        if self.agent_name:
            result["current_agent"] = self.agent_name
        return result