"""Tests for phase-4 temporal and execution contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.services.temporal_contracts import (
    InhibitoryHawkesParams,
    RevisionConflictError,
    apply_expected_revision,
    build_analytics_snapshot,
    build_narrative_brief,
    compile_jit_subgraph,
    counterfactual_slots,
    effective_intensity,
    encode_time_features,
    inhibit_factor,
    narrative_anchors,
    salvage_timed_out_payload,
    validate_commercial_brief_contract,
)


def test_expected_revision_cas_accepts_current_revision() -> None:
    current = apply_expected_revision(None, 0, {"title": "a"})
    assert current.revision == 1
    nxt = apply_expected_revision(current, 1, {"title": "b"})
    assert nxt.revision == 2
    assert nxt.value == {"title": "b"}


def test_expected_revision_cas_rejects_stale_writer() -> None:
    current = apply_expected_revision(None, 0, {"title": "a"})
    with pytest.raises(RevisionConflictError) as exc:
        apply_expected_revision(current, 0, {"title": "b"})
    assert exc.value.expected == 0
    assert exc.value.actual == 1


def test_analytics_snapshot_computes_non_negative_delta() -> None:
    snap = build_analytics_snapshot(
        "draft-1", 2, reads=500, likes=20, collects=10, comments=3, previous_reads=300
    )
    assert snap.seq_no == 2
    assert snap.delta_views == 200
    assert snap.reads == 500


def test_timepop_encodes_periodic_features_and_48_slots() -> None:
    features = encode_time_features(datetime(2026, 11, 16, 12, 0, tzinfo=UTC))
    assert -1.0 <= features.sin_day <= 1.0
    assert -1.0 <= features.cos_week <= 1.0
    assert features.hour_slot == 24
    slots = counterfactual_slots(date(2026, 11, 16))
    assert len(slots) == 48
    assert slots[0]["label"] == "00:00"
    assert slots[-1]["label"] == "23:30"


def test_inhibitory_hawkes_only_suppresses_near_duplicates() -> None:
    params = InhibitoryHawkesParams(tau_refractory=2.0)
    suppressed = inhibit_factor(1.0, 0.9, params)
    assert 0.0 < suppressed < 0.5
    assert inhibit_factor(1.0, 0.1, params) == 1.0
    assert inhibit_factor(10.0, 0.9, params) == 1.0
    base = 1.0
    intensity = effective_intensity(base, [(1.0, 0.9), (8.0, 0.9)], params)
    assert intensity > base


def test_jit_subgraph_for_free_skips_strategy_nodes() -> None:
    plan = compile_jit_subgraph("free", {"topic": "通勤穿搭"})
    assert "trend_scout" in plan.skip_nodes
    assert "content_strategist" in plan.skip_nodes
    assert plan.nodes[0] == "orchestrator"


def test_jit_subgraph_for_brief_adds_contract_nodes() -> None:
    plan = compile_jit_subgraph("brief", {})
    assert "brief_analyzer" in plan.nodes
    assert "shooting_planner" in plan.nodes
    assert set(plan.nodes) <= set(plan.graph_nodes)
    assert "brief_analyzer" in plan.graph_nodes


def test_commercial_brief_contract_reports_missing_fields() -> None:
    report = validate_commercial_brief_contract(
        {"brand_name": "Brand", "selling_points": ["point"]}
    )
    assert report.ready is False
    assert report.missing_fields == (
        "product_name",
        "content_direction",
        "target_audience",
    )


def test_commercial_brief_contract_accepts_complete_brief() -> None:
    report = validate_commercial_brief_contract(
        {
            "brand_name": "Brand",
            "product_name": "Product",
            "selling_points": ["point"],
            "content_direction": "通勤",
            "target_audience": "上班族",
        }
    )
    assert report.ready is True
    assert report.missing_fields == ()


def test_narrative_priors_are_three_orthogonal_anchors() -> None:
    anchors = narrative_anchors()
    assert [anchor.key for anchor in anchors] == [
        "search_direct",
        "pain_contrast",
        "minimal_visual",
    ]
    brief = build_narrative_brief(anchors[1], "秋日通勤")
    assert brief["topic"] == "秋日通勤"
    assert brief["anchor"] == "pain_contrast"


def test_ripple_salvage_uses_partial_prediction_and_flags_missing_fields() -> None:
    partial = salvage_timed_out_payload({"partial_result": {"estimated_reach": 1200}})
    assert partial.usable is False
    assert partial.stage == "timed_out"
    assert "viral_probability" in partial.missing_fields
    assert partial.fallback["status"] == "degraded"


def test_ripple_salvage_accepts_complete_prediction() -> None:
    result = salvage_timed_out_payload(
        {"estimated_reach": 1200, "viral_probability": 0.72, "verdict": "stable"}
    )
    assert result.usable is True
    assert result.stage == "partial"
    assert result.missing_fields == ()
