"""Orchestrator agent — central coordinator that routes tasks."""

from __future__ import annotations

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.modes import mode_spec
from backend.state.schema import WorkflowPhase, XHSGrowthState


class OrchestratorAgent(BaseAgent):
    task_type = TaskType.ROUTING
    agent_name = "orchestrator"
    prompt_file = "orchestrator.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
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

        # 起点阶段是模式事实（backend/state/modes.py）：brief → BRIEFING，
        # trend → SCOUTING。
        return {"phase": mode_spec(state).initial_phase}
