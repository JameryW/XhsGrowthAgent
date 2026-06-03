"""Shooting Planner agent — generates shooting plan from parsed brief + viral references."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.shooting_planner")


class ShootingPlannerAgent(BaseAgent):
    task_type = TaskType.SHOOTING_PLAN
    agent_name = "shooting_planner"
    prompt_file = "shooting_planner.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        brief = state.get("brief_content", {})
        viral_refs = state.get("viral_posts", [])

        if not brief:
            return {
                "error": "No brief content available for shooting plan",
                "phase": WorkflowPhase.ERROR,
            }

        system_prompt = self._build_system_prompt(state)

        # Build viral reference context
        viral_context = ""
        if viral_refs:
            viral_context = "\n\n参考爆款笔记：\n"
            for i, post in enumerate(viral_refs[:5], 1):
                title = post.get('title', 'N/A')
                eng = post.get('engagement', 'N/A')
                viral_context += f"\n{i}. {title} — 互动量: {eng}\n"
                style = post.get('style', 'N/A')
                scene = post.get('scene', 'N/A')
                viral_context += f"   风格: {style} | 场景: {scene}\n"

        user_msg = f"""请根据以下商单 brief 生成拍摄计划：

品牌：{brief.get('brand_name', 'N/A')}
产品：{brief.get('product_name', 'N/A')}
规格：{brief.get('product_specs', [])}
必提卖点：{brief.get('selling_points', [])}
必含关键词：{brief.get('required_keywords', [])}
内容方向：{brief.get('content_direction', 'N/A')}
目标受众：{brief.get('target_audience', 'N/A')}
风格要求：{brief.get('style_requirements', 'N/A')}
拍摄要求：{brief.get('shooting_requirements', 'N/A')}
注意事项：{brief.get('notes', [])}
{viral_context}

请输出 JSON 格式的拍摄计划，包含以下字段：
- creator_nickname: 达人昵称（留空，由用户填写）
- content_direction: 内容方向
- content_type_label: 图文内容标签（如"几素Life3/4"）
- profile_link: 主页链接（留空）
- creator_level: 达人量级（留空）
- planned_publish_date: 预计发布日期（留空）
- product_specification: 产品规格描述
- draft_requirements: 初稿要求列表
- draft_notes: 初稿注意事项列表
- title_candidates: 标题备选（至少2个）
- body_copy: 文案（需包含必提卖点和必含关键词）
- required_hashtags: 必带话题
- optional_hashtags: 选带话题
- suggested_hashtags: 建议的热门话题
- outfits: 拍摄服装建议 {{角色: [服装选项]}}
- shooting_angles: 拍摄角度建议 [{{description: 描述}}]"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        parsed = self._parse_json_response(response.content)

        result: dict[str, Any] = {
            "shooting_plan": parsed,
            "phase": WorkflowPhase.CREATING,
        }

        return result


__all__ = ["ShootingPlannerAgent"]
