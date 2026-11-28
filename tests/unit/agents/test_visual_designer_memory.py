"""Visual designer read side (ledger #45): anchors in prompt, drift recorded."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents.visual_designer import VisualDesignerAgent
from backend.services.visual_memory import (
    VISUAL_MEMORY_ENV,
    ensure_dna,
    load_dna,
)

_PLAN_JSON = """```json
{
  "cover_prompt": "川西自驾封面，暖色调，路线大字",
  "layout_type": "grid",
  "style": "minimalist",
  "color_palette": ["#F5E6D3", "#2B2B2B"],
  "image_count": 2,
  "image_prompts": ["路线图", "实景拼图"]
}
```"""


class _Item:
    def __init__(self, value: Any) -> None:
        self.value = value


class FakeStore:
    """Minimal BaseStore stand-in: aget/aput for memory, asearch for CreativeMemory."""

    def __init__(self) -> None:
        self.data: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}

    async def aget(self, namespace: Any, key: str) -> _Item | None:
        value = self.data.get((tuple(namespace), key))
        return _Item(value) if value is not None else None

    async def aput(self, namespace: Any, key: str, value: dict[str, Any]) -> None:
        self.data[(tuple(namespace), key)] = value

    async def asearch(self, namespace: Any, **kwargs: Any) -> list[Any]:
        return []


def _passing_synergy() -> MagicMock:
    synergy = MagicMock()
    synergy.passed = True
    synergy.recommendations = []
    synergy.as_dict.return_value = {"passed": True, "overall": 82.0, "threshold": 60.0}
    return synergy


@pytest.fixture
def agent() -> VisualDesignerAgent:
    return VisualDesignerAgent()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def state() -> dict[str, Any]:
    return {
        "account_id": "acc",
        "niche": "川西自驾旅行",
        "content_plan": {
            "selected_topic": "川西 7 天自驾攻略",
            "content_angle": "实测避坑",
            "content_type": "图文笔记",
        },
        "copy_content": {"body_text": "川西自驾 7 天，油费与住宿实测。"},
    }


def _model_with(content: str) -> PropertyMock:
    model = MagicMock()
    response = MagicMock()
    response.content = content
    model.ainvoke = AsyncMock(return_value=response)
    prop = PropertyMock(return_value=model)
    return prop


def _prompt_text(prop: PropertyMock) -> str:
    model = prop.return_value
    messages = model.ainvoke.await_args.args[0]
    return "\n".join(str(message.content) for message in messages)


class TestVisualDesignerMemory:
    async def test_switch_off_keeps_plan_shape(
        self,
        agent: VisualDesignerAgent,
        store: FakeStore,
        state: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(VISUAL_MEMORY_ENV, raising=False)
        prop = _model_with(_PLAN_JSON)
        with (
            patch.object(type(agent), "model", new=prop),
            patch(
                "backend.services.content_launch.evaluate_multimodal_synergy",
                return_value=_passing_synergy(),
            ),
        ):
            result = await agent.execute(state, store=store)

        assert "visual_memory" not in result["visual_plan"]
        assert "账号视觉记忆" not in _prompt_text(prop)
        assert not any(key == "visual_memory" for _ns, key in store.data)

    async def test_first_run_freezes_dna(
        self,
        agent: VisualDesignerAgent,
        store: FakeStore,
        state: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(VISUAL_MEMORY_ENV, "1")
        prop = _model_with(_PLAN_JSON)
        with (
            patch.object(type(agent), "model", new=prop),
            patch(
                "backend.services.content_launch.evaluate_multimodal_synergy",
                return_value=_passing_synergy(),
            ),
        ):
            result = await agent.execute(state, store=store)

        report = result["visual_plan"]["visual_memory"]
        assert report["bootstrapped"] is False
        assert report["scene"] == "travel"
        assert "首篇视觉方案" in _prompt_text(prop)
        dna = await load_dna(store, "acc")
        assert dna is not None
        assert dna.primary_color == "#F5E6D3"
        assert dna.secondary_color == "#2B2B2B"

    async def test_anchor_conflict_is_drift_not_rewrite(
        self,
        agent: VisualDesignerAgent,
        store: FakeStore,
        state: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(VISUAL_MEMORY_ENV, "1")
        await ensure_dna(
            store,
            "acc",
            palette=["#111111", "#222222", "#333333"],
            title_weight_ratio=1.8,
        )
        prop = _model_with(_PLAN_JSON)
        with (
            patch.object(type(agent), "model", new=prop),
            patch(
                "backend.services.content_launch.evaluate_multimodal_synergy",
                return_value=_passing_synergy(),
            ),
        ):
            result = await agent.execute(state, store=store)

        plan = result["visual_plan"]
        assert plan["color_palette"] == ["#F5E6D3", "#2B2B2B"]
        assert "palette_off_anchor" in plan["visual_memory"]["drift"]
        assert any("视觉记忆漂移" in hint for hint in plan["revision_hints"])
        assert "#111111" in _prompt_text(prop)
