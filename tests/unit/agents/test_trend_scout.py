"""Unit tests for TrendScoutAgent."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.trend_scout import TrendScoutAgent
from backend.state.schema import WorkflowPhase


class TestTrendScoutAgent:
    """Tests for TrendScoutAgent trend discovery."""

    @pytest.fixture
    def agent(self):
        """Create trend scout instance."""
        return TrendScoutAgent()

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph store."""
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_state(self):
        """Standard mock state."""
        return {
            "account_id": "test_account",
            "niche": "母婴",
            "phase": WorkflowPhase.IDLE,
        }

    @pytest.mark.asyncio
    async def test_execute_returns_trend_data(self, agent, mock_state, mock_store):
        """Execute returns trend_data in result."""
        mock_response = MagicMock()
        mock_response.content = """```json
{
  "trending_topics": ["美食探店", "OOTD穿搭"],
  "opportunities": ["健康饮食", "可持续生活"],
  "recommendations": ["测试话题"]
}
```"""

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=mock_store)

        assert "trend_data" in result
        assert result["phase"] == WorkflowPhase.SCOUTING

    @pytest.mark.asyncio
    async def test_execute_recalls_memory(self, agent, mock_state, mock_store):
        """Execute recalls memory for historical insights."""
        mock_item = MagicMock()
        mock_item.value = {"insight": "美食话题表现好"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=mock_store)

        # Memory was recalled
        mock_store.asearch.assert_called_once()
        assert "trend_data" in result

    @pytest.mark.asyncio
    async def test_execute_handles_invalid_json(self, agent, mock_state, mock_store):
        """Unparseable LLM output degrades to the declared empty trend shape.

        The old implementation turned ``_parse_json_response``'s failure into
        ``{"raw_content": <model text>}`` — it parked the raw answer in state
        and left the *API layer* to filter it back out (see
        ``tests/unit/api/test_public_showcase.py``). Note what that payload
        does now: every field on ``TrendScoutOutput`` has a default and the
        model ignores extras, so ``{"raw_content": ...}`` *passes* the schema
        and the failure never even reaches ``StructuredOutputError``. Two
        independent mechanisms keep the text out of state — the chain never
        returns a malformed payload, and the output model only admits keys it
        declared — so the assertion below pins the property, not the mechanism.
        """
        mock_response = MagicMock()
        mock_response.content = "Not valid JSON"

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        with (
            patch("backend.tools.xhs.trending.xhs_trending") as trending,
            patch("backend.tools.xhs.trending.keyword_monitor") as monitor,
            patch("backend.tools.xhs.trending.competitor_analyzer") as competitor,
        ):
            trending.ainvoke = AsyncMock(return_value=[])
            monitor.ainvoke = AsyncMock(return_value={})
            competitor.ainvoke = AsyncMock(return_value=[])
            result = await agent.execute(mock_state, store=mock_store)

        assert "trend_data" in result
        trend_data = result["trend_data"]
        assert trend_data["hot_topics"] == []
        assert "raw_content" not in trend_data
        # 模型原文一个字都不随结果走 —— 上面那条只钉了键名，这条钉内容。
        assert "Not valid JSON" not in json.dumps(trend_data, ensure_ascii=False)
        assert trend_data["data_source"] == "llm_generated"

    @pytest.mark.asyncio
    async def test_execute_with_account_id(self, agent, mock_store):
        """Execute uses account_id from state."""
        mock_state = {"niche": "母婴", "account_id": "custom_account"}
        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=mock_store)

        assert result["phase"] == WorkflowPhase.SCOUTING

    @pytest.mark.asyncio
    async def test_execute_stores_insight(self, agent, mock_state, mock_store):
        """Execute stores trend insight to memory after scouting."""
        mock_response = MagicMock()
        mock_response.content = """```json
{
  "trending_topics": [{"topic": "美食探店"}, {"topic": "OOTD穿搭"}],
  "opportunities": ["健康饮食"],
  "recommendations": ["测试话题"]
}
```"""

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=mock_store)

        assert "trend_data" in result
        # aput should have been called to store insight
        mock_store.aput.assert_called_once()
        call_args = mock_store.aput.call_args
        assert call_args.args[0] == ("accounts", "test_account", "performance_insights")

    @pytest.mark.asyncio
    async def test_execute_stores_insight_no_store(self, agent, mock_state):
        """Execute skips insight storage when store is None."""
        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=None)

        assert "trend_data" in result

    @pytest.mark.asyncio
    async def test_user_topic_added_to_keyword_seed(self, agent, mock_store):
        """state['topic'] is prepended to the keyword_monitor seed so trend
        scouting revolves around the user's topic, not just the niche.
        Previously trend_scout only seeded [niche]."""
        captured: dict = {}

        xhs_trending = MagicMock()
        # no trending → keyword seed is niche + user_topic only
        xhs_trending.ainvoke = AsyncMock(return_value=[])

        keyword_monitor = MagicMock()
        keyword_monitor.ainvoke = AsyncMock(return_value={})

        async def _capture(*args, **kwargs):
            # keyword_monitor.ainvoke is called with a single dict arg
            # {"keywords": [...], "account_id": ...}
            payload = args[0] if args else kwargs
            captured["keywords"] = (payload or {}).get("keywords")
            return {}

        keyword_monitor.ainvoke = _capture

        competitor = MagicMock()
        competitor.ainvoke = AsyncMock(return_value={})

        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        state = {
            "niche": "母婴",
            "account_id": "test_account",
            "phase": WorkflowPhase.IDLE,
            "topic": "露营亲子日记",
        }

        with (
            patch("backend.tools.xhs.trending.xhs_trending", new=xhs_trending),
            patch("backend.tools.xhs.trending.keyword_monitor", new=keyword_monitor),
            patch("backend.tools.xhs.trending.competitor_analyzer", new=competitor),
        ):
            await agent.execute(state, store=mock_store)

        assert captured.get("keywords"), "keyword_monitor was not invoked"
        assert "露营亲子日记" in captured["keywords"]
        # user_topic prepended (first) — it is the selection core.
        assert captured["keywords"][0] == "露营亲子日记"

    @pytest.mark.asyncio
    async def test_fetch_real_data_gathers_independent_xhs_calls(self, agent, mock_store):
        """xhs_trending + competitor_analyzer run via one asyncio.gather (not
        3 serial awaits); keyword_monitor stays serial after (needs trending).

        Non-vacuous: patches ``asyncio.gather`` in the trend_scout module and
        asserts exactly one gather call whose awaitables are the independent
        XHS fetches (_safe_xhs_trending + _safe_competitor_analyzer
        coroutines). Discriminates by coroutine source (qualified name), not
        by awaitable count alone — the module now also has a top-level
        2-awaitable gather (_recall_memory + _fetch_real_data, see
        test_execute_gathers_memory_with_xhs_fetch), so count-based filtering
        cannot disambiguate. keyword_monitor is NOT gathered (it depends on
        trending for its keyword seed), so the XHS gather has 2 — not 3 —
        awaitables. If the XHS calls are reverted to 3 serial ``await``
        assignments, no gather contains the _safe_xhs_trending coroutine and
        this test fails.
        """
        import asyncio as _asyncio

        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'

        real_gather = _asyncio.gather
        gather_calls: list[tuple[tuple, dict]] = []

        async def _fake_gather(*awaitables, **kwargs):
            gather_calls.append((awaitables, kwargs))
            # Drive the coroutines the way real gather would, preserving order.
            return list(await real_gather(*awaitables, **kwargs))

        xhs_trending = MagicMock()
        xhs_trending.ainvoke = AsyncMock(return_value=[])
        keyword_monitor = MagicMock()
        keyword_monitor.ainvoke = AsyncMock(return_value={})
        competitor = MagicMock()
        competitor.ainvoke = AsyncMock(return_value=[])

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        state = {
            "niche": "母婴",
            "account_id": "test_account",
            "phase": WorkflowPhase.IDLE,
        }

        with (
            patch("backend.tools.xhs.trending.xhs_trending", new=xhs_trending),
            patch("backend.tools.xhs.trending.keyword_monitor", new=keyword_monitor),
            patch("backend.tools.xhs.trending.competitor_analyzer", new=competitor),
            patch("backend.agents.trend_scout.asyncio.gather", new=_fake_gather),
        ):
            await agent.execute(state, store=mock_store)

        def _names(awaitables):
            return ",".join(getattr(a, "__qualname__", "") for a in awaitables)

        # The internal _fetch_real_data gather: xhs_trending + competitor.
        xhs_gathers = [
            c
            for c, _ in gather_calls
            if "_safe_xhs_trending" in _names(c) and "_safe_competitor_analyzer" in _names(c)
        ]
        assert len(xhs_gathers) == 1, (
            "xhs_trending + competitor_analyzer must be gathered in one call"
        )
        assert len(xhs_gathers[0]) == 2, "keyword_monitor must stay serial, not gathered too"
        # Sanity: no 3-awaitable gather (would mean keyword_monitor was
        # gathered too — that breaks its trending-derived keyword seed).
        assert not any(len(c) == 3 for c, _ in gather_calls), (
            "keyword_monitor must stay serial, not gathered with the other two"
        )

    @pytest.mark.asyncio
    async def test_execute_gathers_memory_with_xhs_fetch(self, agent, mock_store):
        """_recall_insights + _fetch_real_data run via one top-level
        asyncio.gather (not 2 serial awaits), so the fast Postgres memory RTT
        hides behind the slow XHS fetch (the long pole).

        Non-vacuous: patches ``asyncio.gather`` in the trend_scout module and
        asserts exactly one gather call whose awaitables include the
        ``_recall_insights`` coroutine. Discriminates by coroutine source
        (qualified name), not by awaitable count alone — the module also has
        #504's internal 2-awaitable gather (_safe_xhs_trending +
        _safe_competitor_analyzer inside _fetch_real_data), so count-based
        filtering cannot disambiguate the top-level gather. If the top-level
        calls are reverted to 2 serial ``await`` assignments, no gather
        contains the _recall_insights coroutine and this test fails.
        """
        import asyncio as _asyncio

        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'

        real_gather = _asyncio.gather
        gather_calls: list[tuple[tuple, dict]] = []

        async def _fake_gather(*awaitables, **kwargs):
            gather_calls.append((awaitables, kwargs))
            return list(await real_gather(*awaitables, **kwargs))

        xhs_trending = MagicMock()
        xhs_trending.ainvoke = AsyncMock(return_value=[])
        keyword_monitor = MagicMock()
        keyword_monitor.ainvoke = AsyncMock(return_value={})
        competitor = MagicMock()
        competitor.ainvoke = AsyncMock(return_value=[])

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        state = {
            "niche": "母婴",
            "account_id": "test_account",
            "phase": WorkflowPhase.IDLE,
        }

        with (
            patch("backend.tools.xhs.trending.xhs_trending", new=xhs_trending),
            patch("backend.tools.xhs.trending.keyword_monitor", new=keyword_monitor),
            patch("backend.tools.xhs.trending.competitor_analyzer", new=competitor),
            patch("backend.agents.trend_scout.asyncio.gather", new=_fake_gather),
        ):
            await agent.execute(state, store=mock_store)

        def _names(awaitables):
            return ",".join(getattr(a, "__qualname__", "") for a in awaitables)

        # The top-level gather: _recall_insights + _fetch_real_data.
        top_level_gathers = [c for c, _ in gather_calls if "_recall_insights" in _names(c)]
        assert len(top_level_gathers) == 1, (
            "_recall_insights + _fetch_real_data must be gathered in one top-level call"
        )
        assert "_fetch_real_data" in _names(top_level_gathers[0]), (
            "top-level gather must also contain _fetch_real_data"
        )

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "trend_scout"
        assert agent.prompt_file == "trend_scout.yaml"
        # SCOUTING task type for trend discovery (blogger_scout moved to MOCK_GEN)
        from backend.config.models import TaskType

        assert agent.task_type == TaskType.SCOUTING


class TestTrendScoutContextPipeline:
    """S4-1 迁移契约：recall 走 S2 管线、prompt 走 compile_prompt、降级可观测。"""

    @pytest.fixture
    def agent(self):
        return TrendScoutAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    def _mock_model(self, agent, content: str, captured: dict):
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.content = content
        mock_model = MagicMock()

        async def _capture(messages, **kwargs):
            captured["messages"] = messages
            return mock_response

        mock_model.ainvoke = _capture
        agent._model = mock_model

    @pytest.mark.asyncio
    async def test_recall_uses_context_pipeline_ns_and_query(self, agent, mock_store):
        """S2 pipeline recall: same ns/query/limit as the old _recall_memory."""
        mock_state = {"niche": "母婴", "account_id": "test_account", "phase": WorkflowPhase.IDLE}
        self._mock_model(agent, '{"trending_topics": []}', {})
        await agent.execute(mock_state, store=mock_store)
        mock_store.asearch.assert_called_once()
        args, kwargs = mock_store.asearch.call_args
        assert args[0] == ("accounts", "test_account", "performance_insights")
        assert kwargs.get("query") == "trend insights"
        assert kwargs.get("limit") == 3

    @pytest.mark.asyncio
    async def test_memory_context_in_l4_format(self, agent, mock_store):
        """L4 block keeps the pre-migration format byte-for-byte."""
        mock_item = MagicMock()
        mock_item.value = {"insight": "美食话题表现好"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])
        mock_state = {"niche": "母婴", "account_id": "test_account", "phase": WorkflowPhase.IDLE}
        self._mock_model(agent, '{"trending_topics": []}', captured := {})
        await agent.execute(mock_state, store=mock_store)
        system = captured["messages"][0].content
        assert "历史趋势洞察：\n- 美食话题表现好\n" in system

    @pytest.mark.asyncio
    async def test_no_placeholder_leaks_into_prompt(self, agent, mock_store):
        """The {memory_context} placeholder must not survive the migration."""
        mock_state = {"niche": "母婴", "account_id": "test_account", "phase": WorkflowPhase.IDLE}
        self._mock_model(agent, '{"trending_topics": []}', captured := {})
        await agent.execute(mock_state, store=mock_store)
        system = captured["messages"][0].content
        assert "{memory_context}" not in system
        assert "你是小红书趋势侦察专家" in system

    @pytest.mark.asyncio
    async def test_no_real_data_degradation_string_and_llm_source(self, agent, mock_store):
        """No realtime data -> the exact degradation text stays in the prompt
        and data_source keeps its pre-migration value (分段等价 + 状态契约)."""
        mock_state = {
            "niche": "母婴",
            "account_id": "test_account",
            "phase": WorkflowPhase.IDLE,
        }
        self._mock_model(agent, '{"trending_topics": []}', captured := {})
        with (
            patch("backend.tools.xhs.trending.xhs_trending") as trending,
            patch("backend.tools.xhs.trending.keyword_monitor") as monitor,
            patch("backend.tools.xhs.trending.competitor_analyzer") as competitor,
        ):
            trending.ainvoke = AsyncMock(return_value=[])
            monitor.ainvoke = AsyncMock(return_value={})
            competitor.ainvoke = AsyncMock(return_value=[])
            result = await agent.execute(mock_state, store=mock_store)
        system = captured["messages"][0].content
        assert "小红书实时数据不可用，基于你的知识生成趋势分析。" in system
        assert result["trend_data"]["data_source"] == "llm_generated"

    @pytest.mark.asyncio
    async def test_real_data_block_in_prompt(self, agent, mock_store):
        """Realtime data -> L5 block with the pre-migration header."""
        mock_state = {
            "niche": "母婴",
            "account_id": "test_account",
            "phase": WorkflowPhase.IDLE,
        }
        self._mock_model(agent, '{"trending_topics": []}', captured := {})
        with (
            patch("backend.tools.xhs.trending.xhs_trending") as trending,
            patch("backend.tools.xhs.trending.keyword_monitor") as monitor,
            patch("backend.tools.xhs.trending.competitor_analyzer") as competitor,
        ):
            trending.ainvoke = AsyncMock(return_value=[{"topic": "露营亲子", "heat_score": 88}])
            monitor.ainvoke = AsyncMock(return_value={})
            competitor.ainvoke = AsyncMock(return_value=[])
            result = await agent.execute(mock_state, store=mock_store)
        system = captured["messages"][0].content
        assert "## 实时数据（来自小红书 API）" in system
        assert "- 露营亲子 (热度: 88)" in system
        assert result["trend_data"]["data_source"] == "real"

    @pytest.mark.asyncio
    async def test_degraded_realtime_emits_context_event(self, agent, mock_store):
        """L5 degradation (no realtime data) with a thread_id lands a
        kind=context event — the §十五 silent-degradation kill. With realtime
        data (HIT) no observation event is emitted."""
        from backend.db.workflow_events import _reset_memory_store, list_events

        mock_state = {
            "niche": "母婴",
            "account_id": "test_account",
            "phase": WorkflowPhase.IDLE,
            "session_id": "thread-tel",
        }
        self._mock_model(agent, '{"trending_topics": []}', {})
        with (
            patch("backend.tools.xhs.trending.xhs_trending") as trending,
            patch("backend.tools.xhs.trending.keyword_monitor") as monitor,
            patch("backend.tools.xhs.trending.competitor_analyzer") as competitor,
        ):
            _reset_memory_store()
            trending.ainvoke = AsyncMock(return_value=[])
            monitor.ainvoke = AsyncMock(return_value={})
            competitor.ainvoke = AsyncMock(return_value=[])
            await agent.execute(mock_state, store=mock_store)
            events = await list_events("thread-tel", kind="context")
            degraded = [
                e for e in events if e.get("event") == "observation" and e.get("mode") == "degraded"
            ]
            assert len(degraded) == 1
            assert degraded[0]["error"] == "realtime_unavailable"
            assert degraded[0]["agent"] == "trend_scout"

            _reset_memory_store()
            trending.ainvoke = AsyncMock(return_value=[{"topic": "x", "heat_score": 1}])
            await agent.execute(mock_state, store=mock_store)
            events = await list_events("thread-tel", kind="context")
            assert not [e for e in events if e.get("event") == "observation"]


class TestXhsReadsThroughTheGateway:
    """S3d 迁移契约：三个平台读点经 Tool Gateway，失败对运行时可见。

    可观测的差别不是降级输出本身 —— trend_scout 迁移前就退化为
    ``data_source="llm_generated"`` —— 而是失败终于有人知道。此前工具吞一次、
    agent 再吞一次，Gateway 若在场只会看到"成功的空读取"，于是"平台读不到"和
    "这个领域确实没热点"是同一个值。
    """

    @pytest.fixture
    def agent(self):
        return TrendScoutAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @staticmethod
    def _tool_raising(exc: Exception) -> MagicMock:
        double = MagicMock()
        double.ainvoke = AsyncMock(side_effect=exc)
        return double

    @staticmethod
    def _tool_returning(rows) -> MagicMock:
        double = MagicMock()
        double.ainvoke = AsyncMock(return_value=rows)
        return double

    def _mock_model(self, agent, captured: dict) -> None:
        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'
        mock_model = MagicMock()

        async def _capture(messages, **kwargs):
            captured["messages"] = messages
            return mock_response

        mock_model.ainvoke = _capture
        agent._model = mock_model

    @pytest.mark.asyncio
    async def test_a_broken_platform_read_is_traced_and_degrades(self, agent, mock_store):
        """Non-vacuous: a direct call would raise out of ``execute``. That it
        returns a degraded result *and* the gateway records all three
        capabilities as failures is what shows the reads are routed."""
        from backend.services.xhs_client import XHSAuthError
        from backend.tools.runtime.bridge import tracing_to

        self._mock_model(agent, {})
        events: list[dict] = []

        async def _sink(event):
            events.append(dict(event))

        broken = XHSAuthError("未配置 Cookie")
        state = {"niche": "母婴", "account_id": "test_account", "session_id": "thread-s3d"}
        with (
            patch("backend.tools.xhs.trending.xhs_trending", new=self._tool_raising(broken)),
            patch("backend.tools.xhs.trending.keyword_monitor", new=self._tool_raising(broken)),
            patch("backend.tools.xhs.trending.competitor_analyzer", new=self._tool_raising(broken)),
            tracing_to(_sink),
        ):
            result = await agent.execute(state, store=mock_store)

        assert result["trend_data"]["data_source"] == "llm_generated"
        xhs_events = [e for e in events if str(e.get("capability", "")).startswith("xhs.")]
        assert {e["capability"] for e in xhs_events} == {
            "xhs.trending",
            "xhs.keyword_monitor",
            "xhs.competitor_analyzer",
        }
        assert all(e["ok"] is False for e in xhs_events)
        assert all(e["error_kind"] == "exception" for e in xhs_events)
        # the caller's thread id rides the event, so it is self-describing
        assert all(e["thread_id"] == "thread-s3d" for e in xhs_events)

    @pytest.mark.asyncio
    async def test_a_working_platform_read_still_reports_real(self, agent, mock_store):
        """The migration must not over-degrade: same doubles, healthy this
        time, and the gateway sees successes."""
        from backend.tools.runtime.bridge import tracing_to

        captured: dict = {}
        self._mock_model(agent, captured)
        events: list[dict] = []

        async def _sink(event):
            events.append(dict(event))

        state = {"niche": "母婴", "account_id": "test_account", "session_id": "thread-s3d"}
        with (
            patch(
                "backend.tools.xhs.trending.xhs_trending",
                new=self._tool_returning([{"topic": "露营亲子", "heat_score": 88}]),
            ),
            patch(
                "backend.tools.xhs.trending.keyword_monitor",
                new=self._tool_returning([{"keyword": "母婴", "post_count": 3, "avg_likes": 12.0}]),
            ),
            patch("backend.tools.xhs.trending.competitor_analyzer", new=self._tool_returning([])),
            tracing_to(_sink),
        ):
            result = await agent.execute(state, store=mock_store)

        assert result["trend_data"]["data_source"] == "real"
        assert "露营亲子" in captured["messages"][0].content
        assert all(e["ok"] is True for e in events if e["capability"].startswith("xhs."))


class TestL1ToolSchemaLayer:
    """P1c-S4：L1 接线在真实 prompt 上走通，但默认不出现。

    默认关是本片的决定（模型到 P2c 才有 tool-calling 通道），所以这里既钉
    "打开后真的进 prompt"，也钉"不打开时一个字都不进" —— 后者才是让 14 个
    agent 的 prompt 与基线快照保持字节不变的那一条。
    """

    @pytest.fixture
    def agent(self):
        return TrendScoutAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    def _mock_model(self, agent, captured: dict) -> None:
        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'
        mock_model = MagicMock()

        async def _capture(messages, **kwargs):
            captured["messages"] = messages
            return mock_response

        mock_model.ainvoke = _capture
        agent._model = mock_model

    def _state(self) -> dict:
        return {"niche": "母婴", "account_id": "test_account", "phase": WorkflowPhase.IDLE}

    @staticmethod
    def _tool(rows) -> MagicMock:
        """A double whose ``ainvoke`` answers with ``rows``.

        ``AsyncMock(return_value=rows)`` alone would not: the Gateway calls
        ``target.ainvoke(payload)``, and on an AsyncMock the child attribute is
        its own mock whose return value is not the parent's.
        """
        double = MagicMock()
        double.ainvoke = AsyncMock(return_value=rows)
        return double

    @pytest.mark.asyncio
    async def test_off_by_default_and_then_really_in_the_prompt(self, agent, mock_store):
        captured: dict = {}
        self._mock_model(agent, captured)

        # Doubles with usable shapes, so a missing L1 cannot be blamed on a
        # degraded run.
        with (
            patch(
                "backend.tools.xhs.trending.xhs_trending",
                new=self._tool([{"topic": "露营亲子", "heat_score": 88}]),
            ),
            patch("backend.tools.xhs.trending.keyword_monitor", new=self._tool([])),
            patch("backend.tools.xhs.trending.competitor_analyzer", new=self._tool([])),
        ):
            await agent.execute(self._state(), store=mock_store)
            assert "可用能力" not in captured["messages"][0].content

            agent.include_tool_schema = True
            self._mock_model(agent, captured)
            await agent.execute(self._state(), store=mock_store)

        system = captured["messages"][0].content
        assert "[可用能力]" in system
        assert "- xhs.trending — " in system
        # L1 sits in the stable prefix: after the policy layer, before recall.
        assert system.index("你是小红书趋势侦察专家") < system.index("[可用能力]")
