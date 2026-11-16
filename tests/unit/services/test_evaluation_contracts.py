"""Tests for phase-5 evaluation and generation contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.context.models import CompiledPrompt, PromptLayer
from backend.services.evaluation_contracts import (
    CandidateScore,
    PolicyAnchor,
    build_swa_sandwich,
    evaluate_cover_layout,
    evaluate_groupwise,
    policy_reset_decision,
    ptgs_temperature,
    route_model_capability,
    shannon_entropy,
)


def test_capability_routing_defaults_to_existing_magpie_route() -> None:
    decision = route_model_capability("creative_copywriting")
    assert decision.model_id == "magpie-deepseek-v4.1-flash"
    assert decision.capability_routing is False


def test_capability_routing_can_recommend_creative_and_prefill() -> None:
    creative = route_model_capability("creative_copywriting", capability_routing=True)
    assert creative.model_id == "mimo-v2.6-flash"
    visual = route_model_capability("visual_design", has_vision=True, capability_routing=True)
    assert visual.workload == "vision"


def test_groupwise_grader_ranks_the_consistently_strong_candidate() -> None:
    report = evaluate_groupwise(
        [
            CandidateScore("a", {"copy": 82, "visual": 78, "compliance": 90}),
            CandidateScore("b", {"copy": 92, "visual": 40, "compliance": 60}),
            CandidateScore("c", {"copy": 70, "visual": 72, "compliance": 75}),
        ]
    )
    assert report.leader == "a"
    assert report.group_mean > 0
    assert report.ranking[0]["candidate_id"] == "a"


def test_ptgs_temperature_is_clamped_and_monotonic() -> None:
    assert ptgs_temperature(0.0, 0.0) == 0.65
    assert ptgs_temperature(1.0, 1.0) == 1.05
    assert ptgs_temperature(0.8, 0.6) == pytest.approx(0.815)


def test_apmd_resets_on_age_count_and_low_entropy() -> None:
    anchor = PolicyAnchor(datetime(2026, 1, 1, tzinfo=UTC), 10)
    now = datetime(2026, 2, 1, tzinfo=UTC)
    assert policy_reset_decision(anchor, now=now).reason == "age_reset"
    assert (
        policy_reset_decision(anchor, now=now - timedelta(days=12), note_count=25).reason
        == "note_count_reset"
    )
    low = policy_reset_decision(
        anchor,
        now=datetime(2026, 1, 20, tzinfo=UTC),
        note_count=10,
        category_counts=[100, 1],
    )
    assert low.reason == "low_track_entropy"
    assert shannon_entropy([1, 1]) > shannon_entropy([100, 1])


def test_cover_critique_checks_safe_area_contrast_and_thumbnail() -> None:
    good = evaluate_cover_layout(
        "通勤穿搭",
        text_box={"x": 150, "y": 180, "w": 700, "h": 120},
        contrast_ratio=5.0,
    )
    assert good.score == 100
    assert good.issues == ()
    bad = evaluate_cover_layout(
        "很长的封面文案" * 10,
        text_box={"x": 0, "y": 0, "w": 1000, "h": 40},
        contrast_ratio=3.0,
    )
    assert "text_outside_safe_area" in bad.issues
    assert "contrast_below_4_5" in bad.issues
    assert "text_too_small_in_thumbnail" in bad.issues


def test_swa_sandwich_keeps_stable_prefix_and_bounds_anchor() -> None:
    prompt = CompiledPrompt(
        layers={
            PromptLayer.L0_SYSTEM: "system",
            PromptLayer.L1_TOOL_SCHEMA: "tools",
            PromptLayer.L2_ACCOUNT: "account",
            PromptLayer.L5_OBSERVATION: "observation",
        }
    )
    result = build_swa_sandwich(prompt, "anchor " * 100, max_tokens=10)
    assert result["prefix"] == "system\n\ntools\n\naccount"
    assert result["anchor_token_cost"] <= 10
    assert "<swa_active_constraints>" in result["prompt"]
    assert prompt.render() == "system\n\ntools\n\naccount\n\nobservation"
