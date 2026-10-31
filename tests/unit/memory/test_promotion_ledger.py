"""Append-only promotion ledger (Slice B, 票 5s).

The ledger is the protocol's memory of what was decided. What is pinned here:
records are written once and read back losslessly, ids are derived (the same
decision is one row, a policy/version change is a new row), a missing store is
reported rather than faked, a store failure raises, and "current" entries are
*derived* from supersede edges — with a contradiction raised, never guessed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langgraph.store.memory import InMemoryStore

from backend.context.models import TrustClass
from backend.memory.promotion import (
    DEFAULT_PROMOTION_POLICY_VERSION,
    ExistingEntry,
    PromotionCandidate,
    PromotionDecision,
    PromotionDisposition,
    PromotionReason,
    SourceCheck,
    decide_promotion,
)
from backend.memory.promotion_ledger import (
    LedgerAppendOutcome,
    PromotionLedger,
    PromotionRecord,
    current_entries,
    promotion_id_for,
)

_ACCOUNT = "acc-1"
_VERSION = "2026-10-01T00:00:00Z"
_NEWER = "2026-10-02T00:00:00Z"


def _candidate(**overrides: object) -> PromotionCandidate:
    base: dict[str, object] = {
        "namespace": "strategy_notes",
        "key": "style:style_1",
        "body": "治愈/温暖历史互动率 0.4（样本 10）",
        "trust_class": TrustClass.INTERNAL_FACT,
        "source_ref": "creative-memory://style/style_1",
        "source_version": _VERSION,
        "observed_at": _VERSION,
        "evidence_ids": ("ev_style_style_1",),
        "sample_count": 10,
        "measured_rate": 0.4,
    }
    base.update(overrides)
    return PromotionCandidate(**base)  # type: ignore[arg-type]


def _promote(candidate: PromotionCandidate, *, version: str = _VERSION) -> PromotionDecision:
    return decide_promotion(
        candidate,
        source=SourceCheck(present=True, version=version, evidence_found=candidate.evidence_ids),
    )


def test_a_missing_store_is_reported_not_faked() -> None:
    ledger = PromotionLedger(None)
    candidate = _candidate()
    decision = _promote(candidate)

    assert asyncio.run(ledger.append(_ACCOUNT, candidate, decision)) is LedgerAppendOutcome.NO_STORE
    page = asyncio.run(ledger.records(_ACCOUNT))
    assert page.available is False
    assert page.records == ()
    assert page.complete is True


def test_append_then_read_is_lossless() -> None:
    store = InMemoryStore()
    ledger = PromotionLedger(store)
    candidate = _candidate()
    decision = _promote(candidate)

    outcome = asyncio.run(
        ledger.append(_ACCOUNT, candidate, decision, recorded_at="2026-10-21T10:00:00+00:00")
    )
    page = asyncio.run(ledger.records(_ACCOUNT))

    assert outcome is LedgerAppendOutcome.RECORDED
    assert page.available is True
    assert len(page.records) == 1
    record = page.records[0]
    assert record.promotion_id == promotion_id_for(decision, source_version=_VERSION)
    assert record.candidate_id == decision.candidate_id
    assert record.namespace == "strategy_notes"
    assert record.key == "style:style_1"
    assert record.source_ref == "creative-memory://style/style_1"
    assert record.source_version == _VERSION
    assert record.disposition == "promote"
    assert record.reason == "verified_internal_fact"
    assert record.dedupe == "new"
    assert record.verified is True
    assert record.supersedes == ()
    assert record.decided_by == "machine"
    assert record.policy_version == DEFAULT_PROMOTION_POLICY_VERSION
    assert record.recorded_at == "2026-10-21T10:00:00+00:00"


def test_the_same_decision_writes_one_row() -> None:
    """Idempotent by derivation: appending twice leaves one record behind."""
    store = InMemoryStore()
    ledger = PromotionLedger(store)
    candidate = _candidate()
    decision = _promote(candidate)

    async def _twice() -> None:
        await ledger.append(_ACCOUNT, candidate, decision, recorded_at="2026-10-21T10:00:00+00:00")
        await ledger.append(_ACCOUNT, candidate, decision, recorded_at="2026-10-21T11:00:00+00:00")

    asyncio.run(_twice())
    assert len(asyncio.run(ledger.records(_ACCOUNT)).records) == 1


def test_a_new_source_version_is_a_new_row() -> None:
    store = InMemoryStore()
    ledger = PromotionLedger(store)
    old = _candidate()
    new = _candidate(source_version=_NEWER, observed_at=_NEWER)
    new_decision = decide_promotion(
        new,
        source=SourceCheck(present=True, version=_NEWER, evidence_found=new.evidence_ids),
        existing=(
            ExistingEntry(
                key="style:style_1",
                source_ref=new.source_ref,
                source_version=_VERSION,
                promotion_id=promotion_id_for(_promote(old), source_version=_VERSION),
            ),
        ),
    )

    async def _write() -> None:
        await ledger.append(_ACCOUNT, old, _promote(old), recorded_at="2026-10-21T10:00:00+00:00")
        await ledger.append(_ACCOUNT, new, new_decision, recorded_at="2026-10-21T11:00:00+00:00")

    asyncio.run(_write())
    page = asyncio.run(ledger.records(_ACCOUNT))
    assert len(page.records) == 2
    assert new_decision.reason is PromotionReason.SUPERSEDES_OLDER


def test_two_versions_of_the_same_verdict_are_two_rows() -> None:
    """The source version is part of the id: an append-only ledger may not let a
    newer observation overwrite the record of the version it replaced."""
    store = InMemoryStore()
    ledger = PromotionLedger(store)
    first = _candidate()
    second = _candidate(source_version=_NEWER, observed_at=_NEWER)
    # Both decided against an empty ledger, so both are verified_internal_fact;
    # only the source version distinguishes them.
    first_decision = _promote(first, version=_VERSION)
    second_decision = _promote(second, version=_NEWER)

    async def _write() -> None:
        await ledger.append(_ACCOUNT, first, first_decision, recorded_at="2026-10-21T09:00:00Z")
        await ledger.append(_ACCOUNT, second, second_decision, recorded_at="2026-10-21T10:00:00Z")

    asyncio.run(_write())
    records = asyncio.run(ledger.records(_ACCOUNT)).records
    assert len(records) == 2
    assert {record.source_version for record in records} == {_VERSION, _NEWER}


def test_records_are_newest_first() -> None:
    store = InMemoryStore()
    ledger = PromotionLedger(store)
    first = _candidate()
    second = _candidate(key="style:style_2", source_ref="creative-memory://style/style_2")

    async def _write() -> None:
        await ledger.append(
            _ACCOUNT, first, _promote(first), recorded_at="2026-10-21T09:00:00+00:00"
        )
        await ledger.append(
            _ACCOUNT, second, _promote(second), recorded_at="2026-10-21T11:00:00+00:00"
        )

    asyncio.run(_write())
    records = asyncio.run(ledger.records(_ACCOUNT)).records
    assert [record.recorded_at for record in records] == [
        "2026-10-21T11:00:00+00:00",
        "2026-10-21T09:00:00+00:00",
    ]


def test_an_incomplete_page_says_so() -> None:
    store = InMemoryStore()
    ledger = PromotionLedger(store)
    candidate = _candidate()

    async def _write() -> None:
        await ledger.append(
            _ACCOUNT, candidate, _promote(candidate), recorded_at="2026-10-21T09:00:00Z"
        )

    asyncio.run(_write())
    page = asyncio.run(ledger.records(_ACCOUNT, limit=1))
    assert page.complete is False


class _RaisingStore:
    async def aput(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("store down")

    async def asearch(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        raise RuntimeError("store down")


def test_a_store_failure_raises() -> None:
    store = _RaisingStore()
    ledger = PromotionLedger(store)
    candidate = _candidate()
    with pytest.raises(RuntimeError, match="store down"):
        asyncio.run(ledger.append(_ACCOUNT, candidate, _promote(candidate)))
    with pytest.raises(RuntimeError, match="store down"):
        asyncio.run(ledger.records(_ACCOUNT))


def test_current_entries_derives_from_supersede_edges() -> None:
    """The present is computed from append-only history, never from a flag."""
    old_id = "promo_old"
    records = (
        PromotionRecord(
            promotion_id=old_id,
            candidate_id="cand_1",
            namespace="strategy_notes",
            key="style:style_1",
            source_ref="creative-memory://style/style_1",
            source_version=_VERSION,
            disposition="promote",
            reason="verified_internal_fact",
            dedupe="new",
            verified=True,
            supersedes=(),
            decided_by="machine",
            policy_version=DEFAULT_PROMOTION_POLICY_VERSION,
            recorded_at="2026-10-21T09:00:00Z",
        ),
        PromotionRecord(
            promotion_id="promo_new",
            candidate_id="cand_1",
            namespace="strategy_notes",
            key="style:style_1",
            source_ref="creative-memory://style/style_1",
            source_version=_NEWER,
            disposition="promote",
            reason="supersedes_older",
            dedupe="supersedes",
            verified=True,
            supersedes=(old_id,),
            decided_by="machine",
            policy_version=DEFAULT_PROMOTION_POLICY_VERSION,
            recorded_at="2026-10-21T10:00:00Z",
        ),
    )
    current = current_entries(records)
    assert len(current) == 1
    assert current[0].promotion_id == "promo_new"
    assert current[0].source_version == _NEWER


def test_non_promote_records_never_enter_the_current_set() -> None:
    candidate = _candidate()
    decision = decide_promotion(
        candidate,
        source=SourceCheck(present=True, version=_VERSION, evidence_found=candidate.evidence_ids),
    )
    duplicate = PromotionDecision(
        candidate_id=decision.candidate_id,
        disposition=PromotionDisposition.REFUSE,
        reason=PromotionReason.DUPLICATE,
        dedupe=decision.dedupe,
        verified=True,
        supersedes=(),
        decided_by="machine",
        policy_version=DEFAULT_PROMOTION_POLICY_VERSION,
    )
    record = PromotionRecord(
        promotion_id=promotion_id_for(duplicate, source_version=_VERSION),
        candidate_id=duplicate.candidate_id,
        namespace=candidate.namespace,
        key=candidate.key,
        source_ref=candidate.source_ref,
        source_version=_VERSION,
        disposition=duplicate.disposition.value,
        reason=duplicate.reason.value,
        dedupe=duplicate.dedupe.value,
        verified=True,
        supersedes=(),
        decided_by="machine",
        policy_version=DEFAULT_PROMOTION_POLICY_VERSION,
        recorded_at="2026-10-21T09:00:00Z",
    )
    assert current_entries((record,)) == ()


def test_two_current_records_for_one_key_raise() -> None:
    def record(promotion_id: str) -> PromotionRecord:
        return PromotionRecord(
            promotion_id=promotion_id,
            candidate_id="cand_1",
            namespace="strategy_notes",
            key="style:style_1",
            source_ref="creative-memory://style/style_1",
            source_version=_VERSION,
            disposition="promote",
            reason="verified_internal_fact",
            dedupe="new",
            verified=True,
            supersedes=(),
            decided_by="machine",
            policy_version=DEFAULT_PROMOTION_POLICY_VERSION,
            recorded_at="2026-10-21T09:00:00Z",
        )

    with pytest.raises(ValueError, match="two current promote records"):
        current_entries((record("promo_a"), record("promo_b")))


def test_a_record_round_trips_through_its_stored_dict() -> None:
    record = PromotionRecord(
        promotion_id="promo_1",
        candidate_id="cand_1",
        namespace="strategy_notes",
        key="style:style_1",
        source_ref="creative-memory://style/style_1",
        source_version=_VERSION,
        disposition="promote",
        reason="supersedes_older",
        dedupe="supersedes",
        verified=True,
        supersedes=("promo_1", "promo_2"),
        decided_by="machine",
        policy_version=DEFAULT_PROMOTION_POLICY_VERSION,
        recorded_at="2026-10-21T09:00:00Z",
    )
    assert PromotionRecord.from_dict(record.to_dict()) == record
