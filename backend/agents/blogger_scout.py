"""Blogger Scout agent — discovers top bloggers from niche keywords."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.blogger_scout")


class BloggerScoutAgent(BaseAgent):
    """博主发现 Agent — 从赛道热门笔记中提取博主并排序."""

    task_type = TaskType.SCOUTING
    agent_name = "blogger_scout"
    prompt_file = "blogger_scout.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        limit = state.get("blogger_candidate_limit", 5)

        keywords = self._extract_keywords(state)
        if not keywords:
            niche = state.get("niche", "母婴")
            logger.info(f"No keywords found, using fallback candidates for niche: {niche}")
            return self._hardcoded_fallback_candidates(niche, [], limit)

        logger.info("Using LLM-generated blogger candidates")
        return await self._generate_mock_candidates(state, keywords, limit)

    def _extract_keywords(self, state: XHSGrowthState) -> list[str]:
        """Extract search keywords from state based on workflow mode."""
        keywords: list[str] = []

        trend_data = state.get("trend_data") or {}
        content_plan = state.get("content_plan") or {}
        brief_content = state.get("brief_content") or {}

        # Trend mode keywords
        if trend_data.get("trending_keywords"):
            # ponytail: 元素可能是 dict（trending tool 返回 {topic,...}）或 str。
            # extend dict 会拆成 dict 的 keys 污染 keywords，先取 str/字段。
            for k in trend_data["trending_keywords"][:3]:
                if isinstance(k, str):
                    keywords.append(k)
                elif isinstance(k, Mapping):
                    val = k.get("topic") or k.get("keyword") or ""
                    if val:
                        keywords.append(str(val))
        if content_plan.get("selected_topic"):
            keywords.append(content_plan["selected_topic"])

        # Brief mode keywords
        if brief_content.get("required_keywords"):
            keywords.extend(brief_content["required_keywords"][:3])
        if brief_content.get("brand_name"):
            keywords.append(brief_content["brand_name"])

        # Deduplicate while preserving order, coerce to str
        seen = set()
        unique = []
        for kw in keywords:
            kw_str = str(kw) if not isinstance(kw, str) else kw
            if kw_str and kw_str not in seen:
                seen.add(kw_str)
                unique.append(kw_str)

        return unique[:5]

    async def _generate_mock_candidates(
        self, state: XHSGrowthState, keywords: list[str], limit: int
    ) -> dict[str, Any]:
        """Generate mock blogger candidates using LLM when XHS client is unavailable."""
        niche = state.get("niche", "母婴")
        brief_content = state.get("brief_content") or {}
        trend_data = dict(state.get("trend_data") or {})
        trend_summary = self._summarize_trend_data(trend_data)

        system_prompt = self.prompt_template.get("mock_system", "")
        user_template = self.prompt_template.get("mock_user_template", "")

        brief_summary = self._summarize_brief_content(brief_content)

        user_prompt = user_template.format(
            niche=niche,
            keywords=", ".join(keywords),
            trend_summary=trend_summary,
            brief_summary=brief_summary,
            candidate_limit=limit,
        )

        try:
            response = await self.model.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )

            content = response.content
            if isinstance(content, list):
                content = str(content)
            parsed = self._parse_json_response(content)

            candidates = parsed.get("candidates", [])
            if not candidates and parsed.get("raw_content"):
                logger.warning("LLM did not return JSON, retrying with explicit instruction")
                return await self._retry_mock_with_explicit_json(
                    state, keywords, limit, niche, brief_summary, trend_summary
                )

            # Ensure mock_ prefix on all user_ids
            for c in candidates:
                if not c.get("user_id", "").startswith("mock_"):
                    c["user_id"] = f"mock_{c.get('user_id', 'unknown')}"
                if "avatar_url" not in c:
                    c["avatar_url"] = ""

            if not candidates:
                logger.warning("LLM returned empty candidates, using fallback")
                return self._hardcoded_fallback_candidates(niche, keywords, limit)

            candidates = candidates[:limit]
            logger.info(f"Generated {len(candidates)} mock blogger candidates via LLM")
            return {
                "blogger_candidates": candidates,
                "phase": WorkflowPhase.CREATING,
            }
        except Exception as e:
            logger.error(f"LLM mock generation failed: {e}")
            return self._hardcoded_fallback_candidates(niche, keywords, limit)

    async def _retry_mock_with_explicit_json(
        self,
        state: XHSGrowthState,
        keywords: list[str],
        limit: int,
        niche: str,
        brief_summary: str,
        trend_summary: str,
    ) -> dict[str, Any]:
        """Retry mock generation with a more explicit JSON-only prompt."""
        prompt = (
            f"你必须在回复中仅输出一个JSON对象，不要有任何其他文字。\n"
            f"赛道：{niche}\n关键词：{', '.join(keywords)}\n"
            f"商单信息：{brief_summary}\n趋势数据：{trend_summary}\n"
            f"生成{limit}个该赛道风格的虚拟博主候选。\n\n"
            f'输出格式：{{"candidates": [{{"user_id": "mock_001", '
            f'"nickname": "博主昵称", "follower_count": 50000, '
            f'"note_count": 120, "total_engagement": 8000, '
            f'"top_note_title": "代表作标题"}}]}}\n'
            f"只输出JSON，不要输出其他任何内容。"
        )
        try:
            response = await self.model.ainvoke([HumanMessage(content=prompt)])
            content = response.content
            if isinstance(content, list):
                content = str(content)
            parsed = self._parse_json_response(content)
            candidates = parsed.get("candidates", [])
            for c in candidates:
                if not c.get("user_id", "").startswith("mock_"):
                    c["user_id"] = f"mock_{c.get('user_id', 'unknown')}"
                if "avatar_url" not in c:
                    c["avatar_url"] = ""
            if not candidates:
                logger.warning("Retry returned empty candidates, using fallback")
                return self._hardcoded_fallback_candidates(niche, keywords, limit)
            candidates = candidates[:limit]
            logger.info(f"Retry generated {len(candidates)} mock blogger candidates")
            return {
                "blogger_candidates": candidates,
                "phase": WorkflowPhase.CREATING,
            }
        except Exception as e:
            logger.error(f"Retry mock generation also failed: {e}")
            return self._hardcoded_fallback_candidates(niche, keywords, limit)

    def _hardcoded_fallback_candidates(
        self, niche: str, keywords: list[str], limit: int
    ) -> dict[str, Any]:
        """Return hardcoded mock candidates when LLM generation fails."""
        niche_label = niche or "综合"
        candidates = [
            {
                "user_id": "mock_fallback_001",
                "nickname": f"{niche_label}达人Amy",
                "avatar_url": "",
                "follower_count": 52000,
                "note_count": 134,
                "total_engagement": 12800,
                "top_note_title": f"{niche_label}必看推荐！超全攻略",
            },
            {
                "user_id": "mock_fallback_002",
                "nickname": f"{niche_label}博主小K",
                "avatar_url": "",
                "follower_count": 38000,
                "note_count": 89,
                "total_engagement": 9200,
                "top_note_title": f"我的{niche_label}好物分享",
            },
            {
                "user_id": "mock_fallback_003",
                "nickname": f"{niche_label}小姐姐Luna",
                "avatar_url": "",
                "follower_count": 67000,
                "note_count": 201,
                "total_engagement": 18500,
                "top_note_title": f"{niche_label}避坑指南，新手必读",
            },
            {
                "user_id": "mock_fallback_004",
                "nickname": f"{niche_label}探店王",
                "avatar_url": "",
                "follower_count": 29000,
                "note_count": 67,
                "total_engagement": 6400,
                "top_note_title": f"周末{niche_label}打卡清单",
            },
            {
                "user_id": "mock_fallback_005",
                "nickname": f"{niche_label}种草机",
                "avatar_url": "",
                "follower_count": 45000,
                "note_count": 156,
                "total_engagement": 11000,
                "top_note_title": f"{niche_label}测评合集｜真实体验",
            },
        ]
        logger.warning(f"Using hardcoded fallback: {min(limit, len(candidates))} candidates")
        return {
            "blogger_candidates": candidates[:limit],
            "phase": WorkflowPhase.CREATING,
        }

    def _summarize_brief_content(self, brief_content: Mapping[str, Any]) -> str:
        """Create a brief summary of brief_content for LLM context."""
        if not brief_content:
            return "无商单信息"

        parts = []
        if brief_content.get("brand_name"):
            parts.append(f"品牌: {brief_content['brand_name']}")
        if brief_content.get("product_name"):
            parts.append(f"产品: {brief_content['product_name']}")
        if brief_content.get("target_audience"):
            parts.append(f"目标受众: {brief_content['target_audience']}")
        if brief_content.get("content_direction"):
            parts.append(f"内容方向: {brief_content['content_direction'][:100]}")
        if brief_content.get("selling_points"):
            parts.append(f"卖点: {', '.join(brief_content['selling_points'][:3])}")
        if brief_content.get("style_requirements"):
            parts.append(f"风格要求: {brief_content['style_requirements'][:80]}")

        return " | ".join(parts) if parts else "无商单信息"

    def _summarize_trend_data(self, trend_data: dict[str, Any]) -> str:
        """Create a brief summary of trend_data for LLM context."""
        if not trend_data:
            return "无趋势数据"

        parts = []
        if trend_data.get("trending_keywords"):
            kws = trend_data["trending_keywords"][:5]
            # ponytail: 元素可能是 dict（trending tool 返回 {topic,...}）或 str。
            kw_strs = [
                k if isinstance(k, str) else str(k.get("topic") or k.get("keyword") or "")
                for k in kws
            ]
            kw_strs = [k for k in kw_strs if k]
            if kw_strs:
                parts.append(f"热门关键词: {', '.join(kw_strs)}")
        if trend_data.get("hot_topics"):
            topics = trend_data["hot_topics"][:3]
            # ponytail: 元素可能是 dict（LLM/topics tool），取 title/topic。
            topic_strs = [
                t if isinstance(t, str) else str(t.get("title") or t.get("topic") or "")
                for t in topics
            ]
            topic_strs = [t for t in topic_strs if t]
            if topic_strs:
                parts.append(f"热门话题: {', '.join(topic_strs)}")
        if trend_data.get("trending_notes"):
            notes = trend_data["trending_notes"][:2]
            titles = [n.get("title", "") for n in notes if n.get("title")]
            if titles:
                parts.append(f"热门笔记: {', '.join(titles)}")

        return " | ".join(parts) if parts else "无趋势数据"


__all__ = ["BloggerScoutAgent"]
