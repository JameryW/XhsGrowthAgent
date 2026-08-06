"""Copywriter agent — generates titles, body text, hashtags.

When blogger_notes are available, generates multiple style variants
(e.g. professional review, lifestyle seeding, tutorial) so the user
can choose a preferred style before optimization.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.schema import WorkflowPhase, XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.copywriter")


def _audience_pref_query(plan: Mapping[str, Any], brief: Mapping[str, Any]) -> str:
    """Build the audience-preference recall query from plan/brief."""
    kind = plan.get("content_type", "note") or brief.get("style_requirements", "note")
    return f"audience preference for {kind}"


class CopywriterAgent(BaseAgent):
    task_type = TaskType.WRITING
    agent_name = "copywriter"
    prompt_file = "copywriter.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        self._reset_llm_perf()
        account_id = state.get("account_id", "default")
        plan = state.get("content_plan", {})
        brief = state.get("brief_content") or {}
        is_brief_mode = state.get("workflow_mode") == "brief" and bool(brief)

        # ── Creative Memory: 读取 ──
        from backend.memory.creative import CreativeMemory

        cm = CreativeMemory(account_id, store=store)
        recall_query = plan.get("selected_topic", "") or brief.get("product_name", "")
        # 4 independent read-only recalls with disjoint namespaces → one
        # concurrent wave instead of 4 serial ones. Each recall swallows its
        # own exceptions internally (returns []), so gather adds no new
        # exception surface. Precedent: content_strategist.py:210.
        styles, materials, past_content, audience_prefs = await asyncio.gather(
            cm.recall_style(query=recall_query),
            cm.recall_materials(category="文案片段", tags=["高转化", "爆款标题"]),
            self._recall_memory(
                store,
                account_id,
                query=recall_query,
                namespace="content_history",
                limit=3,
            ),
            self._recall_memory(
                store,
                account_id,
                query=_audience_pref_query(plan, brief),
                namespace="audience_preferences",
                limit=3,
            ),
        )

        # 构建完整 memory context
        memory_context = ""
        if past_content:
            memory_context += "\n历史爆款参考：\n"
            for pc in past_content:
                title = pc.get("title", "")
                rate = pc.get("engagement_rate", "N/A")
                memory_context += f"- {title} (互动率: {rate})\n"
        if audience_prefs:
            memory_context += "\n受众偏好：\n"
            for ap in audience_prefs:
                memory_context += f"- {ap.get('preference', '')}\n"

        # 拼接 creative memory 上下文
        creative_ctx = cm.build_creative_context(styles, [], materials)
        if creative_ctx:
            memory_context += f"\n{creative_ctx}"

        # 创作者中心导入数据建议（trend / brief 共用召回面）
        try:
            from backend.services.creator_stats.suggestions import (
                build_mode_creative_context,
            )
            from backend.services.creator_stats.types import CreativeMode

            mode: CreativeMode = "brief" if is_brief_mode else "trend"
            stats_ctx = await build_mode_creative_context(account_id, mode, store=store)
            if stats_ctx:
                memory_context += f"\n{stats_ctx}"
        except Exception as e:
            logger.debug("creator_stats suggestions skipped: %s", e)

        system_prompt = self._build_system_prompt(state, extra_context=memory_context)

        # 构建 Ripple 传播预测上下文
        ripple_context = self._build_ripple_context(dict(plan))
        system_prompt = system_prompt.replace("{ripple_context}", ripple_context)

        # 注入评估器修订建议（RQGM 协同演化：评估器反馈驱动 writer 改进）
        feedback = state.get("human_feedback") or {}
        revisions = feedback.get("revisions") or []
        if revisions:
            hints = "\n".join(f"- {h}" for h in revisions)
            system_prompt += f"\n\n【质量评估修订要求 — 请据此重写】\n{hints}"

        niche = state.get("niche", "母婴")

        if is_brief_mode:
            # Brief mode: build user message from brief_content + blogger references
            selected_blogger = state.get("selected_blogger") or {}
            blogger_notes = state.get("blogger_notes") or []
            notes_context = ""
            for i, note in enumerate(blogger_notes[:3], 1):
                notes_context += (
                    f"\n参考笔记{i}：{note.get('title', '')}\n{(note.get('body') or '')[:500]}\n"
                )

            user_msg = f"""品牌：{brief.get("brand_name", "")}
产品：{brief.get("product_name", "")}
卖点：{", ".join((brief.get("selling_points") or [])[:5])}
内容方向：{brief.get("content_direction", "")}
目标受众：{brief.get("target_audience", "")}
风格要求：{brief.get("style_requirements", "")}
注意事项：{brief.get("notes", "")}
参考博主：{selected_blogger.get("nickname", "")}
垂类赛道：{niche}
{notes_context}"""
        else:
            # Trend mode: build from content_plan
            user_msg = f"""选题：{plan.get("selected_topic", "")}
角度：{plan.get("content_angle", "")}
目标受众：{plan.get("target_audience", "")}
内容类型：{plan.get("content_type", "note")}
垂类赛道：{niche}"""

        response = await self._llm_ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        copy_content = self._parse_json_response(cast(str, response.content))

        # ── De-AI-taste polish (workflow post-pass) ──
        # RQGM ai_taste feedback lands in human_feedback.revisions; always run a
        # polish so first drafts and revision loops both drop template-y AI copy.
        copy_content = await self._apply_de_ai_taste(
            copy_content,
            niche=str(niche or ""),
            revision_hints=[str(h) for h in revisions if h],
        )

        # ── Multi-style generation when blogger_notes exist ──
        blogger_notes = state.get("blogger_notes") or []
        content_versions: list[dict[str, Any]] = []
        if blogger_notes:
            content_versions = await self._generate_style_variants(
                state,
                copy_content,
                cast(list[dict[str, Any]], blogger_notes),
                system_prompt,
                niche,
            )
            # Variants: algorithmic only (cost control); main draft already LLM-polished.
            content_versions = self._algorithmic_de_ai_variants(content_versions)

        # ── Creative Memory: 沉淀 ──
        from backend.memory.types import MaterialEntry

        deposited_material_ids: list[str] = []

        selected_title = copy_content.get("selected_title", "")
        if selected_title:
            title_entry = MaterialEntry(
                category="标题模板",
                content=selected_title,
                source_post_id="",
                tags=["auto_deposit", "标题"],
            )
            await cm.deposit_material(title_entry)
            mid = title_entry.get("material_id", "")
            if mid:
                deposited_material_ids.append(mid)

        body_text = copy_content.get("body_text", "")
        if body_text:
            opening = body_text[:100]
            opening_entry = MaterialEntry(
                category="文案片段",
                content=opening,
                source_post_id="",
                tags=["auto_deposit", "开头"],
            )
            await cm.deposit_material(opening_entry)
            mid = opening_entry.get("material_id", "")
            if mid:
                deposited_material_ids.append(mid)

        # Write material IDs back to copy_content for calibration chain
        if deposited_material_ids:
            copy_content["used_material_ids"] = deposited_material_ids

        result: dict[str, Any] = {
            "copy_content": copy_content,
            "phase": WorkflowPhase.CREATING,
        }
        if content_versions:
            result["content_versions"] = content_versions
        return result

    async def _generate_style_variants(
        self,
        state: XHSGrowthState,
        base_copy: dict[str, Any],
        blogger_notes: list[dict[str, Any]],
        system_prompt: str,
        niche: str,
    ) -> list[dict[str, Any]]:
        """Generate multiple style variants based on blogger reference notes.

        Returns a list of content versions, each with a distinct style
        derived from the blogger notes' characteristics.
        """
        brief = state.get("brief_content") or {}
        plan = state.get("content_plan") or {}
        is_brief_mode = state.get("workflow_mode") == "brief" and bool(brief)

        # Build blogger notes context
        notes_context = ""
        for i, note in enumerate(blogger_notes[:3], 1):
            notes_context += (
                f"\n参考笔记{i}：{note.get('title', '')}\n{(note.get('body') or '')[:300]}\n"
            )

        # Build context string
        if is_brief_mode:
            context_info = f"""品牌：{brief.get("brand_name", "")}
产品：{brief.get("product_name", "")}
卖点：{", ".join((brief.get("selling_points") or [])[:5])}
内容方向：{brief.get("content_direction", "")}
目标受众：{brief.get("target_audience", "")}
风格要求：{brief.get("style_requirements", "")}"""
        else:
            context_info = f"""选题：{plan.get("selected_topic", "")}
角度：{plan.get("content_angle", "")}
目标受众：{plan.get("target_audience", "")}
垂类赛道：{niche}"""

        variant_prompt = f"""基于以上参考博主笔记，请生成3个不同风格的笔记版本。

{context_info}

参考博主笔记：
{notes_context}

每个版本必须风格明显不同，建议参考以下风格维度（可根据博主笔记特征调整）：
- 风格A：专业测评风 — 数据驱动、理性分析、对比测评
- 风格B：生活种草风 — 沉浸体验、情感共鸣、场景代入
- 风格C：教程干货风 — 步骤清晰、实用技巧、避坑指南

请输出JSON：
{{
  "variants": [
    {{
      "version_id": "style_a",
      "style_name": "风格名称",
      "title": "标题（含emoji，≤20字）",
      "body": "正文（400-600字）",
      "hashtags": ["#标签1", "#标签2"],
      "tone": "语气描述",
      "style_suggestion": "视觉风格建议",
      "visual_style": "视觉风格关键词",
      "color_palette": {{"primary": "#hex", "secondary": "#hex", "accent": "#hex"}}
    }},
    ...
  ]
}}"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=variant_prompt),
        ]

        response = await self._llm_ainvoke(messages)

        raw_response = cast(str, response.content)
        parsed = self._parse_json_response(raw_response)
        variants = parsed.get("variants", [])

        # Retry once if the LLM returned no parseable variants (transient format
        # errors are common). Log the raw snippet to aid diagnosis.
        if not variants:
            logger.warning(
                f"copywriter style variants empty on first attempt: {raw_response[:200]}"
            )
            retry_response = await self._llm_ainvoke(messages)
            raw_response = cast(str, retry_response.content)
            parsed = self._parse_json_response(raw_response)
            variants = parsed.get("variants", [])
            if not variants:
                logger.error(f"copywriter style variants empty after retry: {raw_response[:200]}")

        # Ensure each variant has a version_id
        for v in variants:
            if not v.get("version_id"):
                v["version_id"] = str(uuid.uuid4())[:8]

        return cast(list[dict[str, Any]], variants)

    @staticmethod
    def _build_ripple_context(plan: dict[str, Any]) -> str:
        """从 content_plan 中提取 Ripple 数据构建 prompt 上下文"""
        prediction = plan.get("ripple_prediction")
        pmf = plan.get("ripple_pmf")

        if not prediction and not pmf:
            return ""

        lines = ["\nRipple 传播预测数据："]
        if prediction:
            lines.append(f"- 预计触达: {prediction.get('estimated_reach', 'N/A')}")
            lines.append(f"- 预计互动: {prediction.get('estimated_engagement', 'N/A')}")
            lines.append(f"- 爆发概率: {prediction.get('viral_probability', 'N/A')}")
        if pmf:
            if pmf.get("risk_factors"):
                lines.append(f"- PMF 风险: {', '.join(pmf['risk_factors'])}")
            if pmf.get("improvement_strategies"):
                lines.append(f"- 改进建议: {', '.join(pmf['improvement_strategies'])}")

        return "\n".join(lines)

    async def _apply_de_ai_taste(
        self,
        copy_content: dict[str, Any],
        *,
        niche: str = "",
        revision_hints: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run de_ai_taste polish on generated copy; never fail the node."""
        if not isinstance(copy_content, dict):
            return copy_content
        title = str(copy_content.get("selected_title") or copy_content.get("title") or "").strip()
        body = str(copy_content.get("body_text") or copy_content.get("body") or "").strip()
        if not title and not body:
            return copy_content
        try:
            from backend.tools.content.de_ai_taste import polish_copy

            polished = await polish_copy(
                selected_title=title,
                body_text=body,
                cta=str(copy_content.get("cta") or ""),
                tone=str(copy_content.get("tone") or ""),
                niche=niche,
                revision_hints=list(revision_hints or []),
                use_llm=True,
            )
        except Exception as e:
            logger.warning("de_ai_taste polish skipped: %s", e)
            return copy_content

        if not isinstance(polished, dict):
            return copy_content

        out = dict(copy_content)
        if polished.get("selected_title"):
            out["selected_title"] = polished["selected_title"]
            # Keep title_candidates coherent when first candidate matched old title.
            candidates = out.get("title_candidates")
            if isinstance(candidates, list) and candidates and str(candidates[0]) == title:
                candidates = [polished["selected_title"], *candidates[1:]]
                out["title_candidates"] = candidates
        if polished.get("body_text"):
            out["body_text"] = polished["body_text"]
        if polished.get("cta") is not None and str(polished.get("cta") or "").strip():
            out["cta"] = polished["cta"]
        if polished.get("tone"):
            out["tone"] = polished["tone"]
        if polished.get("changes"):
            out["de_ai_changes"] = polished["changes"]
        if polished.get("ai_signals_found"):
            out["de_ai_signals"] = polished["ai_signals_found"]
        out["de_ai_polished"] = bool(polished.get("polished"))
        out["de_ai_method"] = str(polished.get("method") or "")
        return out

    @staticmethod
    def _algorithmic_de_ai_variants(
        variants: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Cheap cliché scrub for multi-style variants (no extra LLM calls)."""
        if not variants:
            return variants
        try:
            from backend.tools.content.de_ai_taste import algorithmic_de_ai
        except Exception:
            return variants

        polished_variants: list[dict[str, Any]] = []
        for variant in variants:
            if not isinstance(variant, dict):
                polished_variants.append(variant)
                continue
            result = algorithmic_de_ai(
                {
                    "selected_title": variant.get("title") or "",
                    "body_text": variant.get("body") or "",
                    "cta": variant.get("cta") or "",
                    "tone": variant.get("tone") or "",
                }
            )
            item = dict(variant)
            if result.get("selected_title"):
                item["title"] = result["selected_title"]
            if result.get("body_text"):
                item["body"] = result["body_text"]
            if result.get("cta"):
                item["cta"] = result["cta"]
            polished_variants.append(item)
        return polished_variants
