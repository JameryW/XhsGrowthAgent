"""Trend Scout agent — discovers hot topics and opportunities."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.schema import XHSGrowthState, WorkflowPhase


class TrendScoutAgent(BaseAgent):
    task_type = TaskType.SCOUTING
    agent_name = "trend_scout"
    prompt_file = "trend_scout.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        account_id = state.get("account_id", "default")

        # 召回历史洞察
        insights = await self._recall_memory(
            store, account_id, query="trend insights", namespace="performance_insights", limit=3
        )
        memory_context = ""
        if insights:
            memory_context = "\n历史趋势洞察：\n"
            for i in insights:
                memory_context += f"- {i.get('insight', '')}\n"

        system_prompt = self._build_system_prompt(state, extra_context=memory_context)

        user_msg = f"""账号定位：{state.get('account_id', 'default')}
关注领域：生活方式、美妆、穿搭
竞品账号：暂无"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        trend_data = self._parse_json_response(response.content)

        return {
            "trend_data": trend_data,
            "phase": WorkflowPhase.SCOUTING,
        }