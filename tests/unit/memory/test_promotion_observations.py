"""Observe-only promotion pass over Creative Memory styles (Slice B, 票 5s).

The pass is the first real candidate source on the protocol. What is pinned:
the row→candidate mapping is lossless and traceable, only styles are in scope,
decisions are recorded (append-only, one row per verdict) while the target
namespace stays untouched, an unavailable ledger reports itself instead of
pretending, a partial ledger read refuses to decide, and a second observation of
a newer version of the same key supersedes instead of forking the ledger.
"""

from __future__ import annotations

import asyncio

import pytest
from langgraph.store.memory import InMemoryStore

from backend.creator_agent.models import ContentObservation, ContentObservationKind
from backend.memory.promotion import (
    DedupeVerdict,
    PromotionDisposition,
    PromotionReason,
)
from backend.memory.promotion_ledger import (
    LedgerPage,
    PromotionLedger,
    current_entries,
    promotion_id_for,
)
from backend.memory.promotion_observations import (
    TARGET_NAMESPACE,
    candidate_from_observation,
    observe_style_promotions,
    source_check_from_observation,
)

_ACCOUNT = "acc-1"
_VERSION = "2026-10-01T00:00:00Z"
_NEWER = "2026-10-02T00:00:00Z"


def _style(
    source_id: str = "style_1",
    *,
    rate: float = 0.4,
    samples: int = 10,
    observed_at: str = _VERSION,
    description: str = "治愈/温暖治愈",
) -> ContentObservation:
    return ContentObservation(
        kind=ContentObservationKind.STYLE,
        source_id=source_id,
        description=description,
        measured_rate=rate,
        sample_count=samples,
        observed_at=observed_at,
    )


class TestCandidateMapping:
    def test_a_style_row_maps_losslessly(self) -> None:
        candidate = candidate_from_observation(_style())
        assert candidate.namespace == TARGET_NAMESPACE
        assert candidate.key == "style:style_1"
        assert candidate.body == "风格「治愈/温暖治愈」历史互动率 0.400（样本 10）"
        assert str(candidate.trust_class.value) == "internal_fact"
        assert candidate.source_ref == "creative-memory://style/style_1"
        assert candidate.source_version == _VERSION
        assert candidate.evidence_ids == ("ev_style_style_1",)
        assert candidate.sample_count == 10
        assert candidate.measured_rate == 0.4
        assert candidate.ttl_seconds is None  # 票 5z: default null / supersede-only
        assert candidate.proposed_by == "creative-memory-observation"

    @pytest.mark.parametrize("kind", [ContentObservationKind.PLAY, ContentObservationKind.MATERIAL])
    def test_only_styles_are_in_scope(self, kind: ContentObservationKind) -> None:
        observation = ContentObservation(
            kind=kind,
            source_id="x",
            description="d",
            measured_rate=0.5,
            sample_count=3,
            observed_at=_VERSION,
        )
        with pytest.raises(ValueError, match="styles only"):
            candidate_from_observation(observation)

    def test_an_unversioned_row_raises_instead_of_being_skipped(self) -> None:
        with pytest.raises(ValueError, match="no timestamp"):
            candidate_from_observation(_style(observed_at=""))

    def test_the_source_check_states_what_was_read(self) -> None:
        observation = _style()
        check = source_check_from_observation(observation)
        assert check.present is True
        assert check.version == _VERSION
        assert check.evidence_found == ("ev_style_style_1",)
        assert check.evidence_missing == ()
        assert check.ttl_expired is False  # null TTL ⇒ never expired


class TestObservationPass:
    def test_a_measured_style_is_promoted_and_recorded(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)

        result = asyncio.run(observe_style_promotions(ledger, _ACCOUNT, [_style()]))

        assert result.ledger_available is True
        assert result.recorded == 1
        assert len(result.promotions) == 1
        decision = result.promotions[0].decision
        assert decision.disposition is PromotionDisposition.PROMOTE
        assert decision.reason is PromotionReason.VERIFIED_INTERNAL_FACT

        page = asyncio.run(ledger.records(_ACCOUNT))
        assert len(page.records) == 1
        assert page.records[0].disposition == "promote"

        # Observe-only: nothing was written to the target namespace.
        target = asyncio.run(store.asearch(("accounts", _ACCOUNT, TARGET_NAMESPACE)))
        assert list(target) == []

    def test_a_second_identical_pass_records_a_duplicate_verdict(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)

        first = asyncio.run(observe_style_promotions(ledger, _ACCOUNT, [_style()]))
        second = asyncio.run(observe_style_promotions(ledger, _ACCOUNT, [_style()]))

        assert first.recorded == 1
        assert second.recorded == 1
        assert second.promotions[0].decision.reason is PromotionReason.DUPLICATE
        assert second.promotions[0].decision.dedupe is DedupeVerdict.DUPLICATE

        page = asyncio.run(ledger.records(_ACCOUNT))
        # Two decisions, one current promote record: history is append-only and
        # the duplicate did not replace the promotion.
        assert len(page.records) == 2
        assert len(current_entries(list(page.records))) == 1

    def test_a_thin_sample_is_refused_but_still_recorded(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)

        result = asyncio.run(observe_style_promotions(ledger, _ACCOUNT, [_style(samples=2)]))

        assert result.promotions[0].decision.disposition is PromotionDisposition.REFUSE
        assert result.promotions[0].decision.reason is PromotionReason.INSUFFICIENT_SAMPLES
        assert result.recorded == 1

    def test_a_missing_ledger_reports_itself(self) -> None:
        ledger = PromotionLedger(None)

        result = asyncio.run(observe_style_promotions(ledger, _ACCOUNT, [_style()]))

        assert result.ledger_available is False
        assert result.recorded == 0
        # Decisions were still reached; only the record is missing.
        assert result.promotions[0].decision.disposition is PromotionDisposition.PROMOTE

    def test_non_style_observations_are_ignored(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        play = ContentObservation(
            kind=ContentObservationKind.PLAY,
            source_id="play_1",
            description="对比测评",
            measured_rate=0.5,
            sample_count=6,
            observed_at=_VERSION,
        )

        result = asyncio.run(observe_style_promotions(ledger, _ACCOUNT, [play, _style()]))

        assert len(result.promotions) == 1
        assert result.promotions[0].candidate.key == "style:style_1"

    def test_a_newer_version_in_the_same_pass_supersedes_not_forks(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)

        result = asyncio.run(
            observe_style_promotions(ledger, _ACCOUNT, [_style(), _style(observed_at=_NEWER)])
        )

        first, second = result.promotions
        assert first.decision.reason is PromotionReason.VERIFIED_INTERNAL_FACT
        assert second.decision.reason is PromotionReason.SUPERSEDES_OLDER
        assert second.decision.supersedes == (
            promotion_id_for(first.decision, source_version=_VERSION),
        )

        page = asyncio.run(ledger.records(_ACCOUNT))
        current = current_entries(list(page.records))
        assert len(current) == 1
        assert current[0].source_version == _NEWER

    def test_a_partial_ledger_read_refuses_to_decide(self) -> None:
        class _PartialLedger:
            async def records(self, *_args: object, **_kwargs: object) -> LedgerPage:
                return LedgerPage(records=(), available=True, complete=False)

            async def append(self, *_args: object, **_kwargs: object) -> object:
                raise AssertionError("a partial read must not reach an append")

        # Outcome-valued: reaching the append must be a *string* here, so the
        # assertion below reports it instead of an unrelated AssertionError.
        outcome: object = "decided"
        try:
            asyncio.run(
                observe_style_promotions(_PartialLedger(), _ACCOUNT, [_style()])  # type: ignore[arg-type]
            )
        except Exception as exc:
            outcome = exc
        assert isinstance(outcome, RuntimeError), outcome

    def test_the_same_inputs_reach_the_same_decisions(self) -> None:
        first = asyncio.run(
            observe_style_promotions(PromotionLedger(InMemoryStore()), _ACCOUNT, [_style()])
        )
        second = asyncio.run(
            observe_style_promotions(PromotionLedger(InMemoryStore()), _ACCOUNT, [_style()])
        )
        assert first.promotions[0].decision == second.promotions[0].decision
