"""Per-account in-flight slots for the Gateway (process-local + optional PG).

Replaces the Gateway's bare ``asyncio.Semaphore`` (process-local, all accounts
shared one ceiling) with an account-keyed slot gate, so ``max_concurrency=1``
means *one in-flight call for this account* rather than *one per worker for
every account together*.

Layers — the same two-layer shape as ``backend/services/cdp_session_lock.py``:

  1. Process-local ``asyncio.Semaphore`` — fast path for single-worker
     deployments and the degraded mode when Postgres is down.
  2. PostgreSQL session-level advisory locks — counted slots (one advisory
     identity per slot: ``hashtext(f"{key}#{i}")``) so Uvicorn workers /
     multi-process hosts share one ceiling. The held connection is checked
     out for the lease duration, so a crash auto-releases the slot when the
     backend disconnects.

When Postgres is unavailable the process-local half still works (degraded:
each worker counts its own slots). The PG import is lazy, so the runtime core
keeps its "no DB dependency" posture — the distributed half is an
enhancement, not a precondition.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger("xhs_growth.tools.account_gate")

#: Namespace for two-int advisory locks. Sits next to ``cdp_session_lock``'s
#: 8910 and must stay distinct: both modules hash keys into the same global
#: advisory-lock space.
_PG_LOCK_CLASS = 8911

#: Busy-wait poll interval for the PG slot acquisition loop. Extracted so
#: tests can shrink it below the wait budget — otherwise a 0.05s budget still
#: sleeps the full 0.15s gap (the deadline check only fires after the sleep).
_BUSY_POLL_S = 0.15

#: Floor for a wait budget, mirroring ``cdp_session_lock``: a zero/negative
#: budget would race the event loop instead of deciding anything.
_MIN_WAIT_S = 0.05

_local_slots: dict[str, asyncio.Semaphore] = {}
_local_limits: dict[str, int] = {}
_local_guard = asyncio.Lock()


class AccountSlotTimeoutError(TimeoutError):
    """No slot for ``key`` became free within the wait budget.

    The call never started — nothing was sent anywhere — so callers can
    report this as a plain timeout and never fear a half-done side effect.
    """

    def __init__(self, key: str, limit: int, waited_s: float) -> None:
        self.key = key
        self.limit = limit
        self.waited_s = waited_s
        super().__init__(
            f"concurrency slot for {key!r} (limit={limit}) not acquired within {waited_s:.2f}s"
        )


class _SlotStatus(StrEnum):
    """Outcome of one PG slot probe — a status, never a measurement."""

    ACQUIRED = "acquired"
    BUSY = "busy"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class _SlotProbe:
    """Result of one ``_try_acquire_pg_slot`` attempt.

    Built through named constructors on purpose: a handler that returns a
    ``call`` is honest about where the value came from, where a handler that
    returns a bare literal is the "failure became data" shape the silent-
    fallback scan exists to catch.
    """

    status: _SlotStatus
    hold: _PgSlotHold | None = None

    @classmethod
    def acquired(cls, hold: _PgSlotHold) -> _SlotProbe:
        return cls(_SlotStatus.ACQUIRED, hold)

    @classmethod
    def busy(cls) -> _SlotProbe:
        return cls(_SlotStatus.BUSY)

    @classmethod
    def unavailable(cls) -> _SlotProbe:
        return cls(_SlotStatus.UNAVAILABLE)


class _PgSlotHold:
    """Holds a pool connection that owns one session-level advisory slot."""

    def __init__(self, conn_cm: Any, conn: Any, slot_key: str) -> None:
        self._conn_cm = conn_cm
        self._conn = conn
        self._slot_key = slot_key
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        with contextlib.suppress(Exception):
            async with self._conn.cursor() as cur:
                await cur.execute(
                    "SELECT pg_advisory_unlock(%s, hashtext(%s))",
                    (_PG_LOCK_CLASS, self._slot_key),
                )
        with contextlib.suppress(Exception):
            await self._conn_cm.__aexit__(None, None, None)


class AccountSlot:
    """One held slot for a gate key. ``release()`` returns it (idempotent)."""

    def __init__(
        self,
        *,
        key: str,
        limit: int,
        sem: asyncio.Semaphore,
        pg_hold: _PgSlotHold | None,
    ) -> None:
        self._key = key
        self._limit = limit
        self._sem = sem
        self._pg_hold = pg_hold
        self._released = False

    @property
    def key(self) -> str:
        return self._key

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def distributed(self) -> bool:
        """True when the PG half is held — not merely process-local."""
        return self._pg_hold is not None

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._pg_hold is not None:
            with contextlib.suppress(Exception):
                await self._pg_hold.release()
        self._sem.release()
        logger.debug("account slot released key=%s pg=%s", self._key, self._pg_hold is not None)


async def _get_local_slot(key: str, limit: int) -> asyncio.Semaphore:
    async with _local_guard:
        sem = _local_slots.get(key)
        if sem is None:
            sem = asyncio.Semaphore(limit)
            _local_slots[key] = sem
            _local_limits[key] = limit
            return sem
        known = _local_limits[key]
        if known != limit:
            # A silently resized ceiling is no ceiling at all: the first limit
            # wins and the mismatch would hide in a "passed" run otherwise.
            raise ValueError(
                f"slot limit for {key!r} changed: {known} -> {limit} (one key must keep one limit)"
            )
        return sem


async def _try_acquire_pg_slot(key: str, limit: int) -> _SlotProbe:
    """Try once to take any free PG slot for ``key`` (slots ``0..limit-1``).

    Returns ``acquired`` (hold is non-None), ``busy`` (every slot is taken by
    another session) or ``unavailable`` (pool down / probe failed — degrade
    to the process-local half).
    """
    try:
        from backend.db.pool import get_pool, is_pool_ready

        if not is_pool_ready():
            return _SlotProbe.unavailable()
        pool = get_pool()
        for slot_index in range(limit):
            slot_key = f"{key}#{slot_index}"
            conn_cm = pool.connection()
            conn = await conn_cm.__aenter__()
            try:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT pg_try_advisory_lock(%s, hashtext(%s))",
                        (_PG_LOCK_CLASS, slot_key),
                    )
                    row = await cur.fetchone()
                    got = bool(row and row[0])
                if got:
                    return _SlotProbe.acquired(_PgSlotHold(conn_cm, conn, slot_key))
                await conn_cm.__aexit__(None, None, None)
            except Exception:
                with contextlib.suppress(Exception):
                    await conn_cm.__aexit__(None, None, None)
                raise
        return _SlotProbe.busy()
    except Exception:
        logger.debug("account slot pg acquire failed (degrade to local)", exc_info=True)
        return _SlotProbe.unavailable()


async def _acquire_pg_with_policy(key: str, limit: int, *, deadline: float) -> _PgSlotHold | None:
    """Acquire a PG slot until ``deadline``.

    Returns:
      - ``_PgSlotHold`` when a distributed slot was acquired
      - ``None`` when the pool is unavailable (caller continues local-only)

    Raises:
      ``AccountSlotTimeoutError`` when the pool is up but every slot stays
      taken past the deadline.
    """
    started = time.monotonic()
    while True:
        probe = await _try_acquire_pg_slot(key, limit)
        if probe.status is _SlotStatus.ACQUIRED:
            return probe.hold
        if probe.status is _SlotStatus.UNAVAILABLE:
            return None
        if time.monotonic() >= deadline:
            raise AccountSlotTimeoutError(key, limit, time.monotonic() - started)
        await asyncio.sleep(_BUSY_POLL_S)


async def acquire_account_slot(*, key: str, limit: int, wait_timeout_s: float) -> AccountSlot:
    """Acquire one of ``limit`` slots for ``key``.

    Raises ``AccountSlotTimeoutError`` when the budget expires first — the
    call that wanted the slot has not started, so nothing happened anywhere.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    budget = max(_MIN_WAIT_S, float(wait_timeout_s))
    deadline = time.monotonic() + budget
    sem = await _get_local_slot(key, limit)
    try:
        await asyncio.wait_for(sem.acquire(), timeout=budget)
    except TimeoutError as exc:
        raise AccountSlotTimeoutError(key, limit, budget) from exc
    try:
        pg_hold = await _acquire_pg_with_policy(key, limit, deadline=deadline)
    except BaseException:
        # Includes cancellation: a waiter that goes away must not leak the
        # process-local slot it already took.
        sem.release()
        raise
    return AccountSlot(key=key, limit=limit, sem=sem, pg_hold=pg_hold)


@asynccontextmanager
async def hold_account_slot(
    *, key: str, limit: int, wait_timeout_s: float
) -> AsyncIterator[AccountSlot]:
    """Acquire a slot for the duration of the block; always releases."""
    slot = await acquire_account_slot(key=key, limit=limit, wait_timeout_s=wait_timeout_s)
    try:
        yield slot
    finally:
        await slot.release()


def reset_account_gates_for_tests() -> None:
    """Test helper — drop all process-local slots."""
    _local_slots.clear()
    _local_limits.clear()


__all__ = [
    "AccountSlot",
    "AccountSlotTimeoutError",
    "acquire_account_slot",
    "hold_account_slot",
    "reset_account_gates_for_tests",
]
