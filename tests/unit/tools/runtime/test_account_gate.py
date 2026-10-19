"""Per-account slot gate tests — process-local half, PG half, degradation.

The gate replaces the Gateway's bare process-local semaphore so that
``max_concurrency`` is a *per-account* ceiling shared across workers. Two
facts are load-bearing and pinned here:

* the PG half degrades to the process-local half when the pool is down —
  single-worker deployments must not need Postgres to get a ceiling;
* a busy slot fails **within the budget** rather than queueing forever —
  the call never started, so a clean timeout is the safe answer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.tools.runtime.account_gate import (
    AccountSlot,
    AccountSlotTimeoutError,
    _PgSlotHold,
    _SlotProbe,
    _SlotStatus,
    _try_acquire_pg_slot,
    acquire_account_slot,
    hold_account_slot,
    reset_account_gates_for_tests,
)


async def _acquire_outcome(
    coro: Coroutine[Any, Any, AccountSlot], *, hang_budget: float = 1.0
) -> str:
    """``"acquired"`` / ``"slot-timeout"`` / ``"hang"``.

    A hang is reported as a value so that a mutant which removes the wait
    budget turns into an *assertion* red (wrong outcome) instead of a hung
    run or an escaped ``TimeoutError`` — a crash-style red is not coverage.
    """
    try:
        slot = await asyncio.wait_for(coro, timeout=hang_budget)
    except AccountSlotTimeoutError:
        return "slot-timeout"
    except TimeoutError:
        return "hang"
    await slot.release()
    return "acquired"


class _Cursor:
    def __init__(self, fetchone_results: list[Any] | None = None) -> None:
        self.sql: list[str] = []
        self.params: list[Any] = []
        self._fetchone = list(fetchone_results or [])

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> None:
        self.sql.append(sql)
        self.params.append(params)

    async def fetchone(self) -> Any:
        return self._fetchone.pop(0) if self._fetchone else None


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    def cursor(self, row_factory: Any = None) -> _Cursor:
        return self._cursor


class _Pool:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def connection(self) -> _Connection:
        return _Connection(self._cursor)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # Shrink the busy-wait poll gap so 0.05s-budget tests don't sleep the
    # full 0.15s default (the deadline check only fires after the sleep).
    monkeypatch.setattr("backend.tools.runtime.account_gate._BUSY_POLL_S", 0.01)
    # Deterministic degraded default: no pool -> process-local half only.
    # Tests that want the PG half re-patch this underneath themselves.
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)
    reset_account_gates_for_tests()
    yield
    reset_account_gates_for_tests()


class TestLocalSlots:
    @pytest.mark.asyncio
    async def test_a_key_holds_at_most_limit_slots(self):
        """Three waiters, limit 2: exactly two slots and one bounded refusal.

        The two that get in *hold* until the round is over — a helper that
        released on the spot would recycle the slots and prove nothing.
        """
        held: list[AccountSlot] = []

        async def try_acquire() -> str:
            try:
                slot = await asyncio.wait_for(
                    acquire_account_slot(key="cap|a1", limit=2, wait_timeout_s=0.5), timeout=1.0
                )
            except AccountSlotTimeoutError:
                return "slot-timeout"
            except TimeoutError:
                return "hang"
            held.append(slot)
            return "acquired"

        results = await asyncio.gather(*(try_acquire() for _ in range(3)))
        try:
            assert sorted(results) == ["acquired", "acquired", "slot-timeout"]
        finally:
            for slot in held:
                await slot.release()

    @pytest.mark.asyncio
    async def test_different_keys_do_not_share_slots(self):
        async with hold_account_slot(key="cap|a1", limit=1, wait_timeout_s=1.0):
            other = await acquire_account_slot(key="cap|a2", limit=1, wait_timeout_s=0.5)
            assert other.key == "cap|a2"
            await other.release()

    @pytest.mark.asyncio
    async def test_release_returns_the_slot(self):
        slot = await acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=1.0)
        await slot.release()
        assert (
            await _acquire_outcome(acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=0.5))
            == "acquired"
        )

    @pytest.mark.asyncio
    async def test_release_is_idempotent(self):
        """A double release must not free the slot twice (limit stays 1)."""
        slot = await acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=1.0)
        await slot.release()
        await slot.release()  # must not free a slot twice
        again = await acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=0.5)
        assert (
            await _acquire_outcome(acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=0.05))
            == "slot-timeout"
        )
        await again.release()

    @pytest.mark.asyncio
    async def test_a_limit_change_on_one_key_is_refused(self):
        slot = await acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=1.0)
        await slot.release()
        with pytest.raises(ValueError, match="limit"):
            await acquire_account_slot(key="cap|a1", limit=2, wait_timeout_s=1.0)

    @pytest.mark.asyncio
    async def test_the_local_ceiling_times_out_a_third_waiter(self):
        """The budget bounds the wait — nothing queues forever."""
        holder = await acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=1.0)
        try:
            assert (
                await _acquire_outcome(
                    acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=0.05)
                )
                == "slot-timeout"
            )
        finally:
            await holder.release()


class TestPgSlotProbes:
    """The real probe against a fake pool — SQL shape and slot indexing."""

    def _pool_up(self, monkeypatch, cursor: _Cursor) -> _Pool:
        pool = _Pool(cursor)
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)
        monkeypatch.setattr("backend.db.pool.get_pool", lambda: pool)
        return pool

    @pytest.mark.asyncio
    async def test_the_first_slot_is_taken_and_unlocked_by_slot_key(self, monkeypatch):
        cursor = _Cursor(fetchone_results=[(True,)])
        self._pool_up(monkeypatch, cursor)
        probe = await _try_acquire_pg_slot("cap|a1", 1)
        assert probe.status is _SlotStatus.ACQUIRED
        assert probe.hold is not None
        assert cursor.sql[0] == "SELECT pg_try_advisory_lock(%s, hashtext(%s))"
        assert cursor.params[0] == (8911, "cap|a1#0")
        await probe.hold.release()
        assert cursor.sql[-1] == "SELECT pg_advisory_unlock(%s, hashtext(%s))"
        assert cursor.params[-1] == (8911, "cap|a1#0")

    @pytest.mark.asyncio
    async def test_slots_are_taken_in_index_order(self, monkeypatch):
        cursor = _Cursor(fetchone_results=[(False,), (True,)])
        self._pool_up(monkeypatch, cursor)
        probe = await _try_acquire_pg_slot("cap|a1", 2)
        assert probe.status is _SlotStatus.ACQUIRED
        assert probe.hold is not None
        assert cursor.params == [(8911, "cap|a1#0"), (8911, "cap|a1#1")]
        await probe.hold.release()
        assert cursor.params[-1] == (8911, "cap|a1#1")

    @pytest.mark.asyncio
    async def test_every_slot_taken_reports_busy(self, monkeypatch):
        cursor = _Cursor(fetchone_results=[(False,), (False,)])
        self._pool_up(monkeypatch, cursor)
        probe = await _try_acquire_pg_slot("cap|a1", 2)
        assert probe.status is _SlotStatus.BUSY
        assert probe.hold is None

    @pytest.mark.asyncio
    async def test_a_down_pool_reports_unavailable(self):
        probe = await _try_acquire_pg_slot("cap|a1", 1)
        assert probe.status is _SlotStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_a_pool_failure_degrades_to_unavailable(self, monkeypatch):
        """A broken pool is 'unavailable', never an exception to the caller."""
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

        def _boom() -> Any:
            raise RuntimeError("pool down")

        monkeypatch.setattr("backend.db.pool.get_pool", _boom)
        probe = await _try_acquire_pg_slot("cap|a1", 1)
        assert probe.status is _SlotStatus.UNAVAILABLE


class TestPgPolicy:
    """The acquisition loop around the probe — busy waits, degrade, timeout."""

    @pytest.mark.asyncio
    async def test_a_busy_pg_slot_times_out_rather_than_waiting_forever(self, monkeypatch):
        monkeypatch.setattr(
            "backend.tools.runtime.account_gate._try_acquire_pg_slot",
            AsyncMock(return_value=_SlotProbe.busy()),
        )
        assert (
            await _acquire_outcome(acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=0.05))
            == "slot-timeout"
        )

    @pytest.mark.asyncio
    async def test_a_slot_freed_before_the_deadline_is_taken(self, monkeypatch):
        hold = _PgSlotHold(object(), object(), "cap|a1#0")
        monkeypatch.setattr(
            "backend.tools.runtime.account_gate._try_acquire_pg_slot",
            AsyncMock(side_effect=[_SlotProbe.busy(), _SlotProbe.acquired(hold)]),
        )
        slot = await acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=1.0)
        try:
            assert slot.distributed is True
        finally:
            await slot.release()

    @pytest.mark.asyncio
    async def test_an_unavailable_pg_degrades_to_process_local_only(self, monkeypatch):
        monkeypatch.setattr(
            "backend.tools.runtime.account_gate._try_acquire_pg_slot",
            AsyncMock(return_value=_SlotProbe.unavailable()),
        )
        slot = await acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=0.5)
        try:
            assert slot.distributed is False
        finally:
            await slot.release()

    @pytest.mark.asyncio
    async def test_a_local_timeout_never_reaches_the_pg_probe(self, monkeypatch):
        probe = AsyncMock(return_value=_SlotProbe.unavailable())
        monkeypatch.setattr("backend.tools.runtime.account_gate._try_acquire_pg_slot", probe)
        holder = await acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=1.0)
        try:
            probe.reset_mock()  # the holder's own probe is not the point
            assert (
                await _acquire_outcome(
                    acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=0.05)
                )
                == "slot-timeout"
            )
            probe.assert_not_awaited()
        finally:
            await holder.release()


class TestHoldContextManager:
    @pytest.mark.asyncio
    async def test_the_block_form_releases_on_exit(self):
        async with hold_account_slot(key="cap|a1", limit=1, wait_timeout_s=1.0) as slot:
            assert slot.key == "cap|a1"
        again = await acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=0.5)
        await again.release()

    @pytest.mark.asyncio
    async def test_the_block_form_releases_on_an_exception_inside(self):
        with pytest.raises(RuntimeError, match="boom"):
            async with hold_account_slot(key="cap|a1", limit=1, wait_timeout_s=1.0):
                raise RuntimeError("boom")
        again = await acquire_account_slot(key="cap|a1", limit=1, wait_timeout_s=0.5)
        await again.release()
