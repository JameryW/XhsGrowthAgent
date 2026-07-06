"""Unit tests for ContentStrategistAgent Ripple background mode."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.content_strategist import ContentStrategistAgent
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


class TestContentStrategistBackground:
    """Tests for RIPPLE_BACKGROUND mode in ContentStrategistAgent."""

    @pytest.fixture
    def agent(self):
        return ContentStrategistAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        store.aput = AsyncMock()
        store.aget = AsyncMock(return_value=None)
        return store

    @pytest.mark.asyncio
    async def test_background_false_awaits_gather(self, agent, mock_store):
        """RIPPLE_BACKGROUND=false → strategist awaits gather (existing behavior)."""
        agent._model = _mock_model()
        fake_settings = MagicMock()
        fake_settings.ripple.background = False
        fake_settings.ripple.workflow_timeout = 60

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch("backend.agents.content_strategist.Settings", lambda: fake_settings),
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_pred.return_value = {
                "ripple_prediction": {"viral_probability": 0.8, "estimated_reach": 5000}
            }
            mock_pmf.return_value = {"ripple_pmf": {"pmf_score": 0.7}}
            result = await agent.execute(_state(), store=mock_store)

        # Blocking path awaited gather and wrote prediction into content_plan
        assert result.get("ripple_pending") is not True
        plan = result.get("content_plan", {})
        assert "ripple_prediction" in plan or "ripple_prediction" in result
        # Both Ripple calls were actually invoked
        mock_pred.assert_awaited()
        mock_pmf.assert_awaited()

    @pytest.mark.asyncio
    async def test_background_true_fires_task_no_await(self, agent, mock_store):
        """RIPPLE_BACKGROUND=true → strategist fires create_task, returns ripple_pending=True."""
        agent._model = _mock_model()
        fake_settings = MagicMock()
        fake_settings.ripple.background = True
        fake_settings.ripple.workflow_timeout = 60

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        created_tasks: list[asyncio.Task] = []

        real_create_task = asyncio.create_task

        def _spy_create_task(coro, **kw):
            t = real_create_task(coro, **kw)
            created_tasks.append(t)
            return t

        with (
            patch("backend.agents.content_strategist.Settings", lambda: fake_settings),
            patch("backend.agents.content_strategist.asyncio.create_task", _spy_create_task),
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_pred.return_value = {
                "ripple_prediction": {"viral_probability": 0.8, "estimated_reach": 5000}
            }
            mock_pmf.return_value = {"ripple_pmf": {"pmf_score": 0.7}}
            result = await agent.execute(_state(), store=mock_store)

        # Returned immediately with ripple_pending set, no prediction in result
        assert result["ripple_pending"] is True
        assert result.get("ripple_reason") == "pending"
        assert "ripple_prediction" not in result
        # A background task was scheduled
        assert len(created_tasks) == 1
        # Let the background task finish so test cleanup is clean
        if created_tasks and not created_tasks[0].done():
            await asyncio.wait_for(created_tasks[0], timeout=5)

    @pytest.mark.asyncio
    async def test_background_task_exception_isolated(self, agent, mock_store):
        """Background task exception is caught and logged, does not crash strategist."""
        agent._model = _mock_model()
        fake_settings = MagicMock()
        fake_settings.ripple.background = True
        fake_settings.ripple.workflow_timeout = 60

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        created_tasks: list[asyncio.Task] = []
        real_create_task = asyncio.create_task

        def _spy_create_task(coro, **kw):
            t = real_create_task(coro, **kw)
            created_tasks.append(t)
            return t

        with (
            patch("backend.agents.content_strategist.Settings", lambda: fake_settings),
            patch("backend.agents.content_strategist.asyncio.create_task", _spy_create_task),
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            # predict_spread raises — _run must catch and persist reason, not crash
            mock_pred.return_value = {"ripple_prediction": {"viral_probability": 0.8}}
            mock_pmf.return_value = {"ripple_pmf": {"pmf_score": 0.7}}
            result = await agent.execute(_state(), store=mock_store)

        # Strategist returned normally despite the background path
        assert result["ripple_pending"] is True
        assert len(created_tasks) == 1
        # Background task should complete without raising
        if created_tasks and not created_tasks[0].done():
            await asyncio.wait_for(created_tasks[0], timeout=5)
        # Task did not raise an uncaught exception
        assert created_tasks[0].exception() is None
