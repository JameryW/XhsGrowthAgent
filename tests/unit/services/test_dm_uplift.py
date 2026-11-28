"""Unit tests for the DM quota uplift allocator (ledger scheme #44)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.services.dm_uplift import (
    DM_UPLIFT_ENV,
    DmIntake,
    assess_batch,
    assess_dm,
    assess_dm_if_enabled,
    base_conversion,
    detect_hostility,
    dm_uplift_enabled,
    estimate_candidate,
    intake_from_context,
    intent_score,
)
from backend.services.interaction_contracts import DmStratum


class TestSwitch:
    def test_switched_off_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(DM_UPLIFT_ENV, raising=False)
        assert dm_uplift_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(DM_UPLIFT_ENV, value)
        assert dm_uplift_enabled() is True

    @pytest.mark.parametrize("value", ["", "0", "off", "false"])
    def test_other_values_stay_off(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(DM_UPLIFT_ENV, value)
        assert dm_uplift_enabled() is False


class TestHostility:
    def test_empty_text_is_calm(self) -> None:
        assert detect_hostility("") == ""

    def test_negotiation_is_not_hostility(self) -> None:
        assert detect_hostility("太贵了能便宜点吗") == ""

    def test_explicit_accusation(self) -> None:
        assert detect_hostility("你们是骗子吧，我要举报") in {"骗子", "举报"}

    def test_narrow_marker_wins(self) -> None:
        assert detect_hostility("差评") == "差评"


class TestIntent:
    def test_empty_intake_has_no_intent(self) -> None:
        assert intent_score(DmIntake()) == 0.0

    def test_price_question_and_slots_raise_intent(self) -> None:
        intake = DmIntake(
            inbound_message="多少钱？押金怎么定",
            qualified_slots=5,
            interest_count=3,
            has_known_price=True,
        )
        assert intent_score(intake) == 1.0

    def test_medium_markers_count_less_than_strong(self) -> None:
        strong = intent_score(DmIntake(inbound_message="多少钱"))
        medium = intent_score(DmIntake(inbound_message="想租车"))
        assert strong > medium > 0.0


class TestBaseConversion:
    def test_fan_stage_priors_are_ordered(self) -> None:
        new = base_conversion(DmIntake(fan_stage="new"))
        returning = base_conversion(DmIntake(fan_stage="returning"))
        vip = base_conversion(DmIntake(fan_stage="vip"))
        assert new < returning < vip

    def test_slots_and_interests_add_to_the_prior(self) -> None:
        plain = base_conversion(DmIntake(fan_stage="returning"))
        warm = base_conversion(DmIntake(fan_stage="returning", qualified_slots=2, interest_count=2))
        assert warm > plain

    def test_prior_is_capped(self) -> None:
        intake = DmIntake(fan_stage="vip", qualified_slots=5, interest_count=3)
        assert base_conversion(intake) == pytest.approx(0.60)


class TestCandidate:
    def test_hesitant_customer_is_persuadable(self) -> None:
        intake = DmIntake(
            inbound_message="10月2号取车，预算600一天，多少钱?",
            fan_stage="vip",
            qualified_slots=5,
            interest_count=3,
            has_known_price=True,
        )
        candidate = estimate_candidate(intake)
        assert candidate.uplift >= 0.10
        assert assess_dm(intake).stratum is DmStratum.PERSUADABLE

    def test_sure_thing_needs_no_persuasion(self) -> None:
        intake = DmIntake(fan_stage="vip", qualified_slots=5, interest_count=3)
        assessment = assess_dm(intake)
        assert assessment.stratum is DmStratum.SURE_THING
        assert assessment.action == "one_shot_card"
        assert assessment.may_send is True

    def test_chatty_browser_is_a_lost_cause_not_a_harm(self) -> None:
        intake = DmIntake(inbound_message="你好呀", fan_stage="returning")
        candidate = estimate_candidate(intake)
        assessment = assess_dm(intake)
        assert candidate.uplift > 0.0
        assert assessment.stratum is DmStratum.LOST_CAUSE
        assert assessment.action == "public_reply_only"
        assert assessment.quota_cost == 0
        assert assessment.may_send is False

    def test_hostile_customer_is_blocked(self) -> None:
        intake = DmIntake(inbound_message="骗子，我要举报你们", fan_stage="returning")
        assessment = assess_dm(intake)
        assert assessment.stratum is DmStratum.SLEEPING_DOG
        assert assessment.action == "silent_block"
        assert assessment.hostility
        assert assessment.may_send is False


class TestEvidence:
    def test_empty_context_is_thin_evidence(self) -> None:
        assert DmIntake().evidence_sufficient is False

    def test_inbound_text_is_enough(self) -> None:
        assert DmIntake(inbound_message="多少钱").evidence_sufficient is True

    def test_two_slots_are_enough(self) -> None:
        assert DmIntake(qualified_slots=2).evidence_sufficient is True


class TestBatch:
    def test_one_quota_defers_the_second_persuadable(self) -> None:
        eager = DmIntake(
            inbound_message="多少钱？押金怎么定",
            fan_stage="vip",
            qualified_slots=5,
            interest_count=3,
            has_known_price=True,
        )
        results = assess_batch([eager, eager], daily_quota=1)
        assert [item.may_send for item in results] == [True, False]
        assert results[0].action == "full_fsm"
        assert results[1].action == "defer_next_day"
        assert results[1].quota_cost == 0

    def test_results_keep_input_order(self) -> None:
        lost = DmIntake(inbound_message="你好呀")
        eager = DmIntake(inbound_message="多少钱？押金多少", qualified_slots=4, interest_count=2)
        results = assess_batch([lost, eager], daily_quota=1)
        assert results[0].stratum is DmStratum.LOST_CAUSE
        assert results[1].stratum is DmStratum.PERSUADABLE


class TestEnabledWrapper:
    def test_returns_none_when_switched_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(DM_UPLIFT_ENV, raising=False)
        assert assess_dm_if_enabled(inbound_message="多少钱") is None

    def test_assesses_when_switched_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DM_UPLIFT_ENV, "1")
        assessment = assess_dm_if_enabled(inbound_message="多少钱", fan_stage="vip")
        assert assessment is not None
        assert assessment.evidence_sufficient is True


class TestIntakeFromContext:
    def test_fsm_like_object(self) -> None:
        qualification = SimpleNamespace(slots={"date": "10-01", "region": ""})
        intake = intake_from_context(qualification=qualification)
        assert intake.qualified_slots == 1
        assert intake.total_slots == 5

    def test_mapping_with_slots_key(self) -> None:
        intake = intake_from_context(qualification={"slots": {"a": "1", "b": "2"}})
        assert intake.qualified_slots == 2

    def test_wide_mapping_widens_the_denominator(self) -> None:
        intake = intake_from_context(qualification={f"k{index}": "v" for index in range(6)})
        assert intake.total_slots == 6
        assert intake.qualified_slots == 6


class TestReport:
    def test_report_marks_priors_and_signals(self) -> None:
        intake = DmIntake(
            inbound_message="多少钱？押金怎么定",
            fan_stage="vip",
            qualified_slots=5,
            interest_count=3,
            has_known_price=True,
        )
        payload = assess_dm(intake).as_dict()
        assert payload["priors"] == "fixed"
        assert payload["stratum"] == DmStratum.PERSUADABLE.value
        assert payload["may_send"] is True
        assert payload["candidate"]["uplift"] >= 0.10
        assert payload["signals"]["filled_ratio"] == pytest.approx(1.0)
