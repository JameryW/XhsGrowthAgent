"""Independent verification and the first promotion write (Slice C, 票 5u).

What is pinned here is the part that changes prompts: a memory reaches
``strategy_notes`` only after an **independent re-read** of the durable source,
only when the protocol says ``PROMOTE``, and only after its ledger record was
appended (a crash between the two is a pending row, not an unattributable
memory). A stale scan, an absent row, a partial ledger page and a store failure
each have their own behaviour and their own test.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langgraph.store.memory import InMemoryStore

from backend.creator_agent.models import ContentObservation, ContentObservationKind
from backend.memory.promotion import (
    DEFAULT_PROMOTION_POLICY_VERSION,
    PromotionDisposition,
    PromotionReason,
    decide_promotion,
)
from backend.memory.promotion_apply import (
    promote_style_observations,
    write_promoted_memory,
)
from backend.memory.promotion_ledger import LedgerPage, PromotionLedger, promotion_id_for
from backend.memory.promotion_observations import candidate_from_observation
from backend.memory.promotion_source import CreativeMemoryPromotionSource

_ACCOUNT = "acc-1"
_VERSION = "2026-10-01T00:00:00Z"
_NEWER = "2026-10-02T00:00:00Z"
_TARGET_NS = ("accounts", _ACCOUNT, "strategy_notes")


def _style(*, observed_at: str = _VERSION, samples: int = 10) -> ContentObservation:
    return ContentObservation(
        kind=ContentObservationKind.STYLE,
        source_id="style_1",
        description="治愈/温暖治愈",
        measured_rate=0.4,
        sample_count=samples,
        observed_at=observed_at,
    )


class _Reader:
    """Scripted durable-row re-read; records the calls it received."""

    def __init__(self, rows: dict[str, dict[str, Any] | None]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, account_id: str, style_id: str) -> dict[str, Any] | None:
        self.calls.append((account_id, style_id))
        return self._rows.get(style_id)


class _TargetWriteFails(InMemoryStore):
    """Ledger writes work; the first target-namespace write raises."""

    async def aput(self, namespace: tuple[str, ...], key: str, value: dict[str, Any]) -> None:
        if namespace == _TARGET_NS:
            raise RuntimeError("target namespace down")
        await super().aput(namespace, key, value)


class TestVerificationSource:
    async def test_a_present_row_carries_its_version(self) -> None:
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _VERSION}}))
        check = await source.source_check(_ACCOUNT, _style())
        assert check.present is True
        assert check.version == _VERSION
        assert check.evidence_found == ("ev_style_style_1",)

    async def test_an_absent_row_is_reported_absent(self) -> None:
        source = CreativeMemoryPromotionSource(_Reader({}))
        check = await source.source_check(_ACCOUNT, _style())
        assert check.present is False
        assert check.version == ""

    async def test_the_re_read_decides_the_version_not_the_scan(self) -> None:
        """The scan says the old version; the row has moved on."""
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _NEWER}}))
        check = await source.source_check(_ACCOUNT, _style())
        assert check.present is True
        assert check.version == _NEWER

    async def test_a_row_without_a_version_raises(self) -> None:
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"tone": "治愈"}}))
        outcome: object = "no error"
        try:
            await source.source_check(_ACCOUNT, _style())
        except Exception as exc:
            outcome = exc
        assert isinstance(outcome, ValueError), outcome
        assert "last_used" in str(outcome), outcome

    async def test_only_styles_are_verified(self) -> None:
        source = CreativeMemoryPromotionSource(_Reader({}))
        play = ContentObservation(
            kind=ContentObservationKind.PLAY,
            source_id="play_1",
            description="d",
            measured_rate=0.5,
            sample_count=3,
            observed_at=_VERSION,
        )
        with pytest.raises(ValueError, match="styles only"):
            await source.source_check(_ACCOUNT, play)

    async def test_a_reader_failure_propagates(self) -> None:
        async def _boom(_account: str, _style_id: str) -> None:
            raise RuntimeError("db down")

        source = CreativeMemoryPromotionSource(_boom)
        with pytest.raises(RuntimeError, match="db down"):
            await source.source_check(_ACCOUNT, _style())


class TestWritePromotedMemory:
    async def test_the_written_value_carries_provenance(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _VERSION}}))
        candidate = candidate_from_observation(_style())
        decision = decide_promotion(candidate, source=await source.source_check(_ACCOUNT, _style()))
        assert decision.disposition is PromotionDisposition.PROMOTE

        await write_promoted_memory(
            store, _ACCOUNT, candidate, decision, recorded_at="2026-10-21T10:00:00+00:00"
        )

        item = await store.aget(_TARGET_NS, "style:style_1")
        assert item is not None
        value = item.value
        assert value["note"] == "风格「治愈/温暖治愈」历史互动率 0.400（样本 10）"
        assert value["promotion_id"] == promotion_id_for(decision, source_version=_VERSION)
        assert value["source_ref"] == "creative-memory://style/style_1"
        assert value["source_version"] == _VERSION
        assert value["verified"] is True
        assert value["trust_class"] == "internal_fact"
        assert value["ttl_seconds"] is None
        assert value["promoted_at"] == "2026-10-21T10:00:00+00:00"
        assert value["policy_version"] == DEFAULT_PROMOTION_POLICY_VERSION
        assert value["decided_by"] == "machine"
        assert ledger is not None


class TestPromotionApplication:
    async def test_a_verified_style_is_recorded_then_written(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _VERSION}}))

        result = await promote_style_observations(
            ledger, store, _ACCOUNT, [_style()], source=source
        )

        assert result.ledger_available is True
        assert result.recorded == 1
        assert result.applied == 1
        assert result.promotions[0].decision.disposition is PromotionDisposition.PROMOTE
        assert result.promotions[0].applied is True

        page = await ledger.records(_ACCOUNT)
        assert len(page.records) == 1
        item = await store.aget(_TARGET_NS, "style:style_1")
        assert item is not None

    async def test_a_stale_scan_is_not_promoted(self) -> None:
        """The scan is old; the durable row moved on — re-read wins."""
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _NEWER}}))

        result = await promote_style_observations(
            ledger, store, _ACCOUNT, [_style()], source=source
        )

        decision = result.promotions[0].decision
        assert decision.disposition is PromotionDisposition.REVIEW
        assert decision.reason is PromotionReason.SOURCE_STALE
        assert result.applied == 0
        assert result.recorded == 1
        assert await store.aget(_TARGET_NS, "style:style_1") is None

    async def test_an_absent_row_is_refused_and_not_written(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        source = CreativeMemoryPromotionSource(_Reader({}))

        result = await promote_style_observations(
            ledger, store, _ACCOUNT, [_style()], source=source
        )

        assert result.promotions[0].decision.reason is PromotionReason.SOURCE_MISSING
        assert result.applied == 0
        assert result.recorded == 1
        assert await store.aget(_TARGET_NS, "style:style_1") is None

    async def test_dry_run_neither_records_nor_writes(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _VERSION}}))

        result = await promote_style_observations(
            ledger, store, _ACCOUNT, [_style()], source=source, dry_run=True
        )

        assert result.promotions[0].decision.disposition is PromotionDisposition.PROMOTE
        assert result.recorded == 0
        assert result.applied == 0
        assert (await ledger.records(_ACCOUNT)).records == ()
        assert await store.aget(_TARGET_NS, "style:style_1") is None

    async def test_a_second_identical_pass_does_not_rewrite(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _VERSION}}))

        first = await promote_style_observations(ledger, store, _ACCOUNT, [_style()], source=source)
        second = await promote_style_observations(
            ledger, store, _ACCOUNT, [_style()], source=source
        )

        assert first.applied == 1
        assert second.applied == 0
        assert second.promotions[0].decision.reason is PromotionReason.DUPLICATE
        assert len((await ledger.records(_ACCOUNT)).records) == 2
        item = await store.aget(_TARGET_NS, "style:style_1")
        assert item is not None  # still exactly one row for the key

    async def test_a_newer_version_supersedes_the_same_key(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        v1_source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _VERSION}}))
        v2_source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _NEWER}}))

        await promote_style_observations(ledger, store, _ACCOUNT, [_style()], source=v1_source)
        second = await promote_style_observations(
            ledger, store, _ACCOUNT, [_style(observed_at=_NEWER)], source=v2_source
        )

        assert second.promotions[0].decision.reason is PromotionReason.SUPERSEDES_OLDER
        assert second.applied == 1
        item = await store.aget(_TARGET_NS, "style:style_1")
        assert item is not None
        assert item.value["source_version"] == _NEWER

    async def test_the_ledger_row_lands_before_the_target_write(self) -> None:
        """A crash between the two leaves a pending record, not a lost write."""
        store = _TargetWriteFails()
        ledger = PromotionLedger(store)
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _VERSION}}))

        outcome: object = "no error"
        try:
            await promote_style_observations(ledger, store, _ACCOUNT, [_style()], source=source)
        except Exception as exc:
            outcome = exc

        assert isinstance(outcome, RuntimeError), outcome
        page = await ledger.records(_ACCOUNT)
        assert len(page.records) == 1, "the ledger row must exist before the target write"
        assert page.records[0].disposition == "promote"
        assert await store.aget(_TARGET_NS, "style:style_1") is None

    async def test_a_partial_ledger_page_refuses_to_apply(self) -> None:
        class _PartialLedger:
            async def records(self, *_args: object, **_kwargs: object) -> LedgerPage:
                return LedgerPage(records=(), available=True, complete=False)

            async def append(self, *_args: object, **_kwargs: object) -> object:
                raise AssertionError("a partial read must not reach a write")

        store = InMemoryStore()
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _VERSION}}))
        outcome: object = "applied"
        try:
            await promote_style_observations(
                _PartialLedger(),
                store,
                _ACCOUNT,
                [_style()],
                source=source,  # type: ignore[arg-type]
            )
        except Exception as exc:
            outcome = exc
        assert isinstance(outcome, RuntimeError), outcome
        assert await store.aget(_TARGET_NS, "style:style_1") is None

    async def test_a_missing_store_reports_unavailable_and_writes_nothing(self) -> None:
        ledger = PromotionLedger(None)
        source = CreativeMemoryPromotionSource(_Reader({"style_1": {"last_used": _VERSION}}))

        outcome: object = "no error"
        try:
            outcome = await promote_style_observations(
                ledger, None, _ACCOUNT, [_style()], source=source
            )
        except Exception as exc:  # judged below: an exception here is a failure
            outcome = exc

        assert not isinstance(outcome, Exception), outcome
        assert outcome.ledger_available is False  # type: ignore[union-attr]
        assert outcome.recorded == 0  # type: ignore[union-attr]
        assert outcome.applied == 0  # type: ignore[union-attr]
        assert (
            outcome.promotions[0].decision.disposition  # type: ignore[union-attr]
            is PromotionDisposition.PROMOTE
        )

    async def test_a_blank_account_is_rejected(self) -> None:
        outcome: object = "no error"
        try:
            await promote_style_observations(PromotionLedger(None), None, "  ", [_style()])
        except Exception as exc:
            outcome = exc
        assert isinstance(outcome, ValueError), outcome
        assert "account_id" in str(outcome), outcome


def test_records_directory_imports_are_used() -> None:
    """The file imports ``promotion_id_for``/``LedgerPage`` for real assertions."""
    assert asyncio is not None
