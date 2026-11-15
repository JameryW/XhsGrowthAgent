"""Context compiler marginal-utility budget tests (MemCredit-style overlap)."""

from __future__ import annotations

from backend.context.compiler import (
    apply_item_budget,
    marginal_utility,
    token_overlap_ratio,
)
from backend.context.models import ContextItem, PromptLayer


def _item(body: str, *, source: str = "memory", priority: int = 0) -> ContextItem:
    return ContextItem(body=body, source=source, priority=priority)


def test_token_overlap_ratio_detects_duplicate_language() -> None:
    selected = set("小红书运营干货")
    assert token_overlap_ratio("小红书运营干货", selected) == 1.0
    assert token_overlap_ratio("旅行摄影", selected) == 0.0


def test_marginal_utility_penalises_duplicate() -> None:
    selected = set("小红书运营干货")
    duplicate = _item("小红书运营干货")
    novel = _item("旅行摄影构图技巧")
    assert marginal_utility(duplicate, selected) < marginal_utility(novel, selected)


def test_budget_keeps_unique_item_over_duplicate() -> None:
    duplicate_a = _item("小红书运营干货小红书运营干货")
    duplicate_b = _item("小红书运营干货小红书运营干货")
    unique = _item("旅行摄影构图技巧" * 6)
    items = {
        PromptLayer.L5_OBSERVATION: (duplicate_a, duplicate_b, unique),
    }
    trimmed = apply_item_budget(items, 64, overlap_penalty=0.8)
    bodies = [item.body for layer in trimmed.values() for item in layer]
    assert any("旅行摄影" in body for body in bodies)
    assert len(bodies) == 2


def test_zero_penalty_restores_legacy_tail_drop() -> None:
    first = _item("a" * 100)
    second = _item("b" * 40)
    items = {PromptLayer.L5_OBSERVATION: (first, second)}
    trimmed = apply_item_budget(items, budget=30, overlap_penalty=0.0)
    assert trimmed[PromptLayer.L5_OBSERVATION] == (first,)


def test_static_layers_are_never_trimmed() -> None:
    system = _item("system prompt " * 10)
    observation = _item("observation " * 10)
    items = {
        PromptLayer.L0_SYSTEM: (system,),
        PromptLayer.L5_OBSERVATION: (observation,),
    }
    trimmed = apply_item_budget(items, budget=1, overlap_penalty=0.15)
    assert trimmed[PromptLayer.L0_SYSTEM] == (system,)
    assert trimmed[PromptLayer.L5_OBSERVATION] == ()
