"""Graceful-drain state machine tests for execution leases."""

from __future__ import annotations

import pytest

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
