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
from backend.models.outputs import VisualPlanOutput, normalize_visual_plan
from backend.services.visual_memory import (
    apply_directive,
    build_directive,
    directive_prompt,
    ensure_dna,
    scene_for,
    visual_memory_enabled,
)
from backend.state.schema import WorkflowPhase, XHSGrowthState

_compiler = ContextCompiler()


def _visual_plan_has_content(output: VisualPlanOutput) -> str | None:
    """Reject a plan that names no cover and no images.

    The schema cannot do this on its own: ``{"raw_content": "…"}`` validates
    against an all-defaults model, so prose would land in ``visual_plan`` as
    eight empty fields — and the node would report success while the user gets
    a note with no cover prompt. Raising instead hands the call to
    ``BaseAgent.__call__``, which returns the error state for the stateful
    retry this failure is worth. ``cover_prompt``/``image_prompts``/
    ``visual_style`` is the whole of what this agent exists to produce.
    """
    if output.cover_prompt.strip() or output.image_prompts or output.visual_style.strip():
        return None
    return (
        "上一次回答里 cover_prompt、image_prompts、visual_style 都是空的。"
        "请严格按 JSON 规范重新输出完整的视觉计划。"
    )


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
        # ── Visual memory (#45): account anchors must survive across weeks ──
        # Off by default: with the switch off nothing is read, nothing is added
        # to the prompt and the plan keeps exactly its previous shape.
        visual_directive: dict[str, Any] | None = None
        memory_ctx = ""
        if visual_memory_enabled():
            visual_directive = await build_directive(
                store,
                account_id,
                scene_for(
                    niche=str(niche or ""),
                    content_type=str(plan.get("content_type", "")),
                ),
            )
            memory_ctx = f"\n{directive_prompt(visual_directive)}"
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
拍摄要求：{shooting_notes}{shooting_ctx}{memory_ctx}"""

        visual_plan = normalize_visual_plan(
            await self._llm_structured(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_msg),
                ],
                VisualPlanOutput,
                validator=_visual_plan_has_content,
            )
        )

        # ── Multimodal synergy gate (IDProxy-style cold-start check) ──
        # A failed first pass is sent back to the same visual-designer prompt
        # once with the concrete recommendations.  This is the production
        # "打回 visual_designer" path; review_gate also treats a still-failing
        # plan as high risk so it can never auto-approve.
        from backend.services.content_launch import evaluate_multimodal_synergy

        title = str(copy.get("selected_title") or copy.get("title") or "")
        body = str(copy.get("body_text") or copy.get("body") or "")
        synergy = evaluate_multimodal_synergy(title, body, visual_plan, niche=str(niche or ""))
        synergy_attempts = 1
        if not synergy.passed:
            feedback = "\n".join(f"- {item}" for item in synergy.recommendations)
            retry_msg = (
                f"{user_msg}\n\n"
                "上一次视觉方案未通过图文协同检查，请按以下要求修正后重新输出：\n"
                f"{feedback}"
            )
            visual_plan = normalize_visual_plan(
                await self._llm_structured(
                    [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=retry_msg),
                    ],
                    VisualPlanOutput,
                    validator=_visual_plan_has_content,
                )
            )
            synergy = evaluate_multimodal_synergy(title, body, visual_plan, niche=str(niche or ""))
            synergy_attempts = 2

        visual_plan["multimodal_synergy"] = synergy.as_dict()
        visual_plan["synergy_attempts"] = synergy_attempts
        if not synergy.passed:
            visual_plan["synergy_blocked"] = True
            visual_plan["revision_hints"] = [
                *list(visual_plan.get("revision_hints") or []),
                *synergy.recommendations,
            ]

        # ── Visual memory (#45): fill gaps, report drift, freeze DNA on run 1 ──
        if visual_directive is not None:
            report = apply_directive(visual_plan, visual_directive)
            if report["drift"]:
                visual_plan["revision_hints"] = [
                    *list(visual_plan.get("revision_hints") or []),
                    f"视觉记忆漂移：{'、'.join(report['drift'])}（与账号品牌 DNA 不一致）",
                ]
            # First run establishes the anchors from what the designer actually
            # produced; later runs return the frozen DNA untouched.
            await ensure_dna(
                store,
                account_id,
                palette=[str(item) for item in visual_plan.get("color_palette") or []],
                title_weight_ratio=visual_plan.get("title_weight_ratio"),
            )

        # ── Carousel dwell-time arc (P1 hook → P2 conclusion → PN save list) ──
        prompts = list(
            visual_plan.get("carousel_prompts") or visual_plan.get("image_prompts") or []
        )
        if prompts:
            from backend.services.distribution_contracts import plan_carousel

            slides = plan_carousel(len(prompts))
            visual_plan["carousel_plan"] = [
                {
                    **slide.as_dict(),
                    "prompt": str(prompts[slide.index - 1]) if slide.index <= len(prompts) else "",
                }
                for slide in slides
            ]
            # AVTP: the visual budget follows the retention arc, so downstream
            # image generation consumes the plan rather than the flat prompt list.
            visual_plan["avtp_token_budget"] = sum(slide.token_budget for slide in slides)
            visual_plan["image_prompts"] = [
                f"{slide.purpose}：{prompts[slide.index - 1]}"
                for slide in slides
                if slide.index <= len(prompts)
            ]

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
