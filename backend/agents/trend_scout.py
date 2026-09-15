"""Trend Scout agent — discovers hot topics and opportunities.

P1b-S4 迁移第一个销号 agent（consumer-map §六.1）：recall 走 S2 管线
（RetrievalResult.mode 降级信号 + kind=context 事件面），prompt 组装走
ContextCompiler.compile_prompt（YAML 分段 schema，`<!-- ctx:l4_memory -->`
标记替代 {memory_context} 占位符）。分段等价口径（info.md D3'）：L0 policy
文本逐字不变，L4/L5 各段内容集合与迁移前相等；`data_source` 状态契约不动。

P1c-S3d 迁移最后三个直调点（xhs.trending / xhs.keyword_monitor /
xhs.competitor_analyzer）——agent 层的 `from backend.tools.xhs.trending import
...` 至此清零，读平台一律经 Gateway。降级语义不变（失败仍退化为
`data_source="llm_generated"`），变的是"谁还知道失败了"：以前工具自己吞掉异常
返回 `[]`、调用方再吞一次，Gateway 只会看到一次"成功的空读取"。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.context.compiler import ContextCompiler
from backend.context.models import (
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
    require_niche,
)
from backend.context.retrieval import RecallRequest, recall_namespaces
from backend.models.outputs import TrendScoutOutput, normalize_trend_data
from backend.models.structured import StructuredOutputError
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.trend_scout")

_compiler = ContextCompiler()


async def _recall_insights(
    store: BaseStore | None, account_id: str, thread_id: str
) -> RetrievalResult:
    """performance_insights recall through the S2 pipeline (D6').

    The outcome always carries a mode: a store failure degrades with an error
    summary instead of silently returning ``[]``, and — with a ``thread_id`` —
    lands in the workflow_events tier as ``kind="context"``.
    """
    if store is None:
        return RetrievalResult(
            namespace="performance_insights",
            mode=RetrievalMode.DEGRADED,
            error="store_unavailable",
        )
    results = await recall_namespaces(
        store,
        account_id=account_id,
        requests=[RecallRequest(namespace="performance_insights", query="trend insights", limit=3)],
        thread_id=thread_id,
        emit_events=True,
    )
    return results["performance_insights"]


def _format_memory_context(result: RetrievalResult) -> str:
    """L4 text, format identical to the pre-migration block (分段等价)."""
    if result.mode is RetrievalMode.HIT and result.items:
        text = "\n历史趋势洞察：\n"
        for item in result.items:
            text += f"- {item.body}\n"
        return text
    return ""


class TrendScoutAgent(BaseAgent):
    task_type = TaskType.SCOUTING
    agent_name = "trend_scout"
    prompt_file = "trend_scout.yaml"
    tool_capabilities = (
        "xhs.trending",
        "xhs.keyword_monitor",
        "xhs.competitor_analyzer",
    )

    async def _safe_xhs_trending(
        self, niche: str, account_id: str, thread_id: str = ""
    ) -> list[dict[str, Any]]:
        """Trending topics through the Gateway; degrade to ``[]`` on failure.

        Degrading is the *caller's* decision and stays exactly where it was.
        What changed is who else gets told: the old body caught the tool's
        exception itself, so the failure lived only in a log line, while the
        Gateway — with the tool swallowing on its side too — recorded a
        successful call. Now the failure comes back as ``ToolResult(ok=False)``
        and this method degrades *from* that result, so the trace agrees.
        """
        result = await self.tools.invoke(
            "xhs.trending",
            {"category": niche, "account_id": account_id},
            thread_id=thread_id,
        )
        if not result.ok:
            logger.warning("xhs_trending failed: %s", result.error)
            return []
        rows = result.value
        return cast(list[dict[str, Any]], rows) if isinstance(rows, list) else []

    async def _safe_competitor_analyzer(
        self, niche: str, account_id: str, thread_id: str = ""
    ) -> list[dict[str, Any]]:
        """Competitor notes through the Gateway; degrade to ``[]`` on failure.

        The payload keeps its pre-migration shape, ``account_id`` being the
        *niche* included: the tool reads that argument as "competitor account
        or search keyword", so a niche is a legitimate value for it and it is
        the value this call site has always sent. Which one it *should* have
        been is a product question, not this migration's to re-decide.
        """
        result = await self.tools.invoke(
            "xhs.competitor_analyzer",
            {
                "account_id": niche,
                "niche": niche,
                "credential_account_id": account_id,
            },
            thread_id=thread_id,
        )
        if not result.ok:
            logger.warning("competitor_analyzer failed: %s", result.error)
            return []
        rows = result.value
        return cast(list[dict[str, Any]], rows) if isinstance(rows, list) else []

    async def _fetch_real_data(
        self,
        niche: str,
        account_id: str = "",
        user_topic: str = "",
        thread_id: str = "",
    ) -> dict[str, Any]:
        """Fetch real data from XHS API via tools. Returns empty dict if unavailable."""
        # xhs_trending + competitor_analyzer are independent (no data
        # dependency, disjoint data keys, each degrades on its own) → run
        # concurrently. keyword_monitor DEPENDS on trending (builds its keyword
        # seed from trending[:3] topic titles) so it stays serial after the
        # gather. Return-value pattern: assign to `data` after gather (no
        # concurrent dict mutation). Precedent: copywriter.py:53, #502/#503.
        trending, competitor_data = await asyncio.gather(
            self._safe_xhs_trending(niche, account_id, thread_id),
            self._safe_competitor_analyzer(niche, account_id, thread_id),
        )

        data: dict[str, Any] = {}
        if trending:
            data["hot_topics"] = trending
        if competitor_data:
            data["competitor_analysis"] = competitor_data

        # keyword_monitor needs trending (enriches keyword seed) — sequential.
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

        # No try/except: the Gateway returns failures as data instead of
        # raising, and the tool no longer swallows its own (see
        # backend/tools/xhs/trending.py), so a failure here is visible to the
        # trace rather than only to this log line.
        monitor = await self.tools.invoke(
            "xhs.keyword_monitor",
            {"keywords": keywords, "account_id": account_id},
            thread_id=thread_id,
        )
        if not monitor.ok:
            logger.warning("keyword_monitor failed: %s", monitor.error)
        elif monitor.value:
            data["keyword_monitor"] = monitor.value

        return data

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        self._reset_llm_perf()
        account_id = state.get("account_id", "default")
        # niche 隐式默认保留到 S4 第 7 步（base 收口时与 start 入口校验一并切换，D2'）。
        niche = require_niche(state)
        # User-provided topic override: include it in the keyword seed so trend
        # scouting / keyword monitoring revolve around the user's topic, not just
        # the niche. Previously dead data — trend_scout only seeded niche.
        user_topic = str(state.get("topic") or "").strip()
        thread_id = str(state.get("session_id") or "")

        # S2 recall pipeline (mode signal + context telemetry) still gathered
        # with the XHS long pole — same concurrency contract as before, the
        # coroutine just changed name to _recall_insights.
        insights_result, real_data = await asyncio.gather(
            _recall_insights(store, account_id, thread_id),
            self._fetch_real_data(
                niche, account_id=account_id, user_topic=user_topic, thread_id=thread_id
            ),
        )
        memory_context = _format_memory_context(insights_result)

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

        # L4/L5 enter the compiler as pre-formatted blocks (one ContextItem
        # each — the agent-specific headers keep 分段等价 byte-for-byte; the
        # L5 mode carries the D6' degradation signal for the realtime source).
        memory = RetrievalResult(
            namespace="performance_insights",
            layer=PromptLayer.L4_MEMORY,
            mode=insights_result.mode,
            error=insights_result.error,
            items=(
                (ContextItem(body=memory_context, source="memory:performance_insights"),)
                if memory_context
                else ()
            ),
        )
        observation = RetrievalResult(
            namespace="xhs_realtime",
            layer=PromptLayer.L5_OBSERVATION,
            mode=RetrievalMode.HIT if data_source == "real" else RetrievalMode.DEGRADED,
            error="" if data_source == "real" else "realtime_unavailable",
            items=(ContextItem(body=data_context, source="xhs:realtime"),),
        )
        if observation.mode is RetrievalMode.DEGRADED and thread_id:
            try:
                from backend.db.workflow_events import append_events

                await append_events(
                    thread_id,
                    [
                        {
                            "kind": "context",
                            "event": "observation",
                            "agent": "trend_scout",
                            "mode": "degraded",
                            "error": "realtime_unavailable",
                            "completed_at": datetime.now(UTC).isoformat(),
                        }
                    ],
                )
            except Exception as e:  # best-effort telemetry
                logger.debug("observation telemetry failed: %s", e)

        run_context = RunContext(
            thread_id=thread_id,
            account_id=account_id,
            niche=niche,
            values=state,
            tool_schema=self.tool_schema_layer(),
        )
        system_prompt = _compiler.compile_prompt(
            run_context,
            self.prompt_template["system"],
            retrievals=(memory, observation),
        ).render()

        user_msg = f"""账号定位：{account_id}
关注领域：{niche}
竞品账号：暂无

请基于以上数据进行分析，输出 JSON 格式的趋势报告。"""

        try:
            output = await self._llm_structured(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_msg),
                ],
                TrendScoutOutput,
            )
        except StructuredOutputError as exc:
            # 旧实现里 `_parse_json_response` 把解析失败变成 `{"raw_content": ...}`，
            # 于是"模型没给出可用趋势"退化成空趋势，而不是让节点失败。这个语义是
            # 对的——空趋势是一个业务结果（should_plan 据此收尾或重试），ERROR 才是
            # "节点坏了"——所以在这里显式保留它，而不是让它悄悄变成后者。
            #
            # 注意这里只接住 StructuredOutputError：它意味着"问过了，答得不能用"。
            # "一次都没问到"（调用本身抛错）不由它承载，会原样往上抛成节点失败 ——
            # 那正是 stateful retry 要接的东西，空趋势接不住它。
            logger.warning(
                "%s: no usable trend payload (%d attempt(s)); degrading to empty trends",
                self.agent_name,
                len(exc.attempts),
            )
            # 空结构的形状只有一个来源，不手写一份平行的空 dict。
            trend_data = normalize_trend_data(TrendScoutOutput())
        else:
            # 别名链（trending_topics / topics → hot_topics）与条目形状已由
            # TrendScoutOutput 收敛，这里拿到的直接就是 state 形状。
            trend_data = normalize_trend_data(output)

        # data_source 是运行时事实，刻意不放进输出模型：模型能声明它就等于能谎报
        # 数据来源——S3d 那个假 data_source="real" 正是这么来的。
        trend_data["data_source"] = data_source

        # 沉淀趋势洞察到长期记忆
        if store is not None:
            try:
                from backend.memory.store import MemoryManager

                mm = MemoryManager(account_id)
                # 条目形状已由 TrendScoutOutput 保证（一定有 topic），所以别名链
                # 和"元素可能是个字符串"的兜底都是迁移前的事，不再需要。
                topics = trend_data["hot_topics"]
                summary = ", ".join(t["topic"][:20] for t in topics[:3]) if topics else niche
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
