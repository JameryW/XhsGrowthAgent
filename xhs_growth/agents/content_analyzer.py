"""Content Analyzer agent — gap analysis between draft and viral posts."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase

logger = logging.getLogger("xhs_growth.content_analyzer")


class ContentAnalyzerAgent(BaseAgent):
    """对比分析 Agent."""

    task_type = TaskType.CONTENT_ANALYSIS
    agent_name = "content_analyzer"
    prompt_file = "content_analyzer.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        draft = state.get("draft_content")
        viral_posts = state.get("viral_posts", [])

        # 无草稿或无爆款参考时跳过分析
        if not draft or not draft.get("text"):
            logger.info("No draft content provided, skipping analysis")
            return {
                "skip_analysis": True,
                "phase": WorkflowPhase.CREATING,
            }

        if not viral_posts or len(viral_posts) == 0:
            logger.info("No viral posts provided, skipping analysis")
            return {
                "skip_analysis": True,
                "phase": WorkflowPhase.CREATING,
            }

        account_id = state.get("account_id", "default")
        system_prompt = self._build_system_prompt(state)

        # 构建爆款摘要 JSON
        viral_summary = self._build_viral_summary(viral_posts)

        user_msg = f"""用户草稿标题：{draft.get('title', '未提供')}
用户草稿内容：{draft.get('text', '')[:500]}
用户草稿标签：{', '.join(draft.get('hashtags', []))}

爆款参考摘要（JSON格式）：
{viral_summary}

请分析用户草稿与爆款笔记之间的差距，并提供优化建议。"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        result = self._parse_json_response(response.content)
        optimization_analysis = result.get("optimization_analysis", {})

        # 确保返回正确的结构
        if not optimization_analysis:
            optimization_analysis = {
                "gaps": [],
                "suggestions": [],
                "viral_patterns": [],
            }

        logger.info(f"Generated optimization analysis with {len(optimization_analysis.get('gaps', []))} gaps and {len(optimization_analysis.get('suggestions', []))} suggestions")

        return {
            "optimization_analysis": optimization_analysis,
            "phase": WorkflowPhase.CREATING,
        }

    def _build_viral_summary(self, viral_posts: list[dict]) -> str:
        """构建爆款摘要 JSON 字符串."""
        summary_posts = []
        for post in viral_posts[:5]:  # 最多取5篇
            summary_posts.append({
                "title": post.get("title", ""),
                "hashtags": post.get("hashtags", []),
                "likes": post.get("likes", 0),
                "collects": post.get("collects", 0),
                "comments": post.get("comments", 0),
                "engagement_rate": post.get("engagement_rate", 0),
                "visual_style": post.get("visual_style", ""),
                "color_palette": post.get("color_palette", {}),
                # 简化正文，只取前200字
                "body_preview": post.get("body", "")[:200],
            })
        return json.dumps(summary_posts, ensure_ascii=False, indent=2)


__all__ = ["ContentAnalyzerAgent"]