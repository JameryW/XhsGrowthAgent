"""Viral Matcher agent — matches viral posts for comparison."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.schema import XHSGrowthState, WorkflowPhase

logger = logging.getLogger("xhs_growth.viral_matcher")


class ViralMatcherAgent(BaseAgent):
    """爆款匹配 Agent."""

    task_type = TaskType.VIRAL_MATCHING
    agent_name = "viral_matcher"
    prompt_file = "viral_matcher.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        draft = state.get("draft_content")

        # 无草稿时跳过优化
        if not draft or not draft.get("text"):
            logger.info("No draft content provided, skipping optimization")
            return {
                "skip_optimization": True,
                "phase": WorkflowPhase.CREATING,
            }

        account_id = state.get("account_id", "default")
        user_links = state.get("user_viral_links", [])

        # 获取自动搜索关键词（来自趋势或策略）
        trend_data = state.get("trend_data", {})
        content_plan = state.get("content_plan", {})
        auto_keywords = list(trend_data.get("trending_keywords", []))
        if content_plan.get("selected_topic"):
            auto_keywords.append(content_plan.get("selected_topic"))

        system_prompt = self._build_system_prompt(state)

        user_msg = f"""用户草稿标题：{draft.get('title', '未提供')}
用户草稿内容：{draft.get('text', '')[:500]}
用户指定爆款链接：{', '.join(user_links) if user_links else '无'}
自动搜索关键词：{', '.join(auto_keywords[:5]) if auto_keywords else '无'}"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        result = self._parse_json_response(response.content)
        viral_posts = result.get("viral_posts", [])

        logger.info(f"Found {len(viral_posts)} viral posts for comparison")

        return {
            "viral_posts": viral_posts,
            "phase": WorkflowPhase.CREATING,
        }


__all__ = ["ViralMatcherAgent"]