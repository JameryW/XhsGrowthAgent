"""Sliding-window UCB/Wilson bandit used by the weekly A/B review."""

from __future__ import annotations

from backend.services.experiment_bandit import rank_arms, ucb_score, wilson_lower_bound


def test_wilson_and_ucb_are_bounded_and_optimistic_for_unseen_arms() -> None:
    assert wilson_lower_bound(0, 0) == 0.0
    assert 0.0 <= wilson_lower_bound(10, 100) <= 0.1
    assert ucb_score(0, 0, 10) > 1.0
    assert ucb_score(10, 100, 100) > 0.1


def test_rank_arms_needs_two_eligible_variants() -> None:
    decision = rank_arms([{"variant_id": "control", "impressions": 100, "conversions": 10}])

    assert decision.status == "insufficient_data"
    assert decision.reason == "need_two_arms_with_min_impressions"
    assert decision.arms[0].eligible is True


def test_ready_decision_names_the_ucb_leader_as_canary() -> None:
    decision = rank_arms(
        [
            {"variant_id": "control", "impressions": 100, "conversions": 5},
            {"variant_id": "hook", "impressions": 100, "conversions": 30},
            {"variant_id": "thin", "impressions": 3, "conversions": 1},
        ]
    )

    assert decision.status == "ready_for_canary"
    assert decision.leader == "hook"
    assert decision.canary_variant == "hook"
    assert decision.canary_fraction == 0.2
    assert decision.confidence > 0
    assert {arm.variant_id for arm in decision.arms if arm.eligible} == {"control", "hook"}
