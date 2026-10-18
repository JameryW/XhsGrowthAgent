"""Effect Ledger — the guard must never read UNKNOWN as FAILED."""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from backend.state.effects import (
    BLOCKING_STATUSES,
    EffectBlockedError,
    EffectLedger,
    EffectStatus,
    StaleEffectWriteError,
)


@pytest.fixture
def ledger() -> EffectLedger:
    return EffectLedger(InMemoryStore())


class TestNormalization:
    @pytest.mark.asyncio
    async def test_legacy_published_normalises_to_confirmed(self, ledger: EffectLedger):
        await ledger._store.aput(("effects",), "e1", {"status": "published"})
        record = await ledger.get("e1")
        assert record is not None and record.status is EffectStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_unrecognised_status_normalises_to_unknown(self, ledger: EffectLedger):
        await ledger._store.aput(("effects",), "e1", {"status": "weird"})
        record = await ledger.get("e1")
        # Unknown must never decay into FAILED (that would release the guard).
        assert record is not None and record.status is EffectStatus.UNKNOWN
        assert record.blocks_retry is True

    @pytest.mark.asyncio
    async def test_extra_fields_survive_round_trip(self, ledger: EffectLedger):
        await ledger._store.aput(
            ("effects",), "e1", {"status": "published", "post_id": "p9", "account_id": "a"}
        )
        record = await ledger.get("e1")
        assert record is not None
        assert record.extra == {"post_id": "p9", "account_id": "a"}


class TestBegin:
    @pytest.mark.asyncio
    async def test_first_begin_claims_in_flight(self, ledger: EffectLedger):
        record = await ledger.begin("e1", tool_name="publish")
        assert record.status is EffectStatus.IN_FLIGHT
        assert record.attempt == 1
        assert record.version == 1

    @pytest.mark.asyncio
    async def test_second_begin_is_blocked_while_in_flight(self, ledger: EffectLedger):
        await ledger.begin("e1")
        with pytest.raises(EffectBlockedError) as exc_info:
            await ledger.begin("e1")
        assert exc_info.value.record.status is EffectStatus.IN_FLIGHT

    @pytest.mark.asyncio
    async def test_force_bypasses_block_and_increments_attempt(self, ledger: EffectLedger):
        await ledger.mark("e1", EffectStatus.UNKNOWN)
        record = await ledger.begin("e1", force=True)
        assert record.attempt == 2
        assert record.status is EffectStatus.IN_FLIGHT

    @pytest.mark.asyncio
    async def test_failed_does_not_block_retry(self, ledger: EffectLedger):
        await ledger.begin("e1")
        await ledger.mark("e1", EffectStatus.FAILED)
        record = await ledger.begin("e1")
        assert record.attempt == 2
        assert record.status is EffectStatus.IN_FLIGHT

    @pytest.mark.asyncio
    async def test_confirmed_blocks(self, ledger: EffectLedger):
        await ledger.begin("e1")
        await ledger.mark("e1", EffectStatus.CONFIRMED)
        with pytest.raises(EffectBlockedError):
            await ledger.begin("e1")

    @pytest.mark.asyncio
    async def test_reconciling_blocks(self, ledger: EffectLedger):
        await ledger.mark("e1", EffectStatus.UNKNOWN)
        await ledger.mark("e1", EffectStatus.RECONCILING)
        with pytest.raises(EffectBlockedError):
            await ledger.begin("e1")


class TestTransitions:
    @pytest.mark.asyncio
    async def test_legal_path_to_confirmed(self, ledger: EffectLedger):
        await ledger.begin("e1")
        record = await ledger.mark("e1", EffectStatus.CONFIRMED, result_ref="r1")
        assert record.status is EffectStatus.CONFIRMED
        assert record.result_ref == "r1"
        assert record.version == 2

    @pytest.mark.asyncio
    async def test_illegal_terminal_transition_is_refused(self, ledger: EffectLedger):
        await ledger.begin("e1")
        await ledger.mark("e1", EffectStatus.CONFIRMED)
        with pytest.raises(ValueError, match="illegal transition"):
            await ledger.mark("e1", EffectStatus.UNKNOWN)

    @pytest.mark.asyncio
    async def test_unknown_can_reconcile(self, ledger: EffectLedger):
        await ledger.mark("e1", EffectStatus.UNKNOWN)
        record = await ledger.mark("e1", EffectStatus.RECONCILING)
        assert record.status is EffectStatus.RECONCILING

    @pytest.mark.asyncio
    async def test_stale_write_is_refused(self, ledger: EffectLedger):
        await ledger.begin("e1")
        record = await ledger.get("e1")
        assert record is not None and record.version == 1
        await ledger.mark("e1", EffectStatus.UNKNOWN)  # version -> 2
        with pytest.raises(StaleEffectWriteError):
            await ledger.mark("e1", EffectStatus.FAILED, expect_version=1)

    @pytest.mark.asyncio
    async def test_missing_record_is_created_by_mark(self, ledger: EffectLedger):
        record = await ledger.mark("e9", EffectStatus.UNKNOWN, extra={"k": "v"})
        assert record.version == 1
        assert record.extra == {"k": "v"}

    @pytest.mark.asyncio
    async def test_extra_merges_on_transition(self, ledger: EffectLedger):
        await ledger.begin("e1")
        await ledger.mark("e1", EffectStatus.UNKNOWN, extra={"post_id": "p1"})
        record = await ledger.mark("e1", EffectStatus.FAILED)
        assert record.extra == {"post_id": "p1"}


class TestBlockingSet:
    def test_only_prepared_and_failed_are_non_blocking(self):
        # PREPARED = intent only; FAILED = a verdict that nothing happened.
        expected = {
            EffectStatus.IN_FLIGHT,
            EffectStatus.CONFIRMED,
            EffectStatus.UNKNOWN,
            EffectStatus.RECONCILING,
        }
        assert expected == BLOCKING_STATUSES
