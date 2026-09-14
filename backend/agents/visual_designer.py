"""Visual Designer agent — generates cover prompts and layout recommendations.

P1b-S4 迁移第五批销号（consumer-map §六.5，creative_ctx 类批）：本 agent 无
管线 ns recall（仅 CreativeMemory），creative_ctx 经 compile_prompt 渲染到
`<!-- ctx:l4_memory -->` 标记位。原 `{memory_context}` 占位符位于 system
中部（JSON 输出规范之前），迁移后 L4 段按层序渲染到 L0 尾部——跨层顺序变化
符合 D3' 段落内容集合等价口径（与 copywriter/strategist 同一先例）。
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.context.compiler import ContextCompiler
from backend.context.models import (
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
    require_niche,
)
from backend.state.schema import WorkflowPhase, XHSGrowthState

_compiler = ContextCompiler()


class VisualDesignerAgent(BaseAgent):
    task_type = TaskType.VISUAL
    agent_name = "visual_designer"
    prompt_file = "visual_designer.yaml"

    def _compile_system_prompt(self, state: XHSGrowthState, l4_extra: str) -> str:
        """System prompt via ContextCompiler（S4-5 迁移）。niche 走 require_niche
        fail-fast（S4-7 D2'：不新造默认值）。"""
        run_context = RunContext(
            thread_id=str(state.get("session_id") or ""),
            account_id=str(state.get("account_id", "default")),
            niche=require_niche(state),
            values=state,
        )
        if l4_extra:
            memory = RetrievalResult(
                namespace="visual_designer_memory",
                layer=PromptLayer.L4_MEMORY,
                mode=RetrievalMode.HIT,
                items=(ContextItem(body=l4_extra, source="memory:visual_designer"),),
            )
        else:
            memory = RetrievalResult(
                namespace="visual_designer_memory",
                layer=PromptLayer.L4_MEMORY,
                mode=RetrievalMode.EMPTY,
            )
        return _compiler.compile_prompt(
            run_context, self.prompt_template["system"], retrievals=(memory,)
        ).render()

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        self._reset_llm_perf()
        account_id = state.get("account_id", "default")
        plan = state.get("content_plan", {})
        copy = state.get("copy_content", {})
        brief = state.get("brief_content", {})
        shooting_plan: dict[str, Any] = dict(cast(Any, state.get("shooting_plan")) or {})
        # ponytail: shooting_plan may be empty in trend mode; include only when available
        shooting_ctx = ""
        if shooting_plan:
            scenes = ", ".join(str(s.get("name", "")) for s in (shooting_plan.get("scenes") or []))
            props = ", ".join(str(p) for p in (shooting_plan.get("props") or []))
            shooting_ctx = f"\n拍摄计划场景：{scenes}\n拍摄道具：{props}"

        # ── Creative Memory: 读取风格指纹 + 封面素材 ──
        from backend.memory.creative import CreativeMemory

        cm = CreativeMemory(account_id, store=store)
        styles, cover_materials = await asyncio.gather(
            cm.recall_style(query=plan.get("selected_topic", "")),
            cm.recall_materials(category="封面", limit=3),
        )

        creative_ctx = cm.build_creative_context(styles, [], cover_materials)
        system_prompt = self._compile_system_prompt(state, creative_ctx)

        niche = require_niche(state)
        body_summary = copy.get("body_text", "")[:200] if copy else ""
        brief_brand = brief.get("brand_name", "") if brief else ""
        brief_requirements = brief.get("style_requirements", "") if brief else ""
        shooting_notes = brief.get("shooting_requirements", "") if brief else ""
        user_msg = f"""选题：{plan.get("selected_topic", "")}
角度：{plan.get("content_angle", "")}
内容类型：{plan.get("content_type", "note")}
垂类赛道：{niche}
正文摘要：{body_summary}
品牌：{brief_brand}
视觉要求：{brief_requirements}
拍摄要求：{shooting_notes}{shooting_ctx}"""

        response = await self._llm_ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        visual_plan = self._parse_json_response(cast(str, response.content))

        # ── Creative Memory: 沉淀风格选择 ──
        from backend.memory.types import StyleDNA

        visual_style = visual_plan.get("style_name", visual_plan.get("visual_style", ""))
        if visual_style:
            style = StyleDNA(
                visual_style=visual_style,
                color_palette=visual_plan.get("color_palette", []),
                layout_preference=visual_plan.get(
                    "layout_type", visual_plan.get("layout_preference", "")
                ),
            )
            await cm.deposit_style(style)
            # Write style_id back to visual_plan for calibration chain
            style_id = style.get("style_id", "")
            if style_id:
                visual_plan["style_id"] = style_id

        return {
            "visual_plan": visual_plan,
            "phase": WorkflowPhase.CREATING,
        }
