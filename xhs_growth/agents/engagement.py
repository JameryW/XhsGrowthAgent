"""Engagement agent — manages comments, DMs, and fan interactions."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase


class EngagementAgent(BaseAgent):
    task_type = TaskType.ENGAGEMENT
    agent_name = "engagement"
    prompt_file = "engagement.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        account_id = state.get("account_id", "default")

        # 召回受众偏好
        audience_prefs = await self._recall_memory(
            store, account_id, query="audience interaction style", namespace="audience_preferences", limit=3
        )

        system_prompt = self._build_system_prompt(state)

        # TODO: 从 XHS API 获取真实互动
        # client = XHSClient(...)
        # comments = await client.get_comments(post_id)
        # dms = await client.get_direct_messages()

        # 模拟处理
        engagement_actions = []

        return {
            "engagement_actions": engagement_actions,
            "phase": WorkflowPhase.ENGAGING,
        }