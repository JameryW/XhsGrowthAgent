"""Copywriter agent — generates titles, body text, hashtags."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase


class CopywriterAgent(BaseAgent):
    task_type = TaskType.WRITING
    agent_name = "copywriter"
    prompt_file = "copywriter.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        account_id = state.get("account_id", "default")
        plan = state.get("content_plan", {})

        # 召回相似历史内容
        past_content = await self._recall_memory(
            store, account_id, query=plan.get("selected_topic", ""), namespace="content_history", limit=3
        )
        # 召回受众偏好
        audience_prefs = await self._recall_memory(
            store, account_id, query=f"audience preference for {plan.get('content_type', 'note')}",
            namespace="audience_preferences", limit=3,
        )

        memory_context = ""
        if past_content:
            memory_context += "\n历史爆款参考：\n"
            for pc in past_content:
                memory_context += f"- {pc.get('title', '')} (互动率: {pc.get('engagement_rate', 'N/A')})\n"
        if audience_prefs:
            memory_context += "\n受众偏好：\n"
            for ap in audience_prefs:
                memory_context += f"- {ap.get('preference', '')}\n"

        system_prompt = self._build_system_prompt(state, extra_context=memory_context)

        user_msg = f"""选题：{plan.get('selected_topic', '')}
角度：{plan.get('content_angle', '')}
目标受众：{plan.get('target_audience', '')}
内容类型：{plan.get('content_type', 'note')}"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        copy_content = self._parse_json_response(response.content)

        return {
            "copy_content": copy_content,
            "phase": WorkflowPhase.CREATING,
        }