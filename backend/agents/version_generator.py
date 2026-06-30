"""版本生成 Agent.

Two modes of operation:
1. Standard (no style_selected): uses draft_content + optimization_analysis
   to generate conservative/balanced/aggressive A/B/C variants.
2. Style-selected (style_selected=True): uses draft_content (from the
   user's style choice) as the base, generating A/B/C variants that
   preserve the selected style while varying optimization intensity.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.schema import WorkflowPhase, XHSGrowthState

logger = logging.getLogger(__name__)


class VersionGeneratorAgent(BaseAgent):
    """版本生成 Agent."""

    task_type = TaskType.VERSION_GEN
    agent_name = "version_generator"
    prompt_file = "version_generator.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        """执行版本生成."""
        style_selected = state.get("style_selected", False)
        draft = cast("dict[str, Any] | None", state.get("draft_content"))
        analysis = cast("dict[str, Any] | None", state.get("optimization_analysis"))

        # Style-selected mode: draft_content comes from selected style variant
        if style_selected and draft and draft.get("text"):
            return await self._generate_from_selected_style(state, draft, analysis)

        # Standard mode: build synthetic draft from shooting_plan when draft_content is empty
        if not draft or not draft.get("text"):
            draft = self._build_draft_from_shooting_plan(state)
            if draft:
                logger.info("Using synthetic draft from shooting_plan for version generation")

        # 缺少草稿时返回空版本
        if not draft or not draft.get("text"):
            logger.info("No draft content available, skipping version generation")
            return {
                "content_versions": [],
                "phase": WorkflowPhase.CREATING,
            }

        if not analysis:
            logger.info("No optimization analysis provided, skipping version generation")
            return {
                "content_versions": [],
                "phase": WorkflowPhase.CREATING,
            }

        return await self._generate_from_analysis(state, draft, analysis)

    async def _generate_from_selected_style(
        self,
        state: XHSGrowthState,
        draft: dict[str, Any],
        analysis: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Generate A/B/C variants based on the user-selected style.

        The draft_content already contains the style the user chose.
        Generate conservative/balanced/aggressive versions that keep
        the style but vary optimization intensity.
        """
        system_prompt = self._build_system_prompt(state)

        # Build analysis context (may be partial for brief mode)
        analysis_ctx = ""
        if analysis:
            gaps = analysis.get("gaps", [])
            suggestions = analysis.get("suggestions", [])
            viral_patterns = analysis.get("viral_patterns", [])
            gaps_str = (
                "\n".join(
                    [
                        f"- [{g.get('severity', '中')}] "
                        f"{g.get('dimension', '')}: {g.get('description', '')}"
                        for g in gaps[:5]
                    ]
                )
                or "无差距分析"
            )
            suggestions_str = (
                "\n".join(
                    [
                        f"- [P{s.get('priority', 3)}] {s.get('dimension', '')}: "
                        f"{s.get('action', '')} ({s.get('reasoning', '')})"
                        for s in suggestions[:5]
                    ]
                )
                or "无优化建议"
            )
            patterns_str = "\n".join([f"- {p}" for p in viral_patterns[:5]]) or "无爆款模式"
            analysis_ctx = f"""
差距分析：
{gaps_str}

优化建议：
{suggestions_str}

爆款模式：
{patterns_str}"""

        user_msg = f"""用户已选择一种笔记风格，请基于该风格生成3个优化版本。

选中的风格草稿标题：{draft.get("title", "未提供")}
选中的风格草稿正文：{(draft.get("text") or "")[:800]}
选中的风格标签：{", ".join(draft.get("hashtags") or []) or "无"}
选中的风格视觉建议：{draft.get("style_suggestion", "未提供")}
{analysis_ctx}

请保持选中风格的整体调性，生成3个版本：
- A版：保守优化 — 微调标题钩子、少量增删、保持原文节奏
- B版：平衡优化 — 适度强化爆款特征、优化结构、增强CTA
- C版：激进优化 — 大幅重组开头、最大化互动触发点、强化争议性

请输出JSON：
{{
  "versions": [
    {{
      "version_id": "a",
      "version_type": "conservative",
      "title": "标题（含emoji，≤20字）",
      "body": "正文内容",
      "hashtags": ["#标签1", "#标签2"],
      "tone": "语气描述",
      "style_suggestion": "视觉风格建议",
      "visual_style": "视觉风格关键词",
      "color_palette": {{ "primary": "#hex", "secondary": "#hex", "accent": "#hex" }}
    }},
    ...
  ]
}}"""

        response = await self.model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        content = response.content
        if isinstance(content, list):
            content = str(content)
        parsed = self._parse_json_response(content)
        versions = parsed.get("versions", [])

        # Ensure version_ids
        for v in versions:
            if not v.get("version_id"):
                v["version_id"] = str(uuid.uuid4())[:8]

        logger.info(f"Generated {len(versions)} versions from selected style (A/B/C)")

        updates: dict[str, Any] = {
            "content_versions": versions,
            "phase": WorkflowPhase.CREATING,
        }
        # Auto-apply single version
        if len(versions) == 1:
            v = versions[0]
            updates["copy_content"] = {
                **(state.get("copy_content") or {}),
                "selected_title": v.get("title", ""),
                "title_candidates": [v.get("title", "")],
                "body_text": v.get("body", ""),
                "hashtags": v.get("hashtags", []),
                "tone": v.get("tone", ""),
            }
            updates["visual_plan"] = {
                "cover_prompt": v.get("style_suggestion", ""),
                "style": v.get("visual_style", ""),
                "color_palette": v.get("color_palette", {}),
            }

        return updates

    async def _generate_from_analysis(
        self,
        state: XHSGrowthState,
        draft: dict[str, Any],
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        """Standard A/B/C generation from optimization analysis (original logic)."""
        # 构建差距和建议字符串
        gaps = analysis.get("gaps", [])
        gaps_str = (
            "\n".join(
                [
                    f"- [{g.get('severity', '中')}]"
                    f" {g.get('dimension', '')}: {g.get('description', '')}"
                    for g in gaps[:5]
                ]
            )
            or "无差距分析"
        )

        suggestions = analysis.get("suggestions", [])
        suggestions_str = (
            "\n".join(
                [
                    f"- [P{s.get('priority', 3)}] {s.get('dimension', '')}: "
                    f"{s.get('action', '')} ({s.get('reasoning', '')})"
                    for s in suggestions[:5]
                ]
            )
            or "无优化建议"
        )

        viral_patterns = analysis.get("viral_patterns", [])
        patterns_str = "\n".join([f"- {p}" for p in viral_patterns[:5]]) or "无爆款模式"

        # 构建系统提示
        system_prompt = self._build_system_prompt(state)

        # 构建用户消息
        user_msg = f"""原始草稿标题：{draft.get("title", "未提供")}
原始草稿正文：{(draft.get("text") or "")[:800]}
原始标签：{", ".join(draft.get("hashtags") or []) or "无"}
原始风格建议：{draft.get("style_suggestion", "未提供")}

差距分析：
{gaps_str}

优化建议：
{suggestions_str}

爆款模式：
{patterns_str}
"""

        # 调用 LLM
        response = await self.model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        # 解析响应
        content = response.content
        if isinstance(content, list):
            content = str(content)
        result = self._parse_json_response(content)
        versions = result.get("versions", [])

        # Ensure version_ids
        for v in versions:
            if not v.get("version_id"):
                v["version_id"] = str(uuid.uuid4())[:8]

        logger.info(f"Generated {len(versions)} content versions (A/B/C)")

        # When only 1 version is generated, auto-apply it
        updates: dict[str, Any] = {
            "content_versions": versions,
            "phase": WorkflowPhase.CREATING,
        }
        if len(versions) == 1:
            v = versions[0]
            updates["copy_content"] = {
                **(state.get("copy_content") or {}),
                "selected_title": v.get("title", ""),
                "title_candidates": [v.get("title", "")],
                "body_text": v.get("body", ""),
                "hashtags": v.get("hashtags", []),
                "tone": v.get("tone", ""),
            }
            updates["visual_plan"] = {
                "cover_prompt": v.get("style_suggestion", ""),
                "style": v.get("visual_style", ""),
                "color_palette": v.get("color_palette", {}),
            }

        return updates

    def _build_draft_from_shooting_plan(self, state: XHSGrowthState) -> dict[str, Any] | None:
        """Build a synthetic draft_content from shooting_plan (brief mode)."""
        sp = state.get("shooting_plan")
        if not sp or not sp.get("body_copy"):
            return None
        titles = sp.get("title_candidates", [])
        return {
            "title": titles[0] if titles else "",
            "text": sp.get("body_copy", ""),
            "hashtags": (sp.get("required_hashtags", []) or [])
            + (sp.get("optional_hashtags", []) or []),
        }
