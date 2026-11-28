"""Analyst write side (ledger #45): a scene weight moves only with a baseline."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents import analyst as analyst_module
from backend.agents.analyst import AnalystAgent, _safe_record_visual_feedback
from backend.context.models import RetrievalMode, RetrievalResult
from backend.services.visual_memory import VISUAL_MEMORY_ENV, load_scenes
from backend.state.schema import WorkflowPhase


class _Item:
    def __init__(self, value: Any) -> None:
        self.value = value


class FakeStore:
    def __init__(self) -> None:
        self.data: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
        self.writes = 0

    async def aget(self, namespace: Any, key: str) -> _Item | None:
        value = self.data.get((tuple(namespace), key))
        return _Item(value) if value is not None else None

    async def aput(self, namespace: Any, key: str, value: dict[str, Any]) -> None:
        self.writes += 1
        self.data[(tuple(namespace), key)] = value

    async def asearch(self, namespace: Any, **kwargs: Any) -> list[Any]:
        return []


class BrokenStore:
    async def aget(self, namespace: Any, key: str) -> Any:
        raise RuntimeError("store down")

    async def aput(self, namespace: Any, key: str, value: Any) -> None:
        raise RuntimeError("store down")

    async def asearch(self, namespace: Any, **kwargs: Any) -> list[Any]:
        return []


class TestSafeRecordVisualFeedback:
    async def test_switch_off_writes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(VISUAL_MEMORY_ENV, raising=False)
        store = FakeStore()

        await _safe_record_visual_feedback(
            store,
            "acc",
            "川西自驾旅行",
            collect_ratio=1.8,
            view_ratio=1.2,
            sample_size=5,
        )

        assert store.writes == 0

    async def test_baseline_moves_scene_weight(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(VISUAL_MEMORY_ENV, "1")
        store = FakeStore()

        await _safe_record_visual_feedback(
            store,
            "acc",
            "川西自驾旅行",
            collect_ratio=1.2,
            view_ratio=1.0,
            sample_size=5,
        )

        scenes = await load_scenes(store, "acc")
        assert "travel" in scenes
        assert scenes["travel"].weight == pytest.approx(1.014, abs=1e-3)

    async def test_no_baseline_is_a_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(VISUAL_MEMORY_ENV, "1")
        store = FakeStore()

        await _safe_record_visual_feedback(
            store,
            "acc",
            "川西自驾旅行",
            collect_ratio=None,
            view_ratio=None,
            sample_size=5,
        )

        assert store.writes == 0

    async def test_store_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(VISUAL_MEMORY_ENV, "1")

        # The analytics node must never fail because visual memory cannot write.
        await _safe_record_visual_feedback(
            BrokenStore(),
            "acc",
            "川西自驾旅行",
            collect_ratio=1.5,
            view_ratio=1.1,
            sample_size=5,
        )


class TestAnalystCallSite:
    async def test_execute_passes_gate_ratios(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(VISUAL_MEMORY_ENV, "1")
        agent = AnalystAgent()
        store = FakeStore()
        state = {
            "account_id": "acc",
            "niche": "川西自驾旅行",
            "phase": WorkflowPhase.PUBLISHING,
            "publish_result": {
                "post_id": "123",
                "views": 1000,
                "likes": 50,
                "collects": 60,
                "engagement_rate": 0.05,
            },
        }
        history = RetrievalResult(
            namespace="content_history",
            mode=RetrievalMode.HIT,
            raw_items=[
                {"post_id": "a", "views": 800, "collects": 20},
                {"post_id": "b", "views": 900, "collects": 30},
                {"post_id": "c", "views": 700, "collects": 25},
            ],
        )
        response = MagicMock()
        response.content = '{"insights": [], "recommendations": []}'
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=response)
        feedback = AsyncMock()

        with (
            patch.object(type(agent), "model", new=PropertyMock(return_value=model)),
            patch.object(type(agent), "_ripple_report", AsyncMock(return_value=None)),
            patch.object(analyst_module, "_recall_history", AsyncMock(return_value=history)),
            patch.object(analyst_module, "_safe_record_visual_feedback", feedback),
        ):
            result = await agent.execute(state, store=store)

        assert result["phase"] == WorkflowPhase.ANALYZING
        feedback.assert_awaited_once()
        kwargs = feedback.await_args.kwargs
        assert kwargs["sample_size"] == 3
        assert kwargs["collect_ratio"] is not None
        assert kwargs["collect_ratio"] > 1.0
        assert feedback.await_args.args[2] == "川西自驾旅行"
