"""Blogger Scout agent — discovers top bloggers from niche keywords."""

from __future__ import annotations

import logging
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
            logger.info("No keywords found, skipping blogger scout")
            return {
                "blogger_candidates": [],
                "phase": WorkflowPhase.CREATING,
            }

        try:
            from backend.services.xhs_client import XHSClient

            cookie = str(state.get("xhs_cookie", "") or "")
            client = XHSClient(cookie=cookie) if cookie else None
            if not client or not client._http:
                logger.warning("No XHS client available, falling back to LLM mock generation")
                return await self._generate_mock_candidates(state, keywords, limit)

            # Step 1: Search notes by each keyword and collect user_ids with engagement
            user_engagement: dict[str, dict[str, Any]] = {}

            for keyword in keywords[:3]:
                notes = await client.search_posts(keyword=keyword, limit=20)
                for note in notes:
                    uid = note.user_id
                    if not uid:
                        continue
                    engagement = note.likes + note.collects + note.comments
                    if uid not in user_engagement:
                        user_engagement[uid] = {
                            "user_id": uid,
                            "nickname": note.user_name,
                            "total_engagement": 0,
                            "top_note_title": note.title,
                            "top_note_engagement": 0,
                        }
                    user_engagement[uid]["total_engagement"] += engagement
                    if engagement > user_engagement[uid]["top_note_engagement"]:
                        user_engagement[uid]["top_note_title"] = note.title
                        user_engagement[uid]["top_note_engagement"] = engagement

            if not user_engagement:
                logger.info("No bloggers found from search results")
                return {
                    "blogger_candidates": [],
                    "phase": WorkflowPhase.CREATING,
                }

            # Step 2: Sort by total engagement, take top N
            sorted_users = sorted(
                user_engagement.values(),
                key=lambda x: x["total_engagement"],
                reverse=True,
            )[:limit]

            # Step 3: Enrich with user info (follower count, note count)
            candidates = []
            for user_data in sorted_users:
                uid = user_data["user_id"]
                info = await client.get_user_info(uid)
                candidates.append(
                    {
                        "user_id": uid,
                        "nickname": user_data["nickname"],
                        "avatar_url": info.get("avatar", ""),
                        "follower_count": info.get("follows", 0),
                        "note_count": info.get("notes_count", 0),
                        "total_engagement": user_data["total_engagement"],
                        "top_note_title": user_data["top_note_title"],
                    }
                )

            await client.close()

            logger.info(f"Found {len(candidates)} blogger candidates")
            return {
                "blogger_candidates": candidates,
                "phase": WorkflowPhase.CREATING,
            }

        except Exception as e:
            logger.warning(f"Blogger scout failed, returning empty candidates: {e}")
            return {
                "blogger_candidates": [],
                "phase": WorkflowPhase.CREATING,
            }

    def _extract_keywords(self, state: XHSGrowthState) -> list[str]:
        """Extract search keywords from state based on workflow mode."""
        keywords: list[str] = []

        trend_data = state.get("trend_data") or {}
        content_plan = state.get("content_plan") or {}
        brief_content = state.get("brief_content") or {}

        # Trend mode keywords
        if trend_data.get("trending_keywords"):
            keywords.extend(trend_data["trending_keywords"][:3])
        if content_plan.get("selected_topic"):
            keywords.append(content_plan["selected_topic"])

        # Brief mode keywords
        if brief_content.get("required_keywords"):
            keywords.extend(brief_content["required_keywords"][:3])
        if brief_content.get("brand_name"):
            keywords.append(brief_content["brand_name"])

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)

        return unique[:5]

    async def _generate_mock_candidates(
        self, state: XHSGrowthState, keywords: list[str], limit: int
    ) -> dict[str, Any]:
        """Generate mock blogger candidates using LLM when XHS client is unavailable."""
        niche = state.get("niche", "母婴")
        trend_data = dict(state.get("trend_data") or {})
        trend_summary = self._summarize_trend_data(trend_data)

        system_prompt = self.prompt_template.get("mock_system", "")
        user_template = self.prompt_template.get("mock_user_template", "")

        user_prompt = user_template.format(
            niche=niche,
            keywords=", ".join(keywords),
            trend_summary=trend_summary,
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
            # Ensure mock_ prefix on all user_ids
            for c in candidates:
                if not c.get("user_id", "").startswith("mock_"):
                    c["user_id"] = f"mock_{c.get('user_id', 'unknown')}"
                # Ensure avatar_url field exists
                if "avatar_url" not in c:
                    c["avatar_url"] = ""

            logger.info(f"Generated {len(candidates)} mock blogger candidates via LLM")
            return {
                "blogger_candidates": candidates,
                "phase": WorkflowPhase.CREATING,
            }
        except Exception as e:
            logger.error(f"LLM mock generation failed: {e}")
            return {
                "blogger_candidates": [],
                "phase": WorkflowPhase.CREATING,
            }

    def _summarize_trend_data(self, trend_data: dict[str, Any]) -> str:
        """Create a brief summary of trend_data for LLM context."""
        if not trend_data:
            return "无趋势数据"

        parts = []
        if trend_data.get("trending_keywords"):
            parts.append(f"热门关键词: {', '.join(trend_data['trending_keywords'][:5])}")
        if trend_data.get("hot_topics"):
            topics = trend_data["hot_topics"][:3]
            parts.append(f"热门话题: {', '.join(topics)}")
        if trend_data.get("trending_notes"):
            notes = trend_data["trending_notes"][:2]
            titles = [n.get("title", "") for n in notes if n.get("title")]
            if titles:
                parts.append(f"热门笔记: {', '.join(titles)}")

        return " | ".join(parts) if parts else "无趋势数据"


__all__ = ["BloggerScoutAgent"]
