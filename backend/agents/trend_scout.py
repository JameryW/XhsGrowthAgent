"""Trend Scout agent — discovers hot topics and opportunities."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.trend_scout")


async def _safe_xhs_trending(niche: str, account_id: str) -> list[dict[str, Any]]:
    """Fetch trending topics; swallow + log own failures (return [])."""
    from backend.tools.xhs.trending import xhs_trending

    try:
        return cast(
            list[dict[str, Any]],
            await xhs_trending.ainvoke({"category": niche, "account_id": account_id}),
        )
    except Exception as e:
        logger.warning(f"xhs_trending failed: {e}")
        return []


async def _safe_competitor_analyzer(niche: str, account_id: str) -> list[dict[str, Any]]:
    """Analyze competitors; swallow + log own failures (return [])."""
    from backend.tools.xhs.trending import competitor_analyzer

    try:
        return cast(
            list[dict[str, Any]],
            await competitor_analyzer.ainvoke(
                {
                    "account_id": niche,
                    "niche": niche,
                    "credential_account_id": account_id,
                }
            ),
        )
    except Exception as e:
        logger.warning(f"competitor_analyzer failed: {e}")
        return []


class TrendScoutAgent(BaseAgent):
    task_type = TaskType.SCOUTING
    agent_name = "trend_scout"
    prompt_file = "trend_scout.yaml"

    async def _fetch_real_data(
        self, niche: str, account_id: str = "", user_topic: str = ""
    ) -> dict[str, Any]:
        """Fetch real data from XHS API via tools. Returns empty dict if unavailable."""
        from backend.tools.xhs.trending import keyword_monitor

        # xhs_trending + competitor_analyzer are independent (no data
        # dependency, disjoint data keys, each swallows own exceptions) → run
        # concurrently. keyword_monitor DEPENDS on trending (builds its keyword
        # seed from trending[:3] topic titles) so it stays serial after the
        # gather. Return-value pattern: assign to `data` after gather (no
        # concurrent dict mutation). Precedent: copywriter.py:53, #502/#503.
        trending, competitor_data = await asyncio.gather(
            _safe_xhs_trending(niche, account_id),
            _safe_competitor_analyzer(niche, account_id),
        )

        data: dict[str, Any] = {}
        if trending:
            data["hot_topics"] = trending
        if competitor_data:
            data["competitor_analysis"] = competitor_data

        # keyword_monitor needs trending (enriches keyword seed) — sequential.
        try:
            # Keyword seed: niche + user-provided topic (if any), so trend /
            # keyword monitoring revolves around the user's topic, not just niche.
            keywords = [niche]
            if user_topic and user_topic not in keywords:
                keywords.insert(0, user_topic)
            if trending:
                # Add top trending topic titles as keywords
                for t in trending[:3]:
                    topic = t.get("topic", "")
                    if topic and topic not in keywords:
                        keywords.append(topic)

            monitor_data = await keyword_monitor.ainvoke(
                {"keywords": keywords, "account_id": account_id}
            )
            if monitor_data:
                data["keyword_monitor"] = monitor_data
        except Exception as e:
            logger.warning(f"keyword_monitor failed: {e}")

        return data

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        self._reset_llm_perf()
        account_id = state.get("account_id", "default")
        niche = state.get("niche", "母婴")
        # User-provided topic override: include it in the keyword seed so trend
        # scouting / keyword monitoring revolve around the user's topic, not just
        # the niche. Previously dead data — trend_scout only seeded niche.
        user_topic = str(state.get("topic") or "").strip()

        # _recall_memory (fast Postgres asearch) + _fetch_real_data (slow XHS,
        # 3 RTTs — the long pole) are independent (memory reads
        # performance_insights ns, fetch reads XHS API; neither needs the other's
        # result — both feed separate context strings concatenated at :168). Both
        # swallow own exceptions (_recall_memory via base.py try/except,
        # _fetch_real_data via _safe_* + keyword_monitor try/except). Gather so
        # memory RTT hides behind the XHS long pole. Return-value pattern.
        # Precedent: #502/#503/#504/#505; _fetch_real_data itself gathers
        # internally (#504) — first nested-gather example.
        insights, real_data = await asyncio.gather(
            self._recall_memory(
                store,
                account_id,
                query="trend insights",
                namespace="performance_insights",
                limit=3,
            ),
            self._fetch_real_data(niche, account_id=account_id, user_topic=user_topic),
        )
        memory_context = ""
        if insights:
            memory_context = "\n历史趋势洞察：\n"
            for i in insights:
                memory_context += f"- {i.get('insight', '')}\n"

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
            data_context = "\n\n## 无实时数据\n小红书实时数据不可用，基于你的知识生成趋势分析。"
            data_source = "llm_generated"

        system_prompt = self._build_system_prompt(
            state, extra_context=memory_context + data_context
        )

        user_msg = f"""账号定位：{account_id}
关注领域：{niche}
竞品账号：暂无

请基于以上数据进行分析，输出 JSON 格式的趋势报告。"""

        response = await self._llm_ainvoke(
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
