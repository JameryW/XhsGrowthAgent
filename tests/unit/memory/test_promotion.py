"""Memory promotion protocol — Slice A (票 5r).

What is pinned here is the **contract**, not a wired pipeline: the decision is
pure, deterministic, and the reason vocabulary is closed. Every reason must be
reachable from a realistic input (a member nobody can produce is dead
vocabulary), every refusal must be explainable, and a malformed candidate must
raise rather than be silently "refused".
"""

from __future__ import annotations

import pytest

from backend.context.models import TrustClass
from backend.memory.promotion import (
    DedupeVerdict,
    ExistingEntry,
    PromotionCandidate,
    PromotionDisposition,
    PromotionPolicy,
    PromotionReason,
    SourceCheck,
    candidate_id_for,
    decide_promotion,
)

_VERSION = "2026-10-01T00:00:00Z"
_NEWER = "2026-10-02T00:00:00Z"
_OLDER = "2026-09-30T00:00:00Z"


def _candidate(**overrides: object) -> PromotionCandidate:
    base: dict[str, object] = {
        "namespace": "strategy_notes",
        "key": "k1",
        "body": "历史互动率 0.4（样本 10）",
        "trust_class": TrustClass.INTERNAL_FACT,
        "source_ref": "creative-memory://style/s1",
        "source_version": _VERSION,
        "observed_at": _VERSION,
        "evidence_ids": ("ev1",),
        "sample_count": 10,
        "measured_rate": 0.4,
    }
    base.update(overrides)
    return PromotionCandidate(**base)  # type: ignore[arg-type]


def _source(**overrides: object) -> SourceCheck:
    base: dict[str, object] = {
        "present": True,
        "version": _VERSION,
        "evidence_found": ("ev1",),
    }
    base.update(overrides)
    return SourceCheck(**base)  # type: ignore[arg-type]


def _decision(**overrides: object):
    """Run the default (promotable) candidate with one thing changed."""
    source_kwargs = overrides.pop("source", {})
    existing = overrides.pop("existing", ())
    policy = overrides.pop("policy", None)
    return decide_promotion(
        _candidate(**overrides),
        source=_source(**source_kwargs),  # type: ignore[arg-type]
        existing=existing,  # type: ignore[arg-type]
        policy=policy,  # type: ignore[arg-type]
    )


class TestEveryReasonIsReachable:
    """One realistic input per closed-vocabulary member (the module's ratchet)."""

    def test_the_vocabulary_is_the_published_set(self) -> None:
        assert {reason.value for reason in PromotionReason} == {
            "source_missing",
            "source_unversioned",
            "source_degraded",
            "ttl_expired",
            "evidence_missing",
            "insufficient_samples",
            "duplicate",
            "policy_blocked",
            "needs_human_review",
            "source_stale",
            "verified_internal_fact",
            "supersedes_older",
        }

    @pytest.mark.parametrize(
        ("overrides", "reason", "disposition", "dedupe", "verified"),
        [
            (
                {"source": {"present": False, "version": ""}},
                PromotionReason.SOURCE_MISSING,
                PromotionDisposition.REFUSE,
                DedupeVerdict.NOT_EVALUATED,
                False,
            ),
            (
                {"source_version": ""},
                PromotionReason.SOURCE_UNVERSIONED,
                PromotionDisposition.REFUSE,
                DedupeVerdict.NOT_EVALUATED,
                False,
            ),
            (
                {"source": {"degraded": True, "present": False, "version": ""}},
                PromotionReason.SOURCE_DEGRADED,
                PromotionDisposition.REFUSE,
                DedupeVerdict.NOT_EVALUATED,
                False,
            ),
            (
                {"source": {"ttl_expired": True}},
                PromotionReason.TTL_EXPIRED,
                PromotionDisposition.REFUSE,
                DedupeVerdict.NOT_EVALUATED,
                False,
            ),
            (
                {"source": {"evidence_missing": ("ev9",)}},
                PromotionReason.EVIDENCE_MISSING,
                PromotionDisposition.REFUSE,
                DedupeVerdict.NOT_EVALUATED,
                False,
            ),
            (
                {"sample_count": 1},
                PromotionReason.INSUFFICIENT_SAMPLES,
                PromotionDisposition.REFUSE,
                DedupeVerdict.NEW,
                True,
            ),
            (
                {
                    "existing": (
                        ExistingEntry(
                            key="k1",
                            source_ref="creative-memory://style/s1",
                            source_version=_VERSION,
                            promotion_id="promo_1",
                        ),
                    )
                },
                PromotionReason.DUPLICATE,
                PromotionDisposition.REFUSE,
                DedupeVerdict.DUPLICATE,
                True,
            ),
            (
                {"policy": PromotionPolicy(allowed_namespaces=("performance_insights",))},
                PromotionReason.POLICY_BLOCKED,
                PromotionDisposition.REFUSE,
                DedupeVerdict.NOT_EVALUATED,
                False,
            ),
            (
                {"trust_class": TrustClass.MEMORY},
                PromotionReason.NEEDS_HUMAN_REVIEW,
                PromotionDisposition.REVIEW,
                DedupeVerdict.NEW,
                True,
            ),
            (
                {"source": {"version": _NEWER}},
                PromotionReason.SOURCE_STALE,
                PromotionDisposition.REVIEW,
                DedupeVerdict.NOT_EVALUATED,
                False,
            ),
            (
                {},
                PromotionReason.VERIFIED_INTERNAL_FACT,
                PromotionDisposition.PROMOTE,
                DedupeVerdict.NEW,
                True,
            ),
            (
                {
                    "source_version": _NEWER,
                    "source": {"version": _NEWER},
                    "existing": (
                        ExistingEntry(
                            key="k1",
                            source_ref="creative-memory://style/s1",
                            source_version=_VERSION,
                            promotion_id="promo_1",
                        ),
                    ),
                },
                PromotionReason.SUPERSEDES_OLDER,
                PromotionDisposition.PROMOTE,
                DedupeVerdict.SUPERSEDES,
                True,
            ),
        ],
    )
    def test_each_reason(
        self,
        overrides: dict[str, object],
        reason: PromotionReason,
        disposition: PromotionDisposition,
        dedupe: DedupeVerdict,
        verified: bool,
    ) -> None:
        decision = _decision(**overrides)
        assert decision.reason is reason, decision
        assert decision.disposition is disposition, decision
        assert decision.dedupe is dedupe, decision
        assert decision.verified is verified, decision


class TestDeterminism:
    def test_the_same_inputs_produce_the_same_decision(self) -> None:
        first = _decision()
        second = _decision()
        assert first == second
        assert first.to_dict() == second.to_dict()

    def test_the_id_is_derived_not_temporal(self) -> None:
        at_one = _decision(observed_at=_VERSION)
        at_two = _decision(observed_at=_NEWER)
        assert at_one.candidate_id == at_two.candidate_id

    def test_the_id_separates_namespaces_and_sources(self) -> None:
        a = _decision()
        b = _decision(source_ref="creative-memory://style/s2")
        c = _decision(namespace="performance_insights")
        assert len({a.candidate_id, b.candidate_id, c.candidate_id}) == 3

    def test_the_id_helper_matches_the_candidate_property(self) -> None:
        candidate = _candidate()
        assert candidate.id == candidate_id_for(candidate.namespace, candidate.source_ref)

    def test_supersedes_is_sorted_by_promotion_id(self) -> None:
        existing = tuple(
            ExistingEntry(
                key="k1",
                source_ref="creative-memory://style/s1",
                source_version=version,
                promotion_id=promotion_id,
            )
            for version, promotion_id in ((_VERSION, "promo_b"), (_OLDER, "promo_a"))
        )
        decision = _decision(source_version=_NEWER, source={"version": _NEWER}, existing=existing)
        assert decision.supersedes == ("promo_a", "promo_b")


class TestDedupeBranches:
    def test_a_competing_source_on_the_same_key_needs_a_person(self) -> None:
        existing = (
            ExistingEntry(
                key="k1",
                source_ref="creative-memory://play/p1",
                source_version=_VERSION,
                promotion_id="promo_other",
            ),
        )
        decision = _decision(existing=existing)
        assert decision.disposition is PromotionDisposition.REVIEW
        assert decision.reason is PromotionReason.NEEDS_HUMAN_REVIEW
        assert decision.dedupe is DedupeVerdict.NEEDS_REVIEW

    def test_the_same_source_under_another_key_needs_a_person(self) -> None:
        existing = (
            ExistingEntry(
                key="k2",
                source_ref="creative-memory://style/s1",
                source_version=_VERSION,
                promotion_id="promo_elsewhere",
            ),
        )
        decision = _decision(existing=existing)
        assert decision.disposition is PromotionDisposition.REVIEW
        assert decision.dedupe is DedupeVerdict.NEEDS_REVIEW

    def test_an_older_candidate_than_the_stored_record_is_a_stale_review(self) -> None:
        existing = (
            ExistingEntry(
                key="k1",
                source_ref="creative-memory://style/s1",
                source_version=_NEWER,
                promotion_id="promo_newer",
            ),
        )
        # The candidate claims the same source at an older version than the
        # stored record; the source currently says the same old version, so the
        # "current" check passes — the stale fact is the stored record's version.
        decision = _decision(existing=existing)
        assert decision.disposition is PromotionDisposition.REVIEW
        assert decision.reason is PromotionReason.SOURCE_STALE
        assert decision.dedupe is DedupeVerdict.DUPLICATE

    def test_a_review_keeps_the_dedupe_verdict_for_the_reviewer(self) -> None:
        existing = (
            ExistingEntry(
                key="k1",
                source_ref="creative-memory://style/s1",
                source_version=_VERSION,
                promotion_id="promo_1",
            ),
        )
        decision = _decision(trust_class=TrustClass.MEMORY, existing=existing)
        assert decision.disposition is PromotionDisposition.REVIEW
        assert decision.dedupe is DedupeVerdict.DUPLICATE


class TestPrecedence:
    def test_samples_are_checked_before_duplicate(self) -> None:
        existing = (
            ExistingEntry(
                key="k1",
                source_ref="creative-memory://style/s1",
                source_version=_VERSION,
                promotion_id="promo_1",
            ),
        )
        decision = _decision(sample_count=1, existing=existing)
        assert decision.reason is PromotionReason.INSUFFICIENT_SAMPLES
        assert decision.dedupe is DedupeVerdict.DUPLICATE

    def test_a_degraded_reader_never_claims_verified(self) -> None:
        decision = _decision(source={"degraded": True, "present": False, "version": ""})
        assert decision.verified is False

    def test_a_missing_source_is_not_a_dedupe_question(self) -> None:
        decision = _decision(source={"present": False, "version": ""})
        assert decision.dedupe is DedupeVerdict.NOT_EVALUATED


class TestPolicy:
    def test_the_sample_floor_is_the_policy_not_a_constant(self) -> None:
        lenient = decide_promotion(
            _candidate(sample_count=1),
            source=_source(),
            policy=PromotionPolicy(min_samples=1),
        )
        assert lenient.disposition is PromotionDisposition.PROMOTE

    def test_a_measured_flag_is_required_even_with_samples(self) -> None:
        decision = _decision(measured_rate=None)
        assert decision.reason is PromotionReason.INSUFFICIENT_SAMPLES

    def test_a_policy_can_allow_more_classes_but_defaults_stay_strict(self) -> None:
        candidate = _candidate(trust_class=TrustClass.MODEL_GENERATED)
        default = decide_promotion(candidate, source=_source())
        allowed = decide_promotion(
            candidate,
            source=_source(),
            policy=PromotionPolicy(
                machine_promotable_classes=(
                    TrustClass.INTERNAL_FACT,
                    TrustClass.MODEL_GENERATED,
                )
            ),
        )
        assert default.disposition is PromotionDisposition.REVIEW
        assert allowed.disposition is PromotionDisposition.PROMOTE

    def test_the_policy_version_travels_with_the_decision(self) -> None:
        decision = decide_promotion(
            _candidate(), source=_source(), policy=PromotionPolicy(policy_version="v9")
        )
        assert decision.policy_version == "v9"


class TestContractViolationsRaise:
    """A malformed candidate is a bug; closed reasons are for real decisions."""

    @pytest.mark.parametrize(
        "overrides",
        [
            {"namespace": " "},
            {"key": ""},
            {"body": ""},
            {"source_ref": ""},
            {"observed_at": ""},
            {"sample_count": -1},
            {"measured_rate": 1.5},
            {"ttl_seconds": 0},
            {"evidence_ids": ("ev1", "ev1")},
        ],
    )
    def test_a_bad_candidate_raises(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            _candidate(**overrides)

    def test_a_present_source_must_carry_a_version(self) -> None:
        with pytest.raises(ValueError):
            SourceCheck(present=True, version="")

    def test_a_policy_with_a_zero_floor_raises(self) -> None:
        with pytest.raises(ValueError):
            PromotionPolicy(min_samples=0)

    def test_a_policy_without_a_version_raises(self) -> None:
        with pytest.raises(ValueError):
            PromotionPolicy(policy_version=" ")

    def test_a_non_trust_class_member_raises(self) -> None:
        with pytest.raises(ValueError):
            PromotionPolicy(machine_promotable_classes=("internal_fact",))  # type: ignore[arg-type]
