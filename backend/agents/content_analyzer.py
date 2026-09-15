"""Content Analyzer agent — gap analysis between draft and viral posts.

P1b-S4 迁移第六批销号（consumer-map §六.6，纯模板批）：无管线 ns recall、
system YAML 无占位符（任务数据全走 user_msg），prompt 组装接
ContextCompiler.compile_prompt（无标记整段 L0）。

P1d-S2b：差距分析迁到 ``_llm_structured`` + ``ContentAnalysisOutput``；
信封保留（提示词形状不变），旧的"缺键就手写一份空结构"删掉 ——
``normalize_optimization_analysis`` 是空分析形状的唯一来源。
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.context.compiler import ContextCompiler
from backend.context.models import RunContext
from backend.models.outputs import ContentAnalysisOutput, normalize_optimization_analysis
from backend.models.structured import StructuredOutputError
from backend.state.schema import WorkflowPhase, XHSGrowthState

logger = logging.getLogger("xhs_growth.content_analyzer")

_compiler = ContextCompiler()


class ContentAnalyzerAgent(BaseAgent):
    """对比分析 Agent."""

    def _compile_system_prompt(self, state: XHSGrowthState) -> str:
        """System prompt via ContextCompiler（S4-6 纯模板批）。

        本 agent 不读 niche（不在 consumer-map §五隐式默认清单），传 ""
        不新造默认值，统一切换留 S4-7。"""
        run_context = RunContext(
            thread_id=str(state.get("session_id") or ""),
            account_id=str(state.get("account_id", "default")),
            niche=str(state.get("niche", "")),
            values=state,
        )
        return _compiler.compile_prompt(run_context, self.prompt_template["system"]).render()

    task_type = TaskType.CONTENT_ANALYSIS
    agent_name = "content_analyzer"
    prompt_file = "content_analyzer.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        self._reset_llm_perf()
        draft: dict[str, Any] | None = cast(dict[str, Any] | None, state.get("draft_content"))
        viral_posts = state.get("viral_posts", [])

        # Build synthetic draft from shooting_plan when draft_content is empty (brief mode)
        if not draft or not draft.get("text"):
            draft = self._build_draft_from_shooting_plan(state)
            if draft:
                logger.info("Using synthetic draft from shooting_plan for analysis")

        if not draft or not draft.get("text"):
            logger.info("No draft content available, skipping analysis")
            return {
                "skip_analysis": True,
                "phase": WorkflowPhase.CREATING,
            }

        # Analyze without viral_posts too — use brief_content or content_plan as reference
        if not viral_posts:
            logger.info("No viral posts, analyzing draft against brief/strategy context")

        system_prompt = self._compile_system_prompt(state)

        # 构建爆款摘要或内容参考
        if viral_posts:
            viral_summary = self._build_viral_summary(cast(list[dict[str, Any]], viral_posts))
            context_section = f"爆款参考摘要（JSON格式）：\n{viral_summary}"
        else:
            context_section = self._build_content_context(state)

        user_msg = f"""用户草稿标题：{draft.get("title", "未提供")}
用户草稿内容：{(draft.get("text") or "")[:500]}
用户草稿标签：{", ".join(draft.get("hashtags") or [])}

{context_section}

请分析用户草稿与参考内容之间的差距，并提供优化建议。"""

        # P1d-S2b: 差距分析走结构化链。降级只接 ``StructuredOutputError``
        # （问过了但每一档都没给出可用产物 → 空分析继续，与旧的 parse 失败兜底同义）；
        # 「一次都没问到」原样上抛，不让 LLM 故障伪装成"这次没有差距"。
        try:
            output = await self._llm_structured(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_msg),
                ],
                ContentAnalysisOutput,
            )
        except StructuredOutputError as exc:
            logger.warning(
                "%s: no usable optimization analysis (%d attempt(s)); continuing empty",
                self.agent_name,
                len(exc.attempts),
            )
            output = ContentAnalysisOutput()

        # 三个键总是齐（normalize 是"空分析长什么样"的唯一来源）
        optimization_analysis = normalize_optimization_analysis(output)

        gaps_count = len(optimization_analysis["gaps"])
        suggestions_count = len(optimization_analysis["suggestions"])
        logger.info(
            f"Generated optimization analysis with "
            f"{gaps_count} gaps and {suggestions_count} suggestions"
        )

        return {
            "optimization_analysis": optimization_analysis,
            "phase": WorkflowPhase.CREATING,
        }

    def _build_draft_from_shooting_plan(self, state: XHSGrowthState) -> dict[str, Any] | None:
        """Build a synthetic draft_content from shooting_plan (brief mode)."""
        sp = state.get("shooting_plan")
        if not sp or not sp.get("body_copy"):
            return None
        titles = sp.get("title_candidates", [])
        return {
            "title": titles[0] if titles else "",
            "text": sp.get("body_copy", ""),
            "hashtags": (sp.get("required_hashtags") or []) + (sp.get("optional_hashtags") or []),
        }

    def _build_content_context(self, state: XHSGrowthState) -> str:
        """Build content reference context from brief_content / content_plan when no viral_posts."""
        parts = []
        brief = state.get("brief_content") or {}
        plan = state.get("content_plan") or {}
        if brief.get("brand_name"):
            parts.append(f"品牌: {brief['brand_name']}")
        if brief.get("selling_points"):
            parts.append(f"核心卖点: {', '.join(brief['selling_points'][:5])}")
        if brief.get("target_audience"):
            parts.append(f"目标受众: {brief['target_audience']}")
        if brief.get("content_direction"):
            parts.append(f"内容方向: {brief['content_direction'][:200]}")
        if brief.get("style_requirements"):
            parts.append(f"风格要求: {brief['style_requirements'][:100]}")
        if plan.get("selected_topic"):
            parts.append(f"选题: {plan['selected_topic']}")
        if plan.get("content_angle"):
            parts.append(f"角度: {plan['content_angle']}")
        return "内容参考上下文：\n" + "\n".join(parts) if parts else "无额外参考上下文"

    def _build_viral_summary(self, viral_posts: list[dict[str, Any]]) -> str:
        """构建爆款摘要 JSON 字符串."""
        summary_posts = []
        for post in viral_posts[:5]:  # 最多取5篇
            summary_posts.append(
                {
                    "title": post.get("title", ""),
                    "hashtags": post.get("hashtags", []),
                    "likes": post.get("likes", 0),
                    "collects": post.get("collects", 0),
                    "comments": post.get("comments", 0),
                    "engagement_rate": post.get("engagement_rate", 0),
                    "visual_style": post.get("visual_style", ""),
                    "color_palette": post.get("color_palette", {}),
                    # 简化正文，只取前200字
                    "body_preview": (post.get("body") or "")[:200],
                }
            )
        return json.dumps(summary_posts, ensure_ascii=False, indent=2)


__all__ = ["ContentAnalyzerAgent"]
