"""Trend Scout agent — discovers hot topics and opportunities."""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.trend_scout")


def _xhs_configured() -> bool:
    return bool(os.environ.get("XHS_COOKIE") and os.environ.get("XHS_USER_ID"))


class TrendScoutAgent(BaseAgent):
    task_type = TaskType.SCOUTING
    agent_name = "trend_scout"
    prompt_file = "trend_scout.yaml"

    async def _fetch_real_data(self, niche: str) -> dict[str, Any]:
        """Fetch real data from XHS API via tools. Returns empty dict if unavailable."""
        if not _xhs_configured():
            logger.info("XHS credentials not configured, skipping real data fetch")
            return {}

        from backend.tools.xhs.trending import competitor_analyzer, keyword_monitor, xhs_trending

        data: dict[str, Any] = {}

        # 1. Fetch trending topics for the niche
        try:
            trending = await xhs_trending.ainvoke({"category": niche})
            data["hot_topics"] = trending
        except Exception as e:
            logger.warning(f"xhs_trending failed: {e}")

        # 2. Extract keywords from niche and monitor them
        try:
            # Use niche as keyword seed
            keywords = [niche]
            if trending:
                # Add top trending topic titles as keywords
                for t in trending[:3]:
                    topic = t.get("topic", "")
                    if topic and topic not in keywords:
                        keywords.append(topic)

            monitor_data = await keyword_monitor.ainvoke({"keywords": keywords})
            data["keyword_monitor"] = monitor_data
        except Exception as e:
            logger.warning(f"keyword_monitor failed: {e}")

        # 3. Analyze competitors in this niche
        try:
            competitor_data = await competitor_analyzer.ainvoke(
                {
                    "account_id": niche,
                    "niche": niche,
                }
            )
            data["competitor_analysis"] = competitor_data
        except Exception as e:
            logger.warning(f"competitor_analyzer failed: {e}")

        return data

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        account_id = state.get("account_id", "default")
        niche = state.get("niche", "母婴")

        # 召回历史洞察
        insights = await self._recall_memory(
            store, account_id, query="trend insights", namespace="performance_insights", limit=3
        )
        memory_context = ""
        if insights:
            memory_context = "\n历史趋势洞察：\n"
            for i in insights:
                memory_context += f"- {i.get('insight', '')}\n"

        # Fetch real data from XHS API
        real_data = await self._fetch_real_data(niche)

        # Build data context for the LLM
        data_context = ""
        if real_data:
            data_context = "\n\n## 实时数据（来自小红书 API）\n"

            if real_data.get("hot_topics"):
                data_context += f"\n### 热门话题 ({len(real_data['hot_topics'])} 条)\n"
                for t in real_data["hot_topics"][:15]:
                    data_context += f"- {t.get('topic', '')} (热度: {t.get('heat_score', 0)})\n"

            if real_data.get("keyword_monitor"):
                data_context += "\n### 关键词监控数据\n"
                for kw in real_data["keyword_monitor"]:
                    data_context += (
                        f"- {kw.get('keyword', '')}: "
                        f"{kw.get('post_count', 0)} 篇帖子, "
                        f"平均点赞 {kw.get('avg_likes', 0):.0f}, "
                        f"趋势: {kw.get('trend', 'unknown')}\n"
                    )

            if real_data.get("competitor_analysis"):
                data_context += "\n### 竞品分析\n"
                for ca in real_data["competitor_analysis"]:
                    data_context += (
                        f"- {ca.get('account', '')} ({ca.get('niche', '')}): "
                        f"{ca.get('post_count', 0)} 篇帖子, "
                        f"平均点赞 {ca.get('avg_likes', 0):.0f}\n"
                    )
                    top = ca.get("top_posts", [])
                    if top:
                        data_context += "  热门帖子:\n"
                        for p in top[:3]:
                            data_context += f"  - {p.get('title', '')} (赞: {p.get('likes', 0)})\n"

            data_source = "real"
        else:
            data_context = "\n\n## 无实时数据\n未配置小红书 API 凭证，基于你的知识生成趋势分析。"
            data_source = "llm_generated"

        system_prompt = self._build_system_prompt(
            state, extra_context=memory_context + data_context
        )

        user_msg = f"""账号定位：{account_id}
关注领域：{niche}
竞品账号：暂无

请基于以上数据进行分析，输出 JSON 格式的趋势报告。"""

        response = await self.model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        content = response.content
        if isinstance(content, list):
            content = str(content)
        trend_data = self._parse_json_response(content)
        trend_data["data_source"] = data_source

        # Normalize topic field name to canonical `hot_topics`
        # LLM may output `trending_topics` or `topics` — ensure `hot_topics` exists
        if not trend_data.get("hot_topics"):
            trend_data["hot_topics"] = (
                trend_data.get("trending_topics") or trend_data.get("topics") or []
            )

        # 沉淀趋势洞察到长期记忆
        if store is not None:
            try:
                from backend.memory.store import MemoryManager

                mm = MemoryManager(account_id)
                topics = trend_data.get(
                    "hot_topics",
                    trend_data.get("trending_topics", trend_data.get("topics", [])),
                )
                summary = (
                    ", ".join((t.get("topic") or str(t))[:20] for t in topics[:3])
                    if topics
                    else niche
                )
                await mm.store_insight(
                    store,
                    f"趋势信号: {summary}",
                    {"source": "trend_scout", "niche": niche, "data_source": data_source},
                )
            except Exception as e:
                logger.warning(f"Failed to store trend insight: {e}")

        return {
            "trend_data": trend_data,
            "phase": WorkflowPhase.SCOUTING,
        }
