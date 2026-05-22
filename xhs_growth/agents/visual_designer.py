"""Visual Designer agent — generates cover prompts and layout recommendations."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase


class VisualDesignerAgent(BaseAgent):
    task_type = TaskType.VISUAL
    agent_name = "visual_designer"
    prompt_file = "visual_designer.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        plan = state.get("content_plan", {})
        copy = state.get("copy_content", {})

        system_prompt = self._build_system_prompt(state)

        body_summary = copy.get("body_text", "")[:200] if copy else ""
        user_msg = f"""选题：{plan.get('selected_topic', '')}
角度：{plan.get('content_angle', '')}
内容类型：{plan.get('content_type', 'note')}
正文摘要：{body_summary}"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        visual_plan = self._parse_json_response(response.content)

        return {
            "visual_plan": visual_plan,
            "phase": WorkflowPhase.CREATING,
        }