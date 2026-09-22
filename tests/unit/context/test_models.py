"""Model contract tests (P1b-S1): frozen-ness, fail-fast niche, provenance."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.context.models import (
    CompiledPrompt,
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
)


def _item(**overrides: object) -> ContextItem:
    base: dict[str, object] = {"body": "内容", "source": "memory:performance_insights"}
    base.update(overrides)
    return ContextItem(**base)  # type: ignore[arg-type]


def test_context_item_defaults_and_provenance() -> None:
    item = _item()
    assert item.confidence == 1.0
    assert item.scope == "task"
    assert item.priority == 0
    assert item.token_cost == 0
    assert item.timestamp is None


def test_context_item_is_frozen() -> None:
    item = _item()
    with pytest.raises(ValidationError):
        item.body = "改写"  # type: ignore[misc]


def test_with_token_cost_returns_copy_and_keeps_original() -> None:
    item = _item()
    priced = item.with_token_cost(42)
    assert priced.token_cost == 42
    assert item.token_cost == 0
    assert priced.body == item.body


def test_confidence_bounds_enforced() -> None:
    _item(confidence=0.0)
    _item(confidence=1.0)
    with pytest.raises(ValidationError):
        _item(confidence=1.5)


def test_run_context_requires_niche_no_default() -> None:
    """D2': a missing niche must fail fast — never compile a silent 母婴."""
    with pytest.raises(ValidationError):
        RunContext(thread_id="t", account_id="acc")  # type: ignore[call-arg]
    ctx = RunContext(thread_id="t", account_id="acc", niche="职场")
    assert ctx.niche == "职场"
    assert ctx.values == {}


def test_retrieval_result_defaults_to_empty_mode() -> None:
    result = RetrievalResult(namespace="performance_insights")
    assert result.mode is RetrievalMode.EMPTY
    assert result.items == ()
    assert result.bodies == ()
    assert result.layer is PromptLayer.L4_MEMORY


def test_retrieval_result_bodies_preserve_recall_order() -> None:
    items = (_item(body="甲"), _item(body="乙"))
    result = RetrievalResult(namespace="content_history", items=items, mode=RetrievalMode.HIT)
    assert result.bodies == ("甲", "乙")


def test_compiled_prompt_render_follows_layer_order() -> None:
    prompt = CompiledPrompt(
        layers={
            PromptLayer.L5_OBSERVATION: "观测",
            PromptLayer.L0_SYSTEM: "策略",
            PromptLayer.L3_TASK: "任务",
        }
    )
    assert prompt.render() == "策略\n\n任务\n\n观测"


def test_run_context_accepts_resolved_values_view() -> None:
    values = {"content_plan": {"selected_topic": "睡眠倒退"}}
    ctx = RunContext(
        thread_id="t",
        account_id="acc",
        niche="母婴",
        values=values,
    )
    assert ctx.values["content_plan"]["selected_topic"] == "睡眠倒退"


def test_timestamp_roundtrip_keeps_tz() -> None:
    ts = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)
    item = _item(timestamp=ts)
    assert item.timestamp is not None
    assert item.timestamp.tzinfo is UTC
