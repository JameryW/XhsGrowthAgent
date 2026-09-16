"""Durable execution leases (P2b-S1).

Today "who is running this thread" is an in-process fact: ``_runner.py`` keeps
``_background_tasks``, and the comment above it already records the
consequence — a restart leaves DB ``running`` rows with no matching task,
detected lazily as orphans. This module starts turning that fact into one that
can be *stated*: a lease names an owner, records when it last proved it was
alive, and can therefore expire.

S1 shipped the data plane write-only, so that "who is running this thread"
became observable before anything depended on it. S2 turned the first reader
on: :func:`thread_is_held` now backs the status-derivation path -- ``/status``
and ``/list`` ask "does any live owner hold this thread" instead of "does
*this* process have a task". An expired lease still does not trigger a takeover
(S3).

Four properties this module owns:

- **The lease carries its own budget.** ``ttl_seconds`` is a column, and every
  expiry judgement reads the row's value — never the reader's default.
  Otherwise one row would be live to a reader using a long TTL and dead to a
  reader using a short one, which is the "two answers for one state" failure
  this task exists to remove.
- **One time anchor.** Expiry is ``heartbeat_at + ttl_seconds``, derived rather
  than stored, so the row cannot hold an expiry that contradicts the heartbeat
  meant to justify it.
- **The reader judges staleness, it does not read ``state``.** A row can sit
  at ``held`` long after its owner died: nothing flips a silent row to
  ``expired`` in the background, because ``expire_scan`` is the only writer of
  that state and it has no production caller. So asking "is it still
  renewable" is the question callers actually have. Do not "simplify" this to
  a state check -- that answers about the past, not the present.
- **No silent degradation.** Without Postgres the lease lives in this process
  and cannot outlive it; :func:`durability` is the single reader that says
  ``none`` there, instead of every caller inventing its own ``try/except``
  (P2b ruling 2).

Following ``db/workflow_events.py`` and
``.trellis/spec/backend/database-guidelines.md``: PostgreSQL in production and
a process-memory fallback when ``is_pool_ready()`` is false. Reads hand back a
snapshot on both paths — Postgres builds a fresh record per row, so the
fallback must not leak a reference into its own store. Writes are best-effort:
a lease describes a workflow, so a storage failure is logged and swallowed
rather than failing the workflow it describes.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from backend.db.pool import get_pool, is_pool_ready

logger = logging.getLogger("xhs_growth.db.execution_leases")

# A lease is renewed every HEARTBEAT_INTERVAL_SECONDS and expires after
# LEASE_TTL_SECONDS of silence. That is one decision, not two: the TTL is the
# interval the heartbeat budgeted for, so it is derived from the miss count
# instead of being picked independently (a hand-chosen pair drifts the moment
# one side is edited). At least two misses must fit before expiry, otherwise a
# single slow renew would make a live owner look dead.
HEARTBEAT_MISSES_BEFORE_EXPIRY = 3
LEASE_TTL_SECONDS = 90.0
HEARTBEAT_INTERVAL_SECONDS = LEASE_TTL_SECONDS / HEARTBEAT_MISSES_BEFORE_EXPIRY


class LeaseState(StrEnum):
    """Lifecycle of a lease row.

    Rows are never deleted: a released or expired lease is the record of who
    held the thread last, which is what S3 has to read before taking over.
    """

    HELD = "held"
    RELEASED = "released"
    EXPIRED = "expired"


class LeaseDurability(StrEnum):
    """What the lease store can actually promise right now."""

    DURABLE = "durable"
    NONE = "none"


@dataclass(slots=True)
class LeaseRecord:
    """One thread's lease, including the budget it is judged against."""

    thread_id: str
    owner_id: str
    owner_started_at: datetime
    acquired_at: datetime
    heartbeat_at: datetime
    ttl_seconds: float
    state: LeaseState

    def expires_at(self) -> datetime:
        """When this lease goes silent-unrenewed, derived from the heartbeat."""
        return self.heartbeat_at + timedelta(seconds=self.ttl_seconds)

    def is_stale(self, *, now: datetime) -> bool:
        """True when a held lease has gone quiet for longer than *its* budget.

        A released lease is never stale — it was handed back on purpose.
        """
        return self.state is LeaseState.HELD and self.expires_at() <= now


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _host() -> str:
    with contextlib.suppress(OSError):
        return socket.gethostname()
    return "unknown"


def _make_instance_id() -> str:
    """Identify this process: host, pid, and a random suffix.

    Host and pid are what a human reads to tell two deploys apart; the random
    suffix makes the id unique even when the OS recycles a pid.
    """
    return f"{_host()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


_instance_id = _make_instance_id()
_instance_started_at = _utcnow()

# Process-memory fallback. Shared mutable state, so reads and writes serialize
# here the way a Postgres transaction would (same reasoning as
# db/workflow_events.py).
_mem_leases: dict[str, LeaseRecord] = {}
_mem_lock = asyncio.Lock()


def _reset_memory_store() -> None:
    """Test helper for the no-Postgres fallback."""
    _mem_leases.clear()


def _snapshot(record: LeaseRecord) -> LeaseRecord:
    """Hand out a copy, so a caller cannot mutate the store through a read."""
    return dataclasses.replace(record)


def instance_identity() -> tuple[str, datetime]:
    """Return this process's ``(instance_id, started_at)``."""
    return _instance_id, _instance_started_at


def durability() -> LeaseDurability:
    """The single reader for "can a lease here outlive this process?".

    Explicit rather than silent (P2b ruling 2): without Postgres the answer is
    ``NONE``, and saying so is the difference between a degraded lease and a
    lease that only looks durable.
    """
    return LeaseDurability.DURABLE if is_pool_ready() else LeaseDurability.NONE


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS execution_leases (
    thread_id        TEXT PRIMARY KEY,
    owner_id         TEXT NOT NULL,
    owner_started_at TIMESTAMPTZ NOT NULL,
    acquired_at      TIMESTAMPTZ NOT NULL,
    heartbeat_at     TIMESTAMPTZ NOT NULL,
    ttl_seconds      DOUBLE PRECISION NOT NULL,
    state            TEXT NOT NULL
);
"""

# The expiry scan filters on (state, heartbeat_at); the index matches it so the
# scan stays a range read as rows accumulate.
_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_execution_leases_expiry
    ON execution_leases (state, heartbeat_at);
"""

# Granted when the row is new, when the current holder released or lost it, or
# when the holder went silent — refused while another owner's heartbeat is
# fresh. Note which TTL decides that: the incumbent's (execution_leases), not
# the incoming caller's. That refusal is the only place the "no two writers on
# one checkpoint" property lives (P2b red line 4); S1 ignores the answer, S3
# will not.
_ACQUIRE_SQL = """
INSERT INTO execution_leases (
    thread_id, owner_id, owner_started_at, acquired_at, heartbeat_at,
    ttl_seconds, state
) VALUES (%s, %s, %s, now(), now(), %s, 'held')
ON CONFLICT (thread_id) DO UPDATE SET
    owner_id = EXCLUDED.owner_id,
    owner_started_at = EXCLUDED.owner_started_at,
    acquired_at = EXCLUDED.acquired_at,
    heartbeat_at = EXCLUDED.heartbeat_at,
    ttl_seconds = EXCLUDED.ttl_seconds,
    state = 'held'
WHERE execution_leases.state <> 'held'
   OR execution_leases.owner_id = EXCLUDED.owner_id
   OR execution_leases.heartbeat_at
        + make_interval(secs => execution_leases.ttl_seconds) <= now()
RETURNING thread_id
"""

_RENEW_SQL = """
UPDATE execution_leases
   SET heartbeat_at = now(), ttl_seconds = %s
 WHERE thread_id = %s AND owner_id = %s AND state = 'held'
RETURNING thread_id
"""

_RELEASE_SQL = """
UPDATE execution_leases
   SET state = 'released'
 WHERE thread_id = %s AND owner_id = %s
RETURNING thread_id
"""

_EXPIRE_SQL = """
UPDATE execution_leases
   SET state = 'expired'
 WHERE state = 'held'
   AND heartbeat_at + make_interval(secs => ttl_seconds) <= now()
RETURNING thread_id
"""

_SELECT_COLUMNS = (
    "thread_id, owner_id, owner_started_at, acquired_at, heartbeat_at, ttl_seconds, state"
)

_GET_SQL = f"SELECT {_SELECT_COLUMNS} FROM execution_leases WHERE thread_id = %s"

_LIST_SQL = f"SELECT {_SELECT_COLUMNS} FROM execution_leases ORDER BY heartbeat_at ASC"

_LIST_BY_STATE_SQL = (
    f"SELECT {_SELECT_COLUMNS} FROM execution_leases WHERE state = %s ORDER BY heartbeat_at ASC"
)


async def ensure_tables() -> None:
    """Create the lease table when the app pool is ready."""
    if not is_pool_ready():
        logger.debug("execution_leases ensure skipped: pool not ready")
        return
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_TABLE_SQL)
        await conn.execute(_CREATE_INDEX_SQL)
    logger.info("execution_leases table ensured")


def _record_from_row(row: Any) -> LeaseRecord:
    return LeaseRecord(
        thread_id=row["thread_id"],
        owner_id=row["owner_id"],
        owner_started_at=row["owner_started_at"],
        acquired_at=row["acquired_at"],
        heartbeat_at=row["heartbeat_at"],
        ttl_seconds=float(row["ttl_seconds"]),
        state=LeaseState(row["state"]),
    )


def _acquire_in_memory(thread_id: str, ttl_seconds: float) -> bool:
    now = _utcnow()
    existing = _mem_leases.get(thread_id)
    # Mirrors the SQL: the incumbent's own budget decides whether it is still
    # alive. The caller's TTL is what it would apply if it won, not a verdict
    # about the holder.
    if (
        existing is not None
        and existing.owner_id != _instance_id
        and not existing.is_stale(now=now)
    ):
        return False
    _mem_leases[thread_id] = LeaseRecord(
        thread_id=thread_id,
        owner_id=_instance_id,
        owner_started_at=_instance_started_at,
        acquired_at=now,
        heartbeat_at=now,
        ttl_seconds=ttl_seconds,
        state=LeaseState.HELD,
    )
    return True


async def acquire(thread_id: str, *, ttl_seconds: float = LEASE_TTL_SECONDS) -> bool:
    """Claim the lease for this instance, returning whether it was granted.

    ``ttl_seconds`` is the budget this owner would hold it under. ``False``
    means a live lease belonging to another owner is still there and was not
    taken; both backends answer that the same way.
    """
    if not thread_id:
        return False
    if not is_pool_ready():
        async with _mem_lock:
            granted = _acquire_in_memory(thread_id, ttl_seconds)
    else:
        try:
            pool = get_pool()
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    _ACQUIRE_SQL,
                    (
                        thread_id,
                        _instance_id,
                        _instance_started_at,
                        ttl_seconds,
                    ),
                )
                granted = await cur.fetchone() is not None
        except Exception as exc:
            logger.warning("execution_leases acquire failed for %s: %s", thread_id, exc)
            return False
    if not granted:
        logger.warning("execution_leases acquire refused for %s: held by a live owner", thread_id)
    return granted


async def renew(thread_id: str, *, ttl_seconds: float = LEASE_TTL_SECONDS) -> bool:
    """Refresh this instance's lease, returning whether it still holds it.

    ``False`` is the interesting answer: the lease moved on (another owner took
    it over, or it was released) while this instance still believed it was
    running. S1 only logs it; S3 is where it must stop work.
    """
    if not thread_id:
        return False
    if not is_pool_ready():
        async with _mem_lock:
            current = _mem_leases.get(thread_id)
            if (
                current is None
                or current.state is not LeaseState.HELD
                or current.owner_id != _instance_id
            ):
                return False
            current.heartbeat_at = _utcnow()
            current.ttl_seconds = ttl_seconds
        return True
    try:
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_RENEW_SQL, (ttl_seconds, thread_id, _instance_id))
            renewed = await cur.fetchone() is not None
    except Exception as exc:
        logger.warning("execution_leases renew failed for %s: %s", thread_id, exc)
        return False
    return renewed


async def release(thread_id: str) -> bool:
    """Mark this instance's lease released.

    Another owner's lease is left alone — releasing a lease we do not hold
    would erase the record of whoever does.
    """
    if not thread_id:
        return False
    if not is_pool_ready():
        async with _mem_lock:
            current = _mem_leases.get(thread_id)
            if current is None or current.owner_id != _instance_id:
                return False
            current.state = LeaseState.RELEASED
        return True
    try:
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_RELEASE_SQL, (thread_id, _instance_id))
            released = await cur.fetchone() is not None
    except Exception as exc:
        logger.warning("execution_leases release failed for %s: %s", thread_id, exc)
        return False
    return released


async def expire_scan() -> list[str]:
    """Flip held-but-silent leases to ``expired`` and return their thread ids.

    This is the read that gives ``heartbeat_at`` its meaning: a lease expires
    because nobody renewed it, which is a fact about the owner, not about the
    process running the scan. Each row is judged against its own budget.
    """
    if not is_pool_ready():
        now = _utcnow()
        async with _mem_lock:
            expired = sorted(
                thread_id for thread_id, record in _mem_leases.items() if record.is_stale(now=now)
            )
            for thread_id in expired:
                _mem_leases[thread_id].state = LeaseState.EXPIRED
        return expired
    try:
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_EXPIRE_SQL)
            rows = await cur.fetchall()
    except Exception as exc:
        logger.warning("execution_leases expire_scan failed: %s", exc)
        return []
    return sorted(str(row[0]) for row in rows)


async def get_lease(thread_id: str) -> LeaseRecord | None:
    """Return one thread's lease, or ``None`` when it has never been leased."""
    if not thread_id:
        return None
    if not is_pool_ready():
        async with _mem_lock:
            record = _mem_leases.get(thread_id)
        return _snapshot(record) if record is not None else None
    try:
        pool = get_pool()
        from psycopg.rows import dict_row

        async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_GET_SQL, (thread_id,))
            row = await cur.fetchone()
    except Exception as exc:
        logger.warning("execution_leases get failed for %s: %s", thread_id, exc)
        return None
    return _record_from_row(row) if row else None


async def list_leases(*, state: LeaseState | None = None) -> list[LeaseRecord]:
    """Return leases in heartbeat order, optionally filtered by state."""
    if not is_pool_ready():
        async with _mem_lock:
            records = [
                _snapshot(record)
                for record in _mem_leases.values()
                if state is None or record.state is state
            ]
        return sorted(records, key=lambda record: record.heartbeat_at)
    try:
        pool = get_pool()
        from psycopg.rows import dict_row

        async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            if state is None:
                await cur.execute(_LIST_SQL)
            else:
                await cur.execute(_LIST_BY_STATE_SQL, (state.value,))
            rows = await cur.fetchall()
    except Exception as exc:
        logger.warning("execution_leases list failed: %s", exc)
        return []
    return [_record_from_row(row) for row in rows]


async def _heartbeat_until_cancelled(
    thread_id: str,
    *,
    interval_seconds: float,
    ttl_seconds: float,
) -> None:
    """Renew ``thread_id`` until cancelled or until the lease is lost."""
    while True:
        await asyncio.sleep(interval_seconds)
        if not await renew(thread_id, ttl_seconds=ttl_seconds):
            logger.warning(
                "execution_leases heartbeat stopped for %s: lease no longer held",
                thread_id,
            )
            return


async def start_lease(
    thread_id: str,
    *,
    ttl_seconds: float = LEASE_TTL_SECONDS,
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> asyncio.Task[None] | None:
    """Acquire the lease and keep renewing it in the background.

    Returns the heartbeat task for the caller to stop, or ``None`` when the
    lease was refused — S1 still runs the workflow either way, because an
    observational lease must not gate execution.
    """
    if not await acquire(thread_id, ttl_seconds=ttl_seconds):
        return None
    return asyncio.create_task(
        _heartbeat_until_cancelled(
            thread_id, interval_seconds=interval_seconds, ttl_seconds=ttl_seconds
        )
    )


async def end_lease(thread_id: str, heartbeat: asyncio.Task[None] | None) -> None:
    """Stop the heartbeat and release the lease.

    ``gather(return_exceptions=True)`` waits the heartbeat out without either
    swallowing our own cancellation or resurrecting the CancelledError it was
    cancelled with. If this call never runs — a ``kill -9`` — the lease simply
    goes silent and expires, which is the property being built rather than a
    gap in it.
    """
    if heartbeat is not None:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
    await release(thread_id)


async def thread_is_held(thread_id: str) -> bool:
    """Whether a live owner currently holds this thread.

    This is the reader ``heartbeat_at`` was built for, and the reason staleness
    is computed here instead of read off ``state``: nothing flips a silent row
    to ``expired`` in the background -- ``expire_scan`` is the only writer of
    that state and it has no production caller -- so a row can sit at ``held``
    long after its owner died. Asking "is it still renewable" is the question
    callers actually have.
    """
    if not thread_id:
        return False
    record = await get_lease(thread_id)
    if record is None:
        return False
    return record.state is LeaseState.HELD and not record.is_stale(now=_utcnow())


__all__ = [
    "HEARTBEAT_INTERVAL_SECONDS",
    "HEARTBEAT_MISSES_BEFORE_EXPIRY",
    "LEASE_TTL_SECONDS",
    "LeaseDurability",
    "LeaseRecord",
    "LeaseState",
    "acquire",
    "durability",
    "end_lease",
    "ensure_tables",
    "expire_scan",
    "get_lease",
    "instance_identity",
    "list_leases",
    "release",
    "renew",
    "start_lease",
    "thread_is_held",
]
