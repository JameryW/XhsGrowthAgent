"""Lease data plane: a lease states who is running a thread (P2b-S1).

Two jobs here. The obvious one is that the store behaves on the path it claims
to support (the no-Postgres fallback, so the tests are hermetic). The other is
the S1-specific invariant: the plane must be *plugged in*, not merely present.
That is why ``heartbeat_at`` has a reader in this file (``expire_scan``, through
``is_stale``) and why the TTL is asserted to be derived from the heartbeat
budget rather than sitting next to it — a constant carrying a comment but no
assertion is a mutation that survives.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

from backend.db import execution_leases as leases

_BASE = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
_OTHER_OWNER = "other-host:4242:deadbeef"


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch):
    """Every test runs the fallback explicitly, never by accident of no pool."""
    monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
    leases._reset_memory_store()
    yield
    leases._reset_memory_store()


@pytest.fixture
def clock(monkeypatch) -> list[float]:
    """A hand-cranked clock, so lease age never depends on host resolution.

    The memory fallback stamps times from ``_utcnow()``; driving it here keeps
    the TTL assertions exact instead of timing-dependent (the repo has already
    been bitten by a ~15.6 ms Windows clock making two writes share a tick).
    """
    ticks = [0.0]
    monkeypatch.setattr(leases, "_utcnow", lambda: _BASE + timedelta(seconds=ticks[0]))
    return ticks


def _advance(clock: list[float], seconds: float) -> None:
    clock[0] += seconds


class TestLeaseBudget:
    def test_ttl_and_heartbeat_are_one_decision(self) -> None:
        # At least one missed renew must not expire a live lease, and the TTL
        # must be exactly what that budget adds up to.
        assert leases.HEARTBEAT_MISSES_BEFORE_EXPIRY >= 2
        assert (
            pytest.approx(leases.HEARTBEAT_INTERVAL_SECONDS * leases.HEARTBEAT_MISSES_BEFORE_EXPIRY)
            == leases.LEASE_TTL_SECONDS
        )

    def test_the_lease_budget_stays_inside_its_policy_envelope(self) -> None:
        # The relation above is definitional -- it holds for any value -- so it
        # pins the derivation, not the magnitude. The magnitude is a policy
        # choice, pinned here as an envelope: long enough that a live owner is
        # never declared dead, short enough that a dead one is noticed promptly.
        assert 60.0 <= leases.LEASE_TTL_SECONDS <= 300.0

    def test_instance_identity_names_the_process(self) -> None:
        instance_id, started_at = leases.instance_identity()
        assert str(os.getpid()) in instance_id
        assert started_at.tzinfo is not None


class TestDurabilityIsAReadableFact:
    def test_none_without_postgres(self, monkeypatch) -> None:
        monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
        assert leases.durability() is leases.LeaseDurability.NONE

    def test_durable_with_postgres(self, monkeypatch) -> None:
        monkeypatch.setattr(leases, "is_pool_ready", lambda: True)
        assert leases.durability() is leases.LeaseDurability.DURABLE


class TestAcquire:
    async def test_takes_a_free_lease(self) -> None:
        assert await leases.acquire("t1") is True
        record = await leases.get_lease("t1")
        assert record is not None
        assert record.state is leases.LeaseState.HELD
        assert record.owner_id == leases.instance_identity()[0]
        assert record.heartbeat_at == record.acquired_at

    async def test_refuses_a_live_lease_from_another_owner(self, monkeypatch) -> None:
        assert await leases.acquire("t1") is True
        monkeypatch.setattr(leases, "_instance_id", _OTHER_OWNER)

        assert await leases.acquire("t1") is False
        assert (await leases.get_lease("t1")).owner_id != _OTHER_OWNER

    async def test_takes_over_a_silent_lease(self, monkeypatch) -> None:
        await leases.acquire("t1", ttl_seconds=0.0)
        monkeypatch.setattr(leases, "_instance_id", _OTHER_OWNER)

        assert await leases.acquire("t1") is True
        assert (await leases.get_lease("t1")).owner_id == _OTHER_OWNER

    async def test_takes_over_an_expired_lease_from_another_owner(self, monkeypatch) -> None:
        """The state S3's scan actually meets, and the divergence it found.

        The scan calls ``expire_scan`` before it acquires, so the row it is
        taking over is already ``expired`` by then. ``_ACQUIRE_SQL`` grants that
        (``state <> 'held'``); the fallback used to refuse it, because it judged
        the incumbent with ``is_stale`` -- which answers "held and expired", and
        so is False for an expired row. Same question, two answers.
        """
        await leases.acquire("t1", ttl_seconds=0.0)
        assert await leases.expire_scan() == ["t1"]
        monkeypatch.setattr(leases, "_instance_id", _OTHER_OWNER)

        assert await leases.acquire("t1") is True
        record = await leases.get_lease("t1")
        assert record is not None
        assert record.owner_id == _OTHER_OWNER
        assert record.state is leases.LeaseState.HELD

    async def test_takes_over_a_released_lease_from_another_owner(self, monkeypatch) -> None:
        """The same clause of the SQL, reached by the other non-held state."""
        await leases.acquire("t1")
        assert await leases.release("t1") is True
        monkeypatch.setattr(leases, "_instance_id", _OTHER_OWNER)

        assert await leases.acquire("t1") is True
        assert (await leases.get_lease("t1")).owner_id == _OTHER_OWNER

    async def test_the_lease_carries_its_own_budget(self, monkeypatch) -> None:
        # The incumbent's budget decides, not the newcomer's: otherwise the
        # same row would be live to a long-TTL reader and dead to a short-TTL
        # one -- two answers for one state.
        await leases.acquire("t1", ttl_seconds=0.0)
        monkeypatch.setattr(leases, "_instance_id", _OTHER_OWNER)

        assert await leases.acquire("t1") is True
        assert (await leases.get_lease("t1")).ttl_seconds == leases.LEASE_TTL_SECONDS

    async def test_is_reentrant_for_the_same_owner(self) -> None:
        await leases.acquire("t1")
        assert await leases.acquire("t1") is True

    async def test_empty_thread_id_is_never_leased(self) -> None:
        assert await leases.acquire("") is False
        assert await leases.get_lease("") is None


class TestRenewAndRelease:
    async def test_renew_moves_the_anchor_it_owns(self, clock: list[float]) -> None:
        await leases.acquire("t1")
        first = (await leases.get_lease("t1")).heartbeat_at

        _advance(clock, 5)
        assert await leases.renew("t1") is True

        assert (await leases.get_lease("t1")).heartbeat_at == first + timedelta(seconds=5)

    async def test_renew_reports_false_once_the_lease_moved_on(self, monkeypatch) -> None:
        await leases.acquire("t1")
        monkeypatch.setattr(leases, "_instance_id", _OTHER_OWNER)

        assert await leases.renew("t1") is False
        # A refused renew must not be a claim on someone else's lease.
        assert (await leases.get_lease("t1")).owner_id != _OTHER_OWNER

    async def test_renew_adopts_the_current_budget(self, clock: list[float]) -> None:
        await leases.acquire("t1", ttl_seconds=1.0)
        _advance(clock, 1)

        assert await leases.renew("t1", ttl_seconds=30.0) is True

        assert (await leases.get_lease("t1")).ttl_seconds == 30.0

    async def test_a_released_lease_cannot_be_renewed_back_to_life(self) -> None:
        # A heartbeat that loses the cancel race must not be able to revive a
        # lease this instance already gave up.
        await leases.acquire("t1")
        assert await leases.release("t1") is True

        assert await leases.renew("t1") is False
        assert (await leases.get_lease("t1")).state is leases.LeaseState.RELEASED

    async def test_release_marks_released(self) -> None:
        await leases.acquire("t1")
        assert await leases.release("t1") is True
        assert (await leases.get_lease("t1")).state is leases.LeaseState.RELEASED

    async def test_release_leaves_another_owners_lease_alone(self, monkeypatch) -> None:
        await leases.acquire("t1")
        monkeypatch.setattr(leases, "_instance_id", _OTHER_OWNER)

        assert await leases.release("t1") is False
        assert (await leases.get_lease("t1")).state is leases.LeaseState.HELD

    async def test_empty_thread_id_is_never_renewed_or_released(self) -> None:
        assert await leases.renew("") is False
        assert await leases.release("") is False


class TestExpireScan:
    async def test_flips_only_the_silent_held_lease(self, clock: list[float]) -> None:
        await leases.acquire("silent")
        await leases.acquire("busy")

        _advance(clock, 30)
        assert await leases.renew("busy") is True

        # Past silent's expiry, still inside busy's renewed window.
        _advance(clock, leases.LEASE_TTL_SECONDS - 1)

        assert await leases.expire_scan() == ["silent"]
        assert (await leases.get_lease("silent")).state is leases.LeaseState.EXPIRED
        assert (await leases.get_lease("busy")).state is leases.LeaseState.HELD

    async def test_ignores_a_released_lease(self, clock: list[float]) -> None:
        await leases.acquire("t1")
        assert await leases.release("t1") is True

        _advance(clock, leases.LEASE_TTL_SECONDS * 10)

        assert await leases.expire_scan() == []
        assert (await leases.get_lease("t1")).state is leases.LeaseState.RELEASED

    async def test_reports_an_expiry_once(self, clock: list[float]) -> None:
        await leases.acquire("t1")
        _advance(clock, leases.LEASE_TTL_SECONDS + 1)

        assert await leases.expire_scan() == ["t1"]
        assert await leases.expire_scan() == []


class TestReads:
    async def test_reads_hand_back_a_snapshot(self) -> None:
        # Postgres builds a fresh record per row; the fallback must not let a
        # caller mutate the store through a read.
        await leases.acquire("t1")
        record = await leases.get_lease("t1")
        record.state = leases.LeaseState.RELEASED

        assert (await leases.get_lease("t1")).state is leases.LeaseState.HELD

    async def test_get_returns_none_for_an_unleased_thread(self) -> None:
        assert await leases.get_lease("nobody") is None

    async def test_list_orders_by_heartbeat_and_filters_by_state(self, clock: list[float]) -> None:
        await leases.acquire("early")
        _advance(clock, 10)
        await leases.acquire("late")

        assert [r.thread_id for r in await leases.list_leases()] == ["early", "late"]

        await leases.release("early")
        held = await leases.list_leases(state=leases.LeaseState.HELD)
        assert [r.thread_id for r in held] == ["late"]


class TestHeartbeatTask:
    async def test_start_keeps_the_lease_fresh(self, clock: list[float]) -> None:
        heartbeat = await leases.start_lease("t1", interval_seconds=0.005)
        assert heartbeat is not None
        try:
            _advance(clock, 5)
            deadline = asyncio.get_running_loop().time() + 5.0
            while (await leases.get_lease("t1")).heartbeat_at == _BASE:
                assert asyncio.get_running_loop().time() < deadline, "heartbeat never renewed"
                await asyncio.sleep(0.005)
        finally:
            # Also bounded: the teardown must not swallow a failure from the
            # loop above by hanging in place of raising.
            await asyncio.wait_for(leases.end_lease("t1", heartbeat), timeout=5.0)

    async def test_heartbeat_stops_when_the_lease_is_lost(self, monkeypatch) -> None:
        heartbeat = await leases.start_lease("t1", interval_seconds=0.005)
        assert heartbeat is not None

        # Someone else takes the thread while we are still heartbeating.
        monkeypatch.setattr(leases, "_instance_id", _OTHER_OWNER)

        await asyncio.wait_for(heartbeat, timeout=5.0)
        assert heartbeat.done()

    async def test_end_stops_the_heartbeat_and_releases(self) -> None:
        heartbeat = await leases.start_lease("t1")
        assert heartbeat is not None

        # Bounded on purpose: a teardown that forgets to cancel the heartbeat
        # would otherwise wait on it here forever -- a hang, not a failure, and
        # a hang tells the next reader nothing.
        await asyncio.wait_for(leases.end_lease("t1", heartbeat), timeout=5.0)

        assert heartbeat.done()
        assert (await leases.get_lease("t1")).state is leases.LeaseState.RELEASED

    async def test_end_without_a_heartbeat_still_releases(self) -> None:
        await leases.acquire("t1")

        await leases.end_lease("t1", None)

        assert (await leases.get_lease("t1")).state is leases.LeaseState.RELEASED

    async def test_start_returns_none_when_refused(self, monkeypatch) -> None:
        assert await leases.acquire("t1") is True
        monkeypatch.setattr(leases, "_instance_id", _OTHER_OWNER)

        assert await leases.start_lease("t1") is None
