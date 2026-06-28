"""Shooting Planner agent — generates shooting plan from brief
(brief mode) or content strategy (trend mode)."""

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
        content_plan = state.get("content_plan", {})
        copy_content = state.get("copy_content", {})
        trend_data = state.get("trend_data", {})
        viral_refs = state.get("viral_posts", [])

        # Determine mode and build prompt
        if brief and brief.get("raw_text"):
            user_msg = self._build_brief_prompt(brief, viral_refs)
        elif content_plan and content_plan.get("selected_topic"):
            user_msg = self._build_trend_prompt(content_plan, copy_content, trend_data, viral_refs)
        elif copy_content and (copy_content.get("selected_title") or copy_content.get("body_text")):
            # ponytail: fallback — content_plan may be empty in older workflows
            # that ran before content_plan was persisted; copy_content is sufficient
            user_msg = self._build_trend_prompt(content_plan, copy_content, trend_data, viral_refs)
        else:
            logger.info("No brief, content plan, or copy content available, skipping shooting plan")
            return {
                "shooting_plan": {},
                "phase": WorkflowPhase.CREATING,
            }

        system_prompt = self._build_system_prompt(state)
        response = await self.model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        parsed = self._parse_json_response(response.content)

        result: dict[str, Any] = {
            "shooting_plan": parsed,
            "phase": WorkflowPhase.CREATING,
        }

        return result

    def _build_brief_prompt(self, brief: dict, viral_refs: list) -> str:
        """Build prompt for brief mode — from parsed brief content."""
        viral_context = self._format_viral_refs(viral_refs)
        return f"""请根据以下商单 brief 生成拍摄计划：

品牌：{brief.get("brand_name", "N/A")}
产品：{brief.get("product_name", "N/A")}
规格：{brief.get("product_specs", [])}
必提卖点：{brief.get("selling_points", [])}
必含关键词：{brief.get("required_keywords", [])}
内容方向：{brief.get("content_direction", "N/A")}
目标受众：{brief.get("target_audience", "N/A")}
风格要求：{brief.get("style_requirements", "N/A")}
拍摄要求：{brief.get("shooting_requirements", "N/A")}
注意事项：{brief.get("notes", [])}
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

    def _build_trend_prompt(
        self,
        content_plan: dict,
        copy_content: dict,
        trend_data: dict,
        viral_refs: list,
    ) -> str:
        """Build prompt for trend mode — from content plan + copy content."""
        viral_context = self._format_viral_refs(viral_refs)
        niche = trend_data.get("niche", "") or content_plan.get("niche", "")
        topic = content_plan.get("selected_topic", "N/A")
        angle = content_plan.get("content_angle", "")
        audience = content_plan.get("target_audience", "")
        hashtags = content_plan.get("hashtags", [])
        key_points = content_plan.get("key_points", [])
        selected_title = copy_content.get("selected_title", "")
        body_text = copy_content.get("body_text", "")
        copy_hashtags = copy_content.get("hashtags", [])

        return f"""请根据以下内容策略和文案生成拍摄计划：

选题：{topic}
内容角度：{angle}
目标受众：{audience}
赛道：{niche}
核心要点：{key_points}
策略话题标签：{hashtags}
{f"已选标题：{selected_title}" if selected_title else ""}
{f"文案正文：{body_text[:500]}" if body_text else ""}
{f"文案话题：{copy_hashtags}" if copy_hashtags else ""}
{viral_context}

请输出 JSON 格式的拍摄计划，包含以下字段：
- creator_nickname: 达人昵称（留空）
- content_direction: 内容方向（基于选题和角度）
- content_type_label: 图文内容标签
- profile_link: 主页链接（留空）
- creator_level: 达人量级（留空）
- planned_publish_date: 预计发布日期（留空）
- product_specification: 产品相关描述
- draft_requirements: 初稿要求列表
- draft_notes: 初稿注意事项列表
- title_candidates: 标题备选（至少2个，基于选题生成）
- body_copy: 文案（基于策略要点和已有文案优化）
- required_hashtags: 必带话题
- optional_hashtags: 选带话题
- suggested_hashtags: 建议的热门话题（结合赛道趋势）
- outfits: 拍摄服装建议 {{角色: [服装选项]}}
- shooting_angles: 拍摄角度建议 [{{angle: 角度名, description: 描述, tips: 提示}}]"""

    def _format_viral_refs(self, viral_refs: list) -> str:
        """Format viral reference posts for prompt context."""
        if not viral_refs:
            return ""
        lines = ["\n\n参考爆款笔记："]
        for i, post in enumerate(viral_refs[:5], 1):
            title = post.get("title", "N/A")
            eng = post.get("engagement", "N/A")
            style = post.get("style", "N/A")
            scene = post.get("scene", "N/A")
            lines.append(f"\n{i}. {title} — 互动量: {eng}\n   风格: {style} | 场景: {scene}")
        return "".join(lines)


__all__ = ["ShootingPlannerAgent"]
