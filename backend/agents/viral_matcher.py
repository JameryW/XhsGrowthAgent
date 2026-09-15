"""Viral Matcher agent — matches viral posts for comparison.

P1b-S4 迁移第六批销号（consumer-map §六.6，纯模板批）：无管线 ns recall、
system YAML 无占位符（任务数据全走 user_msg），prompt 组装接
ContextCompiler.compile_prompt（无标记整段 L0）。

P1d-S2b：爆款匹配迁到 ``_llm_structured`` + ``ViralPostsOutput``
（裸数组与 ``{"viral_posts": [...]}`` 两种拼法都收）；失败仍然降级成
"无参考笔记 + optimization_error"，见 ``execute`` 内注释。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.context.compiler import ContextCompiler
from backend.context.models import RunContext
from backend.models.outputs import ViralPostsOutput, normalize_viral_posts
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.viral_matcher")

_compiler = ContextCompiler()


class ViralMatcherAgent(BaseAgent):
    """爆款匹配 Agent."""

    task_type = TaskType.VIRAL_MATCHING
    agent_name = "viral_matcher"
    prompt_file = "viral_matcher.yaml"

    def _compile_system_prompt(self, state: XHSGrowthState) -> str:
        """System prompt via ContextCompiler（S4-6 纯模板批）。本 agent 不读
        niche（不在 consumer-map §五隐式默认清单），传 "" 不新造默认值。"""
        run_context = RunContext(
            thread_id=str(state.get("session_id") or ""),
            account_id=str(state.get("account_id", "default")),
            niche=str(state.get("niche", "")),
            values=state,
        )
        return _compiler.compile_prompt(run_context, self.prompt_template["system"]).render()

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        self._reset_llm_perf()
        draft = state.get("draft_content")
        brief = state.get("brief_content")
        has_draft = draft and draft.get("text")
        has_brief = brief and (brief.get("raw_text") or brief.get("brand_name"))

        if not has_draft and not has_brief:
            logger.info("No draft or brief content provided, skipping viral matching")
            return {
                "viral_posts": [],
                "skip_optimization": False,
                "phase": WorkflowPhase.CREATING,
            }

        user_links = state.get("user_viral_links", [])

        # Build auto-search keywords from trend data, content plan, and brief
        trend_data = state.get("trend_data", {})
        content_plan = state.get("content_plan", {})
        auto_keywords: list[str] = list(trend_data.get("trending_keywords", []))
        if selected_topic := content_plan.get("selected_topic"):
            auto_keywords.append(selected_topic)

        # Brief mode: derive keywords and context from brief_content
        if has_brief:
            assert brief is not None
            if brand := brief.get("brand_name"):
                auto_keywords.append(brand)
            if product := brief.get("product_name"):
                auto_keywords.append(product)
            auto_keywords.extend((brief.get("required_keywords") or [])[:3])
            auto_keywords.extend((brief.get("selling_points") or [])[:2])

        system_prompt = self._compile_system_prompt(state)

        if has_draft:
            assert draft is not None
            user_msg = f"""用户草稿标题：{draft.get("title", "未提供")}
用户草稿内容：{(draft.get("text") or "")[:500]}
用户指定爆款链接：{", ".join(user_links) if user_links else "无"}
自动搜索关键词：{", ".join(auto_keywords[:5]) if auto_keywords else "无"}"""
        else:
            # Brief mode: describe what we're looking for from brief context
            assert brief is not None
            brief_ctx = f"品牌：{brief.get('brand_name', '未提供')}"
            if brief.get("product_name"):
                brief_ctx += f"\n产品：{brief.get('product_name')}"
            if brief.get("content_direction"):
                brief_ctx += f"\n内容方向：{brief.get('content_direction')}"
            if brief.get("selling_points"):
                brief_ctx += f"\n核心卖点：{', '.join((brief.get('selling_points') or [])[:3])}"
            if brief.get("target_audience"):
                brief_ctx += f"\n目标受众：{brief.get('target_audience')}"
            user_msg = f"""商单模式 — 根据品牌Brief搜索相关爆款笔记参考
{brief_ctx}
用户指定爆款链接：{", ".join(user_links) if user_links else "无"}
自动搜索关键词：{", ".join(auto_keywords[:5]) if auto_keywords else "无"}"""

        # P1d-S2b: 爆款匹配走结构化链，但**降级语义刻意与 analyst 相反** ——
        # 这里连「一次都没问到」也一起兜住，因为爆款参考是本节点唯一的可选产出：
        # 拿不到就没有参考笔记，而失败**被贴了标签**（``optimization_error``）进
        # state，不是被伪装成"这次没搜到爆款"。analyst 那边不同：空快照带着
        # engagement_rate=0.0 进报表，与一次真实的零表现无法区分，所以那里必须上抛。
        try:
            output = await self._llm_structured(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_msg),
                ],
                ViralPostsOutput,
            )
        except Exception as e:
            logger.warning(
                "Viral matching failed; skipping optional optimization: %s",
                e,
            )
            return {
                "viral_posts": [],
                "skip_optimization": False,
                "optimization_error": f"viral_matcher skipped: {e}",
                "phase": WorkflowPhase.CREATING,
            }

        viral_posts = normalize_viral_posts(output)

        logger.info(f"Found {len(viral_posts)} viral posts for comparison")

        return {
            "viral_posts": viral_posts,
            "skip_optimization": False,
            "phase": WorkflowPhase.CREATING,
        }


__all__ = ["ViralMatcherAgent"]
