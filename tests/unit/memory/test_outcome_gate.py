"""Outcome-Verified Epistemic Gate tests (MemCredit/DISCERN-style guard)."""

from __future__ import annotations

from backend.memory.hy.promotion import (
    NEGATIVE_PITFALL,
    VERIFIED_PATTERN,
    evaluate_outcome_gate,
    memory_metadata,
)


def _history(*, rate: float = 0.1, views: int = 1000, count: int = 10) -> list[dict]:
    return [
        {
            "post_id": f"hist-{index}",
            "views": views,
            "collects": int(views * rate),
            "likes": 10,
        }
        for index in range(count)
    ]


def test_outperforming_collect_rate_is_verified() -> None:
    result = evaluate_outcome_gate(
        {"post_id": "new", "views": 1000, "collects": 200},
        _history(rate=0.1),
    )
    assert result.allowed is True
    assert result.verdict == VERIFIED_PATTERN
    assert result.reason == "collect_rate_outperforms"
    assert result.collect_ratio == 2.0
    assert result.sample_size == 10


def test_outperforming_views_is_verified() -> None:
    result = evaluate_outcome_gate(
        {"post_id": "new", "views": 1500, "collects": 100},
        _history(rate=0.1, views=1000),
    )
    assert result.allowed is True
    assert result.reason == "views_outperform"
    assert result.view_ratio == 1.5


def test_below_baseline_is_negative_pitfall() -> None:
    result = evaluate_outcome_gate(
        {"post_id": "new", "views": 500, "collects": 20},
        _history(rate=0.1, views=1000),
    )
    assert result.allowed is False
    assert result.verdict == NEGATIVE_PITFALL
    assert result.pool == NEGATIVE_PITFALL
    assert result.reason == "below_baseline"


def test_human_approval_bypasses_measurement() -> None:
    result = evaluate_outcome_gate(
        {"post_id": "new", "views": 1, "collects": 0},
        _history(),
        human_approved=True,
    )
    assert result.allowed is True
    assert result.reason == "human_approved"
    assert result.human_approved is True


def test_insufficient_history_blocks_promotion() -> None:
    result = evaluate_outcome_gate({"post_id": "new", "views": 1000, "collects": 300})
    assert result.allowed is False
    assert result.reason == "insufficient_history"
    assert result.sample_size == 0


def test_current_post_is_excluded_from_its_own_baseline() -> None:
    history = _history()
    history.append({"post_id": "new", "views": 1000, "collects": 200})
    result = evaluate_outcome_gate({"post_id": "new", "views": 1000, "collects": 200}, history)
    assert result.sample_size == 10
    assert result.collect_ratio == 2.0


def test_memory_metadata_records_pool_and_evidence() -> None:
    result = evaluate_outcome_gate({"post_id": "new", "views": 1000, "collects": 200}, _history())
    metadata = memory_metadata(result)
    assert metadata["verification"] == VERIFIED_PATTERN
    assert metadata["memory_pool"] == VERIFIED_PATTERN
    assert metadata["outcome_gate"]["collect_ratio"] == 2.0
