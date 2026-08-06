"""Unit tests for ContentStrategistAgent._schedule_ripple_background.

The background branch (``Settings().ripple.background and thread_id``) fires
Ripple predict+pmf as a fire-and-forget task, persists the result to the store
namespace ``("ripple", thread_id)`` key ``result``, and emits a
``WORKFLOW_DATA_UPDATED`` event. Exceptions inside the background task must be
isolated — logged via the done callback, never crash the main workflow chain.

The existing ``test_ripple_background.py`` only asserts the strategist returns
``ripple_pending=True`` and that a task is scheduled; it never waits for the
task body nor asserts on ``store.aput``. These tests pin the persistence
contract (namespace, key, payload shape) and the timeout / unreachable /
stale-delete / event-emit / exception-isolation paths that PR#466 added.

Implementation note: the background task runs after ``execute`` returns, so the
patches on the agent's Ripple helpers must stay active while the task drains.
Each test therefore awaits ``spy.drain()`` *inside* the ``with`` block.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.content_strategist import ContentStrategistAgent
from backend.realtime import EventType
from backend.services.ripple_service import RippleTimeoutError
from backend.state.schema import WorkflowPhase


def _state(**overrides):
    base = {
        "account_id": "test_account",
        "session_id": "thread-bg-1",
        "phase": WorkflowPhase.SCOUTING,
        "trend_data": {"trending_topics": ["美食探店"]},
    }
    base.update(overrides)
    return base


def _mock_model():
    resp = MagicMock()
    resp.content = (
        '{"selected_topic": "美食探店", "content_angle": "探店攻略", "content_type": "图文笔记"}'
    )
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=resp)
    return model


def _background_settings():
    """Settings mock with background=True so execute takes the fire-and-forget branch."""
    fake = MagicMock()
    fake.ripple.background = True
    fake.ripple.workflow_timeout = 60
    fake.ripple.default_max_waves = 3
    fake.ripple.default_simulation_horizon = "12h"
    fake.ripple.default_ensemble_runs = 1
    return fake


def _scorer():
    scorer = AsyncMock()
    scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})
    return scorer


def _ripple_put_call(mock_store) -> tuple:
    """Return the (namespace, key, value) of the store.aput call targeting the
    ('ripple', thread_id) namespace — the background-persistence contract.

    Other aput calls (creative-memory deposit_play) hit different namespaces and
    must not be confused with the Ripple result write.
    """
    for call in mock_store.aput.await_args_list:
        ns = call.args[0] if call.args else call.kwargs.get("namespace")
        if ns and ns[0] == "ripple":
            key = call.args[1] if len(call.args) > 1 else call.kwargs.get("key")
            value = call.kwargs.get("value")
            return ns, key, value
    raise AssertionError(
        f"no store.aput call to ('ripple', *) namespace; calls={mock_store.aput.await_args_list}"
    )


class _BackgroundTaskSpy:
    """Capture asyncio.create_task so tests can await the background coroutine.

    The strategist returns immediately after scheduling; without awaiting the
    spawned task, ``store.aput`` would never be observed and the task could be
    GC'd mid-flight. We spy on ``create_task`` and expose the captured task.
    """

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []
        self._real = asyncio.create_task

    def __call__(self, coro, **kw):
        t = self._real(coro, **kw)
        self.tasks.append(t)
        return t

    async def drain(self, timeout: float = 5.0) -> None:
        if self.tasks and not self.tasks[0].done():
            await asyncio.wait_for(self.tasks[0], timeout=timeout)


class TestScheduleRippleBackground:
    """Persistence + isolation contracts for the background Ripple branch."""

    @pytest.fixture
    def agent(self):
        return ContentStrategistAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        store.aput = AsyncMock()
        store.aget = AsyncMock(return_value=None)
        store.adelete = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_background_true_returns_pending_no_blocking(self, agent, mock_store):
        """background=True → execute returns ripple_pending=True, ripple_reason=pending,
        and does NOT block on the Ripple calls (predict/pmf never awaited before return)."""
        agent._model = _mock_model()
        spy = _BackgroundTaskSpy()
        emit_mock = MagicMock()

        with (
            patch("backend.agents.content_strategist.Settings", _background_settings),
            patch("backend.agents.content_strategist.asyncio.create_task", spy),
            patch.object(
                agent,
                "_ripple_predict",
                new_callable=AsyncMock,
                return_value={"viral_probability": 0.8},
            ) as mock_pred,
            patch.object(
                agent,
                "_ripple_validate_pmf",
                new_callable=AsyncMock,
                return_value={"pmf_score": 0.7},
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", _scorer()),
            patch(
                "backend.realtime.EventBusService.get_instance",
                return_value=MagicMock(emit=emit_mock),
            ),
        ):
            result = await agent.execute(_state(), store=mock_store)
            # Predict/pmf NOT awaited yet — execute returned before the task ran.
            assert mock_pred.await_count == 0
            assert mock_pmf.await_count == 0
            await spy.drain()

        assert result["ripple_pending"] is True
        assert result["ripple_reason"] == "pending"
        assert "ripple_prediction" not in result
        assert result["content_plan"]["ripple_pending"] is True
        assert len(spy.tasks) == 1
        # After draining, the background task did invoke the Ripple helpers.
        assert mock_pred.await_count == 1
        assert mock_pmf.await_count == 1

    @pytest.mark.asyncio
    async def test_background_persists_result_to_store(self, agent, mock_store):
        """Successful background run writes ripple_prediction + ripple_pmf to
        store namespace ('ripple', thread_id) key 'result'."""
        agent._model = _mock_model()
        spy = _BackgroundTaskSpy()
        emit_mock = MagicMock()

        pred = {"viral_probability": 0.8, "estimated_reach": 5000}
        pmf = {"pmf_score": 0.7, "risk_factors": []}

        with (
            patch("backend.agents.content_strategist.Settings", _background_settings),
            patch("backend.agents.content_strategist.asyncio.create_task", spy),
            patch.object(
                agent, "_ripple_predict", new_callable=AsyncMock, return_value=pred
            ) as mock_pred,
            patch.object(
                agent, "_ripple_validate_pmf", new_callable=AsyncMock, return_value=pmf
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", _scorer()),
            patch(
                "backend.realtime.EventBusService.get_instance",
                return_value=MagicMock(emit=emit_mock),
            ),
        ):
            await agent.execute(_state(), store=mock_store)
            await spy.drain()

        mock_pred.assert_awaited_once()
        mock_pmf.assert_awaited_once()
        ns, key, value = _ripple_put_call(mock_store)
        assert ns == ("ripple", "thread-bg-1")
        assert key == "result"
        assert value["ripple_pending"] is False
        assert value["ripple_prediction"] == pred
        assert value["ripple_pmf"] == pmf
        emit_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_background_timeout_persists_reason_and_job_id(self, agent, mock_store):
        """RippleTimeoutError from _ripple_predict → persist ripple_reason='timeout'
        + ripple_job_id, then call _ripple_cancel (best-effort cancel)."""
        agent._model = _mock_model()
        spy = _BackgroundTaskSpy()

        with (
            patch("backend.agents.content_strategist.Settings", _background_settings),
            patch("backend.agents.content_strategist.asyncio.create_task", spy),
            patch.object(
                agent,
                "_ripple_predict",
                new_callable=AsyncMock,
                side_effect=RippleTimeoutError("job-timeout-bg", 60.0),
            ),
            patch.object(
                agent,
                "_ripple_validate_pmf",
                new_callable=AsyncMock,
                return_value={"pmf_score": 0.7},
            ),
            patch.object(agent, "_ripple_cancel", new_callable=AsyncMock) as mock_cancel,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", _scorer()),
            patch(
                "backend.realtime.EventBusService.get_instance",
                return_value=MagicMock(emit=MagicMock()),
            ),
        ):
            await agent.execute(_state(), store=mock_store)
            await spy.drain()

        _, _, value = _ripple_put_call(mock_store)
        assert value["ripple_reason"] == "timeout"
        assert value["ripple_job_id"] == "job-timeout-bg"
        assert value["ripple_pending"] is False
        mock_cancel.assert_awaited_once_with("job-timeout-bg")

    @pytest.mark.asyncio
    async def test_background_unreachable_persists_reason(self, agent, mock_store):
        """A generic Exception escaping the gather (not RippleTimeoutError) is caught
        by the _run safety net and persists ripple_reason='unreachable'.

        _ripple_predict normally swallows generic errors into None (which the
        prediction-shape branch maps to unreachable). To exercise the bare
        ``except Exception`` arm in _run directly, we make _ripple_predict raise
        a non-timeout exception that escapes gather.
        """
        agent._model = _mock_model()
        spy = _BackgroundTaskSpy()

        with (
            patch("backend.agents.content_strategist.Settings", _background_settings),
            patch("backend.agents.content_strategist.asyncio.create_task", spy),
            patch.object(
                agent,
                "_ripple_predict",
                new_callable=AsyncMock,
                side_effect=RuntimeError("ripple down"),
            ),
            patch.object(
                agent,
                "_ripple_validate_pmf",
                new_callable=AsyncMock,
                return_value={"pmf_score": 0.7},
            ),
            patch("backend.tools.analysis.topic_scorer.topic_scorer", _scorer()),
            patch(
                "backend.realtime.EventBusService.get_instance",
                return_value=MagicMock(emit=MagicMock()),
            ),
        ):
            await agent.execute(_state(), store=mock_store)
            await spy.drain()

        _, _, value = _ripple_put_call(mock_store)
        assert value["ripple_reason"] == "unreachable"
        assert value["ripple_pending"] is False
        assert "ripple_prediction" not in value

    @pytest.mark.asyncio
    async def test_background_clears_stale_result_before_schedule(self, agent, mock_store):
        """Reangle/retopic re-runs _schedule_ripple_background → _safe_store_delete
        must delete the stale ('ripple', thread_id) 'result' key BEFORE the new run,
        so ripple_finalize/late_recheck never read the previous angle's prediction
        as if it were fresh (PR#466 stale-store race fix)."""
        agent._model = _mock_model()
        spy = _BackgroundTaskSpy()

        with (
            patch("backend.agents.content_strategist.Settings", _background_settings),
            patch("backend.agents.content_strategist.asyncio.create_task", spy),
            patch.object(
                agent,
                "_ripple_predict",
                new_callable=AsyncMock,
                return_value={"viral_probability": 0.8},
            ),
            patch.object(
                agent,
                "_ripple_validate_pmf",
                new_callable=AsyncMock,
                return_value={"pmf_score": 0.7},
            ),
            patch("backend.tools.analysis.topic_scorer.topic_scorer", _scorer()),
            patch(
                "backend.realtime.EventBusService.get_instance",
                return_value=MagicMock(emit=MagicMock()),
            ),
        ):
            await agent.execute(_state(), store=mock_store)
            # delete happens synchronously inside _schedule_ripple_background,
            # before the task body's aput — so it's already called by the time
            # execute returns.
            mock_store.adelete.assert_awaited_once()
            ns, key = mock_store.adelete.await_args.args[0], mock_store.adelete.await_args.args[1]
            assert ns == ("ripple", "thread-bg-1")
            assert key == "result"
            await spy.drain()

        # Exactly one Ripple-namespace put (the fresh result), and it followed
        # the synchronous delete — no stale double-write.
        ripple_puts = [c for c in mock_store.aput.await_args_list if c.args[0][0] == "ripple"]
        assert len(ripple_puts) == 1

    @pytest.mark.asyncio
    async def test_background_task_exception_does_not_crash_chain(self, agent, mock_store):
        """An exception inside the background task body is caught by _run and logged
        via the _on_done done-callback; the main execute() chain returns normally
        with ripple_pending=True (never raises)."""
        agent._model = _mock_model()
        spy = _BackgroundTaskSpy()

        with (
            patch("backend.agents.content_strategist.Settings", _background_settings),
            patch("backend.agents.content_strategist.asyncio.create_task", spy),
            patch.object(
                agent,
                "_ripple_predict",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch.object(
                agent,
                "_ripple_validate_pmf",
                new_callable=AsyncMock,
                return_value={"pmf_score": 0.7},
            ),
            patch("backend.tools.analysis.topic_scorer.topic_scorer", _scorer()),
            patch(
                "backend.realtime.EventBusService.get_instance",
                return_value=MagicMock(emit=MagicMock()),
            ),
        ):
            result = await agent.execute(_state(), store=mock_store)
            await spy.drain()

        assert result["ripple_pending"] is True
        assert result["ripple_reason"] == "pending"
        assert len(spy.tasks) == 1
        assert spy.tasks[0].done()
        assert spy.tasks[0].exception() is None

    @pytest.mark.asyncio
    async def test_background_emits_workflow_data_updated_event(self, agent, mock_store):
        """On a successful background run, a WORKFLOW_DATA_UPDATED event is emitted
        with data_type='ripple_ready' so the frontend can refresh Ripple panels."""
        agent._model = _mock_model()
        spy = _BackgroundTaskSpy()
        emit_mock = MagicMock()

        with (
            patch("backend.agents.content_strategist.Settings", _background_settings),
            patch("backend.agents.content_strategist.asyncio.create_task", spy),
            patch.object(
                agent,
                "_ripple_predict",
                new_callable=AsyncMock,
                return_value={"viral_probability": 0.8, "estimated_reach": 5000},
            ),
            patch.object(
                agent,
                "_ripple_validate_pmf",
                new_callable=AsyncMock,
                return_value={"pmf_score": 0.7},
            ),
            patch("backend.tools.analysis.topic_scorer.topic_scorer", _scorer()),
            patch(
                "backend.realtime.EventBusService.get_instance",
                return_value=MagicMock(emit=emit_mock),
            ),
        ):
            await agent.execute(_state(), store=mock_store)
            await spy.drain()

        emit_mock.assert_called_once()
        event_type = emit_mock.call_args.args[0]
        kwargs = emit_mock.call_args.kwargs
        assert event_type == EventType.WORKFLOW_DATA_UPDATED
        assert kwargs["thread_id"] == "thread-bg-1"
        assert kwargs["payload"]["data_type"] == "ripple_ready"
        assert "ripple_prediction" in kwargs["payload"]["data"]
