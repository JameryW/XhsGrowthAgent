"""Graceful-drain state machine tests for execution leases."""

from __future__ import annotations

import asyncio

import pytest

from backend.db import execution_leases as leases
from backend.db.execution_leases import (
    AcquireOutcome,
    begin_drain,
    drain_release_all,
    end_drain,
    is_draining,
    start_drain,
    start_lease,
)


@pytest.fixture(autouse=True)
def _clean_drain_state() -> None:
    end_drain()
    yield
    end_drain()


def test_drain_flag_is_idempotent() -> None:
    assert is_draining() is False
    start_drain()
    assert is_draining() is True
    begin_drain()
    assert is_draining() is True
    end_drain()
    assert is_draining() is False


@pytest.mark.asyncio
async def test_start_lease_refuses_while_draining() -> None:
    start_drain()
    hold = await start_lease("thread-drain")
    assert hold.outcome is AcquireOutcome.DRAINING
    assert hold.heartbeat is None


@pytest.mark.asyncio
async def test_drain_release_all_with_no_owned_leases() -> None:
    start_drain()
    assert await drain_release_all() == 0


@pytest.mark.asyncio
async def test_drain_discards_a_heartbeat_from_a_closed_loop(monkeypatch) -> None:
    """A test-loop teardown must not make the next drain await a dead task.

    ``_active_heartbeats`` is process-global, while pytest gives each async test
    a fresh loop. A heartbeat left behind by an earlier test belongs to a loop
    that is already closed; draining it used to raise ``RuntimeError: Event loop
    is closed`` and leave the entry behind. It must instead be released/dropped
    without being counted as a live lease.
    """
    stale_loop = asyncio.new_event_loop()
    try:
        stale = stale_loop.create_future()
        stale.set_result(None)
    finally:
        stale_loop.close()
    monkeypatch.setitem(leases._active_heartbeats, "stale-thread", stale)

    assert await drain_release_all() == 0
    assert "stale-thread" not in leases._active_heartbeats
