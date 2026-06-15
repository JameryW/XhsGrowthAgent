"""版本生成 Agent.

基于对比分析结果，生成 A/B/C 三版优化内容：
- A 版：保守优化，小幅改动，保持原有风格
- B 版：平衡优化，适度融合爆款特征
- C 版：激进优化，大幅重组，最大化爆款潜力
"""

from __future__ import annotations

import logging
from typing import Any

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
        draft = state.get("draft_content")
        analysis = state.get("optimization_analysis")

        # Build synthetic draft from shooting_plan when draft_content is empty (brief mode)
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

        # 构建差距和建议字符串
        gaps = analysis.get("gaps", [])
        gaps_str = "\n".join([
            f"- [{g.get('severity', '中')}] {g.get('dimension', '')}: {g.get('description', '')}"
            for g in gaps[:5]
        ]) or "无差距分析"

        suggestions = analysis.get("suggestions", [])
        suggestions_str = "\n".join([
            f"- [P{s.get('priority', 3)}] {s.get('dimension', '')}: "
            f"{s.get('action', '')} ({s.get('reasoning', '')})"
            for s in suggestions[:5]
        ]) or "无优化建议"

        viral_patterns = analysis.get("viral_patterns", [])
        patterns_str = "\n".join([f"- {p}" for p in viral_patterns[:5]]) or "无爆款模式"

        # 构建系统提示
        system_prompt = self._build_system_prompt(state)

        # 构建用户消息
        user_msg = f"""原始草稿标题：{draft.get('title', '未提供')}
原始草稿正文：{draft.get('text', '')[:800]}
原始标签：{', '.join(draft.get('hashtags', [])) or '无'}
原始风格建议：{draft.get('style_suggestion', '未提供')}

差距分析：
{gaps_str}

优化建议：
{suggestions_str}

爆款模式：
{patterns_str}
"""

        # 调用 LLM
        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        # 解析响应
        result = self._parse_json_response(response.content)
        versions = result.get("versions", [])

        logger.info(f"Generated {len(versions)} content versions (A/B/C)")

        # When only 1 version is generated, auto-apply it to copy_content and
        # visual_plan so the result isn't lost when should_present_choice skips
        # choice_gate and routes directly to visual_designer.
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
            "hashtags": (sp.get("required_hashtags", []) or []) + (sp.get("optional_hashtags", []) or []),
        }