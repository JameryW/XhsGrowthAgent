"""Orchestrator agent — central coordinator that routes tasks."""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore
from langgraph.types import Command

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.schema import XHSGrowthState, WorkflowPhase


class OrchestratorAgent(BaseAgent):
    task_type = TaskType.ROUTING
    agent_name = "orchestrator"
    prompt_file = "orchestrator.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        # 优先处理待处理互动
        pending = state.get("engagement_actions", [])
        if pending and not state.get("content_plan"):
            return {"phase": WorkflowPhase.ENGAGING}

        # 有数据但无分析 → 先分析
        analytics = state.get("analytics", {})
        if analytics and not analytics.get("insights"):
            return {"phase": WorkflowPhase.ANALYZING}

        # 有错误 → 检查是否可恢复
        error = state.get("error")
        retry_count = state.get("retry_count", 0)
        if error and retry_count >= 3:
            return {"phase": WorkflowPhase.ERROR}
        if error:
            # 清除错误，重新开始侦察周期
            return {"phase": WorkflowPhase.SCOUTING, "error": None, "retry_count": 0}

        # 默认 → 开始侦察周期
        return {"phase": WorkflowPhase.SCOUTING}