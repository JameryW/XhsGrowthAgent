"""Verification trigger policy — the arithmetic never overrides a risk floor."""

from __future__ import annotations

import pytest

from backend.services.verification_policy import (
    VERIFICATION_EVENT_KIND,
    ActionRisk,
    VerificationInput,
    VerificationTier,
    decide,
)


def _inp(**kwargs) -> VerificationInput:
    base = {"action": "publish", "risk": ActionRisk.MEDIUM}
    base.update(kwargs)
    return VerificationInput(**base)


class TestDryRun:
    def test_dry_run_is_never_verified(self):
        decision = decide(_inp(risk=ActionRisk.CRITICAL, dry_run=True))
        assert decision.required is False
        assert decision.tier is VerificationTier.NONE
        assert decision.reason == "dry_run"


class TestRiskFloor:
    def test_critical_always_human_even_at_zero_error_prob(self):
        decision = decide(_inp(risk=ActionRisk.CRITICAL, expected_error_prob=0.0))
        assert decision.required is True
        assert decision.tier is VerificationTier.HUMAN
        assert decision.reason == "critical_risk_floor"

    def test_high_keeps_deterministic_floor_when_arithmetic_says_no(self):
        decision = decide(
            _inp(risk=ActionRisk.HIGH, expected_error_prob=0.0, verify_cost=10.0, loss=1.0)
        )
        assert decision.required is True
        assert decision.tier is VerificationTier.DETERMINISTIC
        assert decision.reason == "risk_floor_kept"

    def test_medium_with_negative_benefit_is_skipped(self):
        decision = decide(_inp(risk=ActionRisk.MEDIUM, expected_error_prob=0.0))
        assert decision.required is False
        assert decision.reason == "below_threshold"


class TestExpectedValue:
    def test_positive_benefit_verifies(self):
        decision = decide(
            _inp(expected_error_prob=0.5, detection_prob=0.9, loss=1.0, verify_cost=0.2)
        )
        assert decision.required is True
        assert decision.reason == "expected_loss_exceeds_cost"
        assert decision.expected_benefit > 0

    def test_medium_gets_llm_tier(self):
        decision = decide(_inp(risk=ActionRisk.MEDIUM, expected_error_prob=0.5))
        assert decision.tier is VerificationTier.LLM

    def test_low_gets_deterministic_tier(self):
        decision = decide(_inp(risk=ActionRisk.LOW, expected_error_prob=0.5))
        assert decision.tier is VerificationTier.DETERMINISTIC

    def test_high_floor_never_lowers_llm_tier(self):
        # Positive benefit on HIGH: LLM (2) is above the deterministic floor (1)
        # and must survive the "raise only" rule.
        decision = decide(_inp(risk=ActionRisk.HIGH, expected_error_prob=0.5))
        assert decision.tier is VerificationTier.LLM

    def test_benefit_is_computed(self):
        decision = decide(
            _inp(expected_error_prob=0.5, detection_prob=0.8, loss=2.0, verify_cost=0.5)
        )
        assert decision.expected_benefit == pytest.approx(0.5 * 0.8 * 2.0 - 0.5)


class TestBudget:
    def test_shortfall_degrades_to_deterministic_not_skip(self):
        decision = decide(
            _inp(
                risk=ActionRisk.HIGH,
                expected_error_prob=0.9,
                budget_remaining=0.01,
                verify_cost=0.2,
            )
        )
        assert decision.required is True
        assert decision.tier is VerificationTier.DETERMINISTIC
        assert decision.reason == "budget_exhausted"

    def test_low_risk_shortfall_skips(self):
        decision = decide(
            _inp(
                risk=ActionRisk.LOW,
                expected_error_prob=0.9,
                budget_remaining=0.01,
                verify_cost=0.2,
            )
        )
        assert decision.required is False
        assert decision.reason == "budget_exhausted"

    def test_sufficient_budget_keeps_normal_path(self):
        decision = decide(_inp(expected_error_prob=0.9, budget_remaining=100.0))
        assert decision.reason == "expected_loss_exceeds_cost"


class TestValidation:
    def test_probability_out_of_range_raises(self):
        with pytest.raises(ValueError, match="expected_error_prob"):
            _inp(expected_error_prob=1.5)

    def test_negative_cost_raises(self):
        with pytest.raises(ValueError, match="verify_cost"):
            _inp(verify_cost=-1.0)


class TestEvent:
    def test_event_shape(self):
        decision = decide(_inp(risk=ActionRisk.CRITICAL))
        entry = decision.to_event(action="publish", account_id="a1", thread_id="t1")
        assert entry["kind"] == VERIFICATION_EVENT_KIND
        assert entry["action"] == "publish"
        assert entry["tier"] == "human"
        assert entry["required"] is True
        assert entry["account_id"] == "a1"
        assert entry["timestamp"]

    def test_registered_event_kind(self):
        from backend.db.workflow_events import EVENT_KINDS

        assert VERIFICATION_EVENT_KIND in EVENT_KINDS
