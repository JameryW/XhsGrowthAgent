"""The lease reader: "is anyone holding this thread right now" (P2b-S2).

``thread_is_held`` is the reason ``heartbeat_at`` exists. It answers from the
row's own budget, so a lease whose owner stopped heartbeating does not count as
held -- whether or not anything has swept it to ``expired`` yet.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.db import execution_leases as leases

_BASE = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
    leases._reset_memory_store()
    yield
    leases._reset_memory_store()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Fake clock driving ``leases._utcnow``; ``clock[0]`` is the offset."""
    ticks = [0.0]
    monkeypatch.setattr(leases, "_utcnow", lambda: _BASE + timedelta(seconds=ticks[0]))
    return ticks


def _advance(clock: list[float], seconds: float) -> None:
    clock[0] += seconds


class TestThreadIsHeld:
    async def test_no_lease_is_not_held(self) -> None:
        assert await leases.thread_is_held("t1") is False

    async def test_an_empty_thread_id_is_not_held(self) -> None:
        assert await leases.thread_is_held("") is False

    async def test_a_held_lease_is_held(self) -> None:
        await leases.acquire("t1")

        assert await leases.thread_is_held("t1") is True

    async def test_a_released_lease_is_not_held(self) -> None:
        await leases.acquire("t1")
        assert await leases.release("t1") is True

        assert await leases.thread_is_held("t1") is False

    async def test_a_silent_lease_is_not_held(self, clock: list[float]) -> None:
        """The whole point: silence ends the claim, not a sweeper's visit."""
        await leases.acquire("t1")

        _advance(clock, leases.LEASE_TTL_SECONDS + 1)

        # Nothing ran expire_scan here, so the row still says "held". The
        # reader must not trust that word -- the scan runs on a schedule, not
        # the moment an owner dies.
        assert (await leases.get_lease("t1")).state is leases.LeaseState.HELD
        assert await leases.thread_is_held("t1") is False

    async def test_it_judges_by_the_rows_own_budget(self, clock: list[float]) -> None:
        """Two rows, same instant, different budgets: both answers are right."""
        await leases.acquire("short", ttl_seconds=1.0)
        await leases.acquire("long", ttl_seconds=3600.0)

        _advance(clock, 2.0)

        assert await leases.thread_is_held("short") is False
        assert await leases.thread_is_held("long") is True

    async def test_asking_does_not_change_the_answer_it_will_give(self, clock: list[float]) -> None:
        """A reader that renews would keep a dead owner's lease alive forever."""
        await leases.acquire("t1", ttl_seconds=10.0)
        before = await leases.get_lease("t1")

        _advance(clock, 5.0)
        assert await leases.thread_is_held("t1") is True

        after = await leases.get_lease("t1")
        assert after is not None and before is not None
        assert after.heartbeat_at == before.heartbeat_at
        assert after.ttl_seconds == before.ttl_seconds
