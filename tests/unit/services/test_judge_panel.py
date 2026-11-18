"""Tests for the optional heterogeneous judge panel (RQGM scheme 9)."""

from __future__ import annotations

import pytest

from backend.services.judge_panel import (
    JUDGE_PANEL_ENV,
    aggregate_judge_panels,
    judge_panel_enabled,
)


def _panel(copy_score: float, compliance_score: float, *, blocking: bool = False) -> dict:
    return {
        "dimensions": [
            {
                "dimension": "copywriting",
                "score": copy_score,
                "rationale": f"copy-{copy_score}",
                "issues": [],
                "is_blocking": False,
            },
            {
                "dimension": "compliance",
                "score": compliance_score,
                "rationale": f"compliance-{compliance_score}",
                "issues": ["披露不足"] if blocking else [],
                "is_blocking": blocking,
            },
        ],
        "revision_hints": [f"hint-{copy_score}"],
        "summary": f"summary-{copy_score}",
        "bias_warning": "",
    }


def test_panel_consensus_averages_scores_and_or_blocks() -> None:
    consensus = aggregate_judge_panels(
        [_panel(80, 90), _panel(60, 85, blocking=True), _panel(70, 80)],
        judge_ids=["strict", "audience", "commercial"],
        model_ids=["magpie-deepseek-v4.1-flash"] * 3,
    )
    dims = {item["dimension"]: item for item in consensus.dimensions}
    assert dims["copywriting"]["score"] == 70.0
    assert dims["compliance"]["score"] == 85.0
    assert dims["compliance"]["is_blocking"] is True
    assert consensus.as_dict()["panel_size"] == 3
    assert len(consensus.revision_hints) == 3


def test_panel_consensus_reports_dissent_and_agreement() -> None:
    consensus = aggregate_judge_panels(
        [_panel(95, 95), _panel(40, 40), _panel(95, 95)],
        judge_ids=["a", "b", "c"],
        model_ids=["m", "m", "m"],
    )
    assert "copywriting" in consensus.dissent
    assert "compliance" in consensus.dissent
    assert consensus.agreement < 0.65


def test_empty_panel_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one panel"):
        aggregate_judge_panels([])


def test_panel_enable_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(JUDGE_PANEL_ENV, raising=False)
    assert judge_panel_enabled() is False
    monkeypatch.setenv(JUDGE_PANEL_ENV, "yes")
    assert judge_panel_enabled() is True


def test_mismatched_judge_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="judge_ids"):
        aggregate_judge_panels([_panel(80, 90)], judge_ids=["a", "b"])
