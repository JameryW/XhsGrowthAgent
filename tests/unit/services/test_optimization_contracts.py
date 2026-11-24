"""Tests for phase-12 optimization contracts."""

from __future__ import annotations

from backend.services.optimization_contracts import (
    BoostInputs,
    CostMatrix,
    CustomerBeliefState,
    ForecastRecord,
    HarnessVariant,
    ScoutNote,
    abstention_threshold,
    co_evolve_forecasts,
    detect_belief_trapping,
    forecast_surprise,
    pareto_frontier,
    plan_multimodal_deep_scout,
    recommend_boost,
    recovery_actions,
    route_with_abstention,
    select_harness_presets,
    update_belief_state,
)


def test_pareto_frontier_removes_dominated_variant() -> None:
    variants = [
        HarnessVariant("a", 0.90, 1.0, 10.0),
        HarnessVariant("b", 0.80, 2.0, 10.0),
        HarnessVariant("c", 0.95, 3.0, 9.0),
    ]
    frontier = pareto_frontier(variants)
    assert [item.variant_id for item in frontier] == ["c", "a"]


def test_select_harness_presets_names_three_frontier_points() -> None:
    presets = select_harness_presets(
        [
            HarnessVariant("light", 0.70, 1.0, 5.0),
            HarnessVariant("balanced", 0.80, 2.0, 6.0),
            HarnessVariant("heavy", 0.90, 3.0, 7.0),
        ]
    )
    assert [item.name for item in presets] == [
        "lightweight",
        "balanced",
        "high-performance",
    ]


def test_select_harness_presets_empty() -> None:
    assert select_harness_presets([]) == ()


def test_update_belief_state_keeps_first_verified_value() -> None:
    update = update_belief_state(
        CustomerBeliefState(verified_slots={"date": "10-01"}),
        {"date": "10-02", "car": "SUV"},
    )
    assert update.conflicts == ("date",)
    assert update.state.verified_slots["date"] == "10-01"
    assert update.state.verified_slots["car"] == "SUV"


def test_update_belief_state_resolves_gaps() -> None:
    update = update_belief_state(
        CustomerBeliefState(
            verified_slots={},
            unresolved_gaps=("date", "budget"),
        ),
        {"date": "10-01"},
    )
    assert update.state.unresolved_gaps == ("budget",)
    assert update.resolved == ("date",)


def test_detect_belief_trapping_by_persistence_and_stagnation() -> None:
    report = detect_belief_trapping(
        [
            ("date", "budget"),
            ("date", "budget"),
            ("date", "budget"),
        ]
    )
    assert report.trapped is True
    assert "gap_persistence" in report.reasons
    assert "progress_stagnation" in report.reasons


def test_detect_belief_trapping_by_recurrence_and_recovery() -> None:
    report = detect_belief_trapping(
        [("date",)],
        recommendations=["SUV"],
        rejected=["SUV"],
    )
    assert report.trapped is True
    assert "belief_recurrence" in report.reasons
    actions = recovery_actions(report, ["方案A", "方案B"])
    assert actions == ("方案A", "方案B", "handoff_to_human")


def test_forecast_surprise_and_coevolution_buckets() -> None:
    assert forecast_surprise(100, 100) == 0.0
    update = co_evolve_forecasts(
        [
            ForecastRecord("reinforce", 100, 110),
            ForecastRecord("blind", 100, 500),
            ForecastRecord("calibrate", 100, 70),
        ]
    )
    assert update.reinforce == ("reinforce",)
    assert update.blind_spots == ("blind",)
    assert update.calibrate == ("calibrate",)


def test_deep_scout_selects_breakout_and_plans_three_hops() -> None:
    plan = plan_multimodal_deep_scout(
        [
            ScoutNote(
                "small",
                "小号神帖",
                followers=60,
                likes=300,
                collects=1800,
                comments=200,
                image_texts=("路线表",),
                visual_entities=("折多山",),
            ),
            ScoutNote(
                "big",
                "大V日常",
                followers=100000,
                likes=500,
                collects=100,
                comments=10,
            ),
        ],
        top_k=1,
    )
    assert plan.selected_notes == ("small",)
    assert len(plan.hops) == 3
    assert plan.hops[1].action == "visualize"
    assert "verify:折多山" in plan.verification_queries


def test_abstention_threshold_and_route() -> None:
    threshold = abstention_threshold(1.0, 50.0)
    assert 0.019 < threshold < 0.020
    auto = route_with_abstention(0.01, costs=CostMatrix(1.0, 50.0))
    abstain = route_with_abstention(0.5, costs=CostMatrix(1.0, 50.0))
    assert auto.action == "auto_pass"
    assert abstain.action == "abstain"


def test_abstention_uses_quote_error_cost() -> None:
    decision = route_with_abstention(
        0.05,
        costs=CostMatrix(abstain_cost=1.0, quote_error_cost=10.0),
        error_kind="quote",
    )
    assert decision.threshold == 1.0 / 11.0
    assert decision.action == "auto_pass"


def test_recommend_boost_for_high_intent_dm() -> None:
    result = recommend_boost(
        BoostInputs(
            note_id="n1",
            ctr=0.10,
            collect_rate=0.03,
            dm_rate=0.05,
            baseline_ctr_p80=0.08,
            baseline_collect_dm_p85=0.07,
            lead_value=1000.0,
            close_rate=0.2,
            margin=0.3,
        )
    )
    assert result.should_boost is True
    assert result.target == "聚光私信开口 oCPC"
    assert result.max_bid_cap == 60.0


def test_recommend_boost_for_high_collect_signal() -> None:
    result = recommend_boost(
        {
            "note_id": "n1",
            "ctr": 0.1,
            "collect_rate": 0.09,
            "dm_rate": 0.01,
            "baseline_ctr_p80": 0.08,
            "baseline_collect_dm_p85": 0.07,
        }
    )
    assert result.should_boost is True
    assert result.target == "薯条赞藏互动量"


def test_recommend_boost_below_window() -> None:
    result = recommend_boost(
        BoostInputs(
            note_id="n1",
            ctr=0.04,
            collect_rate=0.01,
            dm_rate=0.01,
            baseline_ctr_p80=0.08,
            baseline_collect_dm_p85=0.07,
        )
    )
    assert result.should_boost is False
    assert result.target == ""
