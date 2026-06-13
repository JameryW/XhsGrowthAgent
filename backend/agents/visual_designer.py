"""Visual Designer agent — generates cover prompts and layout recommendations."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.schema import WorkflowPhase, XHSGrowthState


class VisualDesignerAgent(BaseAgent):
    task_type = TaskType.VISUAL
    agent_name = "visual_designer"
    prompt_file = "visual_designer.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        account_id = state.get("account_id", "default")
        plan = state.get("content_plan", {})
        copy = state.get("copy_content", {})

        # ── Creative Memory: 读取风格指纹 + 封面素材 ──
        from backend.memory.creative import CreativeMemory

        cm = CreativeMemory(account_id, store=store)
        styles = await cm.recall_style(query=plan.get("selected_topic", ""))
        cover_materials = await cm.recall_materials(category="封面", limit=3)

        creative_ctx = cm.build_creative_context(styles, [], cover_materials)
        system_prompt = self._build_system_prompt(state, extra_context=creative_ctx)

        niche = state.get("niche", "母婴")
        body_summary = copy.get("body_text", "")[:200] if copy else ""
        user_msg = f"""选题：{plan.get("selected_topic", "")}
角度：{plan.get("content_angle", "")}
内容类型：{plan.get("content_type", "note")}
垂类赛道：{niche}
正文摘要：{body_summary}"""

        response = await self.model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        visual_plan = self._parse_json_response(response.content)

        # ── Creative Memory: 沉淀风格选择 ──
        from backend.memory.types import StyleDNA

        visual_style = visual_plan.get("style_name", "")
        if visual_style:
            await cm.deposit_style(
                StyleDNA(
                    visual_style=visual_style,
                    color_palette=visual_plan.get("color_palette", []),
                    layout_preference=visual_plan.get("layout_type", ""),
                )
            )

        return {
            "visual_plan": visual_plan,
            "phase": WorkflowPhase.CREATING,
        }
