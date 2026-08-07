"""Unit tests for AnalystAgent."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents.analyst import AnalystAgent
from backend.state.schema import WorkflowPhase


class TestAnalystAgent:
    """Tests for AnalystAgent analytics generation."""

    @pytest.fixture
    def agent(self):
        """Create analyst instance."""
        return AnalystAgent()

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph store."""
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        store.aput = AsyncMock()
        return store

    @pytest.fixture
    def mock_state(self):
        """Mock state with publish result."""
        return {
            "account_id": "test_account",
            "phase": WorkflowPhase.PUBLISHING,
            "publish_result": {
                "post_id": "123",
                "views": 1000,
                "likes": 50,
                "engagement_rate": 0.05,
            },
        }

    @pytest.mark.asyncio
    async def test_execute_returns_analytics(self, agent, mock_state, mock_store):
        """Execute returns analytics in result."""
        mock_response = MagicMock()
        mock_response.content = """```json
{
  "insights": ["美食内容互动率高", "周末发布效果好"],
  "recommendations": ["增加美食内容比例"],
  "metrics": {"engagement_rate": 0.05}
}
```"""

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            result = await agent.execute(mock_state, store=mock_store)

        assert "analytics" in result
        assert result["phase"] == WorkflowPhase.ANALYZING
        assert "insights" in result["analytics"]

    @pytest.mark.asyncio
    async def test_execute_recalls_content_history(self, agent, mock_state, mock_store):
        """Execute recalls content history."""
        mock_item = MagicMock()
        mock_item.value = {"title": "Past Post", "engagement": 80}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        mock_response = MagicMock()
        mock_response.content = '{"insights": []}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            await agent.execute(mock_state, store=mock_store)

        # Memory recall was called
        mock_store.asearch.assert_called()

    @pytest.mark.asyncio
    async def test_execute_stores_insights(self, agent, mock_state, mock_store):
        """Execute stores insights to memory."""
        mock_response = MagicMock()
        mock_response.content = '{"insights": ["美食效果好"], "recommendations": []}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            await agent.execute(mock_state, store=mock_store)

        # Insights stored
        assert mock_store.aput.called

    @pytest.mark.asyncio
    async def test_execute_gathers_memory_and_ripple_concurrently(
        self, agent, mock_state, mock_store
    ):
        """_recall_memory + _ripple_report run concurrently via asyncio.gather.

        Discriminator: analyst module now has TWO gather calls — the top-level
        memory+ripple gather and the post-publish store-write gather. Both patch
        backend.agents.analyst.asyncio.gather; we filter captured calls for the
        one whose awaitables are the _recall_memory + _ripple_report coroutines
        (qualname check). Serial implementation never calls gather with that pair.
        """
        captured: list[tuple] = []

        async def _fake_gather(*awaitables, **kwargs):
            captured.append(awaitables)
            results = []
            for aw in awaitables:
                results.append(await aw)
            return tuple(results)

        mock_response = MagicMock()
        mock_response.content = '{"insights": [], "recommendations": []}'

        with (
            patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop,
            patch("backend.agents.analyst.asyncio.gather", side_effect=_fake_gather),
        ):
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            await agent.execute(mock_state, store=mock_store)

        # Find the memory+ripple gather call (exactly 2 awaitables whose
        # coroutines are _recall_memory + _ripple_report).
        memory_ripple_calls = []
        for awaitables in captured:
            if len(awaitables) != 2:
                continue
            qualnames = sorted(getattr(aw, "__qualname__", "") for aw in awaitables)
            if qualnames == ["AnalystAgent._ripple_report", "BaseAgent._recall_memory"]:
                memory_ripple_calls.append(awaitables)
        assert len(memory_ripple_calls) == 1, (
            f"expected 1 memory+ripple gather, got {len(memory_ripple_calls)}"
        )
        awaitables = memory_ripple_calls[0]
        assert len(awaitables) == 2, f"expected 2 awaitables, got {len(awaitables)}"

    @pytest.mark.asyncio
    async def test_ripple_report_returns_report(self, agent, mock_state, mock_store):
        """_ripple_report returns report when job_id exists."""
        state_with_ripple = {
            **mock_state,
            "content_plan": {"ripple_prediction": {"ripple_job_id": "job_123"}},
        }

        with patch("backend.tools.ripple.integration.get_report") as mock_get_report:
            mock_get_report.return_value = {
                "rounds": [{"content": "Report text"}],
            }

            report = await agent._ripple_report(state_with_ripple)

        assert report == "Report text"

    @pytest.mark.asyncio
    async def test_ripple_report_none_when_no_job_id(self, agent):
        """_ripple_report returns None when no job_id."""
        state = {"content_plan": {}}
        result = await agent._ripple_report(state)
        assert result is None

    @pytest.mark.asyncio
    async def test_ripple_report_handles_error(self, agent):
        """_ripple_report handles errors gracefully."""
        state = {"content_plan": {"ripple_prediction": {"ripple_job_id": "job_123"}}}

        with patch("backend.tools.ripple.integration.get_report") as mock_get_report:
            mock_get_report.side_effect = Exception("Ripple error")

            result = await agent._ripple_report(state)

        assert result is None

    def test_compare_prediction_vs_actual(self, agent):
        """_compare_prediction_vs_actual returns comparison dict."""
        prediction = {"estimated_reach": 5000, "viral_probability": 0.3}
        actual = {"engagement_rate": 0.05}

        result = agent._compare_prediction_vs_actual(prediction, actual)

        assert result["predicted_reach"] == 5000
        assert result["predicted_viral_prob"] == 0.3
        assert result["actual_engagement_rate"] == 0.05

    def test_compare_prediction_vs_actual_none_prediction(self, agent):
        """_compare_prediction_vs_actual handles None prediction."""
        result = agent._compare_prediction_vs_actual(None, {"rate": 0.05})
        assert result == {}

    @pytest.mark.asyncio
    async def test_execute_with_ripple_report(self, agent, mock_state, mock_store):
        """Execute includes ripple comparison when report exists."""
        state_with_ripple = {
            **mock_state,
            "content_plan": {
                "ripple_prediction": {"ripple_job_id": "job_123", "estimated_reach": 5000}
            },
        }

        mock_response = MagicMock()
        mock_response.content = '{"insights": [], "recommendations": []}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            with patch.object(agent, "_ripple_report", AsyncMock(return_value="Report")):
                result = await agent.execute(state_with_ripple, store=mock_store)

        assert "ripple_comparison" in result["analytics"]

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "analyst"
        assert agent.prompt_file == "analyst.yaml"

    @pytest.mark.asyncio
    async def test_ripple_report_timeout_returns_none(self, agent):
        """_ripple_report 超时时返回 None"""
        state = {"content_plan": {"ripple_prediction": {"ripple_job_id": "job-timeout"}}}

        # asyncio.wait_for evaluates get_report(job_id) before invoking, so the
        # mock coroutine must be closed to avoid a 'never awaited' leak.
        def _fake_wait_for(coro, timeout, *args, **kwargs):
            coro.close()
            raise TimeoutError()

        with (
            patch("backend.tools.ripple.integration.get_report", new_callable=AsyncMock),
            patch.object(agent, "_ripple_cancel", new_callable=AsyncMock),
            patch("asyncio.wait_for", side_effect=_fake_wait_for),
        ):
            result = await agent._ripple_report(state)

        assert result is None

    @pytest.mark.asyncio
    async def test_ripple_cancel_calls_service(self, agent):
        """_ripple_cancel 调用 RippleService.cancel_simulation"""
        mock_service = MagicMock()
        mock_service.cancel_simulation = AsyncMock(
            return_value={"cancelled": True, "job_id": "job-cancel", "status": "cancelled"}
        )

        with patch("backend.services.ripple_service.RippleService") as mock_cls:
            mock_cls.get_instance.return_value = mock_service
            await agent._ripple_cancel("job-cancel")

        mock_service.cancel_simulation.assert_called_once_with("job-cancel")

    @pytest.mark.asyncio
    async def test_ripple_cancel_handles_empty_job_id(self, agent):
        """_ripple_cancel 对空 job_id 不调用服务"""
        with patch("backend.services.ripple_service.RippleService") as mock_cls:
            await agent._ripple_cancel("")

        mock_cls.get_instance.assert_not_called()

    @pytest.mark.asyncio
    async def test_ripple_cancel_handles_exception(self, agent):
        """_ripple_cancel 对异常做优雅降级（不抛出）"""
        mock_service = MagicMock()
        mock_service.cancel_simulation = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("backend.services.ripple_service.RippleService") as mock_cls:
            mock_cls.get_instance.return_value = mock_service
            # 不应抛出异常
            await agent._ripple_cancel("job-err")


@pytest.mark.asyncio
async def test_safe_evolve_swallows_errors():
    """_safe_evolve (fire-and-forget wrapper) never raises — errors just log."""
    from backend.agents.analyst import _safe_evolve

    with patch(
        "backend.db.evaluator_config.maybe_evolve",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        # must not raise
        await _safe_evolve("acct1")


@pytest.mark.asyncio
async def test_safe_evolve_passes_account_id():
    """_safe_evolve forwards a string account_id; non-str degrades to None."""
    from backend.agents.analyst import _safe_evolve

    with patch(
        "backend.db.evaluator_config.maybe_evolve", AsyncMock(return_value={"action": "skip"})
    ) as me:
        await _safe_evolve("acct1")
        me.assert_awaited_once_with("acct1")
    with patch(
        "backend.db.evaluator_config.maybe_evolve", AsyncMock(return_value={"action": "skip"})
    ) as me:
        await _safe_evolve(None)
        me.assert_awaited_once_with(None)


class TestAnalystWriteGather:
    """Post-publish store-write gather: store_insight + store_strategy_note runs
    concurrently via asyncio.gather with per-row _safe_* isolation (write-gather
    variant #512).

    Uses the call-overlap discriminator (#519/#520 pattern): each mocked write
    records a start/finish timestamp and yields control via asyncio.sleep(0).
    Under a real asyncio.gather the writes overlap; under serial ``await`` loops
    the intervals are disjoint. This avoids patching asyncio.gather globally
    (the shared-asyncio-module leak trap from #515).
    """

    @pytest.fixture
    def agent(self):
        return AnalystAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        store.aput = AsyncMock()
        store.aget = AsyncMock(return_value=None)
        return store

    @staticmethod
    def _overlapping(a: tuple[float, float], b: tuple[float, float]) -> bool:
        """True if the two [start, finish] windows overlap in time."""
        return a[0] <= b[1] and b[0] <= a[1]

    @pytest.mark.asyncio
    async def test_stores_insights_and_notes_concurrently(self, agent, mock_store):
        """store_insight + store_strategy_note writes overlap under gather.

        Discriminator: each mocked MemoryManager write records a start/finish
        window and yields via asyncio.sleep(0). Under gather the insight write
        and the note write overlap; under serial loops they don't. Reverts to
        serial → overlap absent → assertion fails.
        """
        windows: dict[str, list[float]] = {}

        async def _tracked_store_insight(self_mm, store, insight, metadata):
            start = asyncio.get_event_loop().time()
            windows.setdefault("insight", [start, start])
            await asyncio.sleep(0)  # yield so the sibling gather task can start
            windows["insight"][1] = asyncio.get_event_loop().time()

        async def _tracked_store_strategy_note(self_mm, store, note, data):
            start = asyncio.get_event_loop().time()
            windows.setdefault("note", [start, start])
            await asyncio.sleep(0)  # yield so the sibling gather task can start
            windows["note"][1] = asyncio.get_event_loop().time()

        mock_response = MagicMock()
        mock_response.content = '{"insights": ["i1", "i2", "i3"], "recommendations": ["r1", "r2"]}'
        mock_state = {
            "account_id": "test_account",
            "phase": WorkflowPhase.PUBLISHING,
            "publish_result": {"post_id": "p1"},
        }

        with (
            patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop,
            patch(
                "backend.memory.store.MemoryManager.store_insight",
                new=_tracked_store_insight,
            ),
            patch(
                "backend.memory.store.MemoryManager.store_strategy_note",
                new=_tracked_store_strategy_note,
            ),
        ):
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model
            await agent.execute(mock_state, store=mock_store)

        assert "insight" in windows and "note" in windows
        assert self._overlapping(
            (windows["insight"][0], windows["insight"][1]),
            (windows["note"][0], windows["note"][1]),
        ), "store_insight + store_strategy_note must overlap (concurrent), not run serially"

    @pytest.mark.asyncio
    async def test_partial_write_failure_does_not_abort_others(self, agent, mock_store):
        """A failing store_insight write does not abort the remaining writes.

        Wrapper isolation: _safe_store_insight/_safe_store_strategy_note swallow
        per-row exceptions. With 3 insights + 2 recs, make the 2nd store_insight
        call raise; the other 2 insights + both recs must still be stored.
        Reverts to bare gather (no wrapper) → 2nd failure aborts the rest → the
        later insight + recs are never stored → assertion fails. Reverts to
        serial → 2nd failure aborts the loop → recs never run → fails too.
        """
        stored_insights: list[str] = []
        stored_notes: list[str] = []
        insight_call_count = 0

        async def _flaky_store_insight(self_mm, store, insight, metadata):
            nonlocal insight_call_count
            insight_call_count += 1
            if insight_call_count == 2:
                raise RuntimeError("simulated 2nd-write failure")
            stored_insights.append(insight)

        async def _tracking_store_strategy_note(self_mm, store, note, data):
            stored_notes.append(note)

        mock_response = MagicMock()
        mock_response.content = '{"insights": ["i1", "i2", "i3"], "recommendations": ["r1", "r2"]}'
        mock_state = {
            "account_id": "test_account",
            "phase": WorkflowPhase.PUBLISHING,
            "publish_result": {"post_id": "p1"},
        }

        with (
            patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop,
            patch(
                "backend.memory.store.MemoryManager.store_insight",
                new=_flaky_store_insight,
            ),
            patch(
                "backend.memory.store.MemoryManager.store_strategy_note",
                new=_tracking_store_strategy_note,
            ),
        ):
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model
            await agent.execute(mock_state, store=mock_store)

        # 2nd insight failed; 1st + 3rd must still be stored (wrapper isolation).
        assert stored_insights == ["i1", "i3"], (
            f"expected i1 + i3 stored (2nd failed, isolated), got {stored_insights}"
        )
        # All recs stored regardless of the insight failure.
        assert stored_notes == ["r1", "r2"], f"expected both recs stored, got {stored_notes}"
