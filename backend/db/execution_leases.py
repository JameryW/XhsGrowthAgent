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
*this* process have a task". S3 turned the lease into a cause: the takeover
scan (``api/routes/_takeover.py``) expires silent leases and resumes the
threads behind them, while an owner that loses its lease stands down
(``_runner._fence_on_lost_lease``) so that taking one over cannot produce the
two writers this task forbids.

Five properties this module owns:

- **The lease carries its own budget.** ``ttl_seconds`` is a column, and every
  expiry judgement reads the row's value — never the reader's default.
  Otherwise one row would be live to a reader using a long TTL and dead to a
  reader using a short one, which is the "two answers for one state" failure
  this task exists to remove.
- **One time anchor.** Expiry is ``heartbeat_at + ttl_seconds``, derived rather
  than stored, so the row cannot hold an expiry that contradicts the heartbeat
  meant to justify it.
- **The reader judges staleness, it does not read ``state``.** A row can sit
  at ``held`` long after its owner died: ``expire_scan`` is the only writer of
  ``expired``, and it runs on the takeover schedule -- periodic, not prompt.
  So asking "is it still renewable" is the question callers actually have. Do
  not "simplify" this to a state check -- that answers about the past, not the
  present.
- **Losing the lease stops the work it described.** A lease excludes other
  owners only if the old owner stands down, so the heartbeat's failure path
  cancels the run it was guarding (``_runner._fence_on_lost_lease``). Without
  that half, a takeover would be a route to the two concurrent writers above.
- **No silent degradation.** Without Postgres the lease lives in this process
  and cannot outlive it; :func:`durability` is the single reader that says
  ``none`` there, instead of every caller inventing its own ``try/except``
  (P2b ruling 2).
- **A refusal says which refusal.** :func:`acquire_outcome` answers GRANTED,
  HELD_BY_LIVE_OWNER or UNKNOWN, and the three are different answers rather
  than three spellings of ``False``: the middle one is evidence about the row,
  the last is the absence of evidence, and callers act on them differently --
  one is a gate, the other is not.

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

# The owner stops itself after this many *consecutive* misses, derived from the
# same budget for the same reason the TTL is: the two are one decision. The row
# only becomes acquirable once it is stale (_ACQUIRE_SQL's last OR-term), i.e. a
# whole TTL after the last successful renew, so the last stop that still lands
# in time is the one attempted M - 1 intervals after that renew -- and landing
# in time has to pay for detecting the miss at all, since a failed renew had to
# run before it could be counted. One full interval pays for that, which leaves
# M - 2. It is deliberately not the scanner's M - 1: matching the two numbers
# would put the owner's stop exactly on the instant its own row expires.
HEARTBEAT_TRANSIENT_FAILURES_TOLERATED = HEARTBEAT_MISSES_BEFORE_EXPIRY - 2


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


class AcquireOutcome(StrEnum):
    """What the store said when asked to grant the lease.

    A ``bool`` answered this question until now, and it carried three different
    meanings: granted, a live foreign owner refused it, and the store could not
    be asked at all. The three are not interchangeable to callers -- the second
    is a fact about the row, the third is the absence of one, and a caller about
    to write a checkpoint has to act differently on them.
    """

    #: The row is now this instance's.
    GRANTED = "granted"
    #: A foreign owner's heartbeat is inside its own budget. Someone else is
    #: writing this thread; a caller about to write must stand down.
    HELD_BY_LIVE_OWNER = "held_by_live_owner"
    #: The store could not be asked, or the question was empty. Nothing is
    #: known about the row -- which is not the same as knowing it is free.
    UNKNOWN = "unknown"


class RenewOutcome(StrEnum):
    """What the store said when asked whether this instance still holds it.

    The mirror of :class:`AcquireOutcome`, and the same collapse undone: a
    ``bool`` answered this too, and ``False`` carried both "the row stopped
    being ours" and "the store could not be asked".  Both stop the run -- but
    at different prices, which is what the split bought: ``LOST`` on the first
    one, ``UNKNOWN`` only after ``HEARTBEAT_TRANSIENT_FAILURES_TOLERATED``
    consecutive misses.  The safe direction here is the *opposite* of
    ``acquire``'s, because the two questions carry different risks.  A run
    that starts without a lease risks doing nothing; a run that keeps writing
    without one risks two writers on one checkpoint (red line 4) -- so the
    budget is derived to expire before the row can be taken, never chosen to
    taste.  The log can also now say which one it was, instead of recording a
    storage failure as a takeover.
    """

    #: The row is still this instance's, and its heartbeat anchor moved.
    RENEWED = "renewed"
    #: The row is no longer ours: another owner's, released, or gone.  This is
    #: evidence, and the run it guards has to stop before its next write.
    LOST = "lost"
    #: The store could not be asked, or the question was empty.  Nothing is
    #: known about the row -- which is not the same as knowing we lost it.
    UNKNOWN = "unknown"


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


@dataclass(frozen=True, slots=True)
class LeaseHold:
    """The answer :func:`start_lease` gives: which outcome, and its heartbeat.

    A tuple would carry the same two values and lose the one thing a caller
    needs at 3am: which is which. ``heartbeat`` is ``None`` unless the outcome
    is GRANTED -- there is nothing to renew when the row was not taken -- so
    the pair is not free to vary and is worth naming. Its task result is the
    :class:`RenewOutcome` the loop stopped on, which is how the fence learns
    which non-answer ended it.
    """

    outcome: AcquireOutcome
    heartbeat: asyncio.Task[RenewOutcome] | None


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
# one checkpoint" property lives (P2b red line 4) -- implemented once per
# backend, so the two must answer alike. S1 ignored it; the takeover scan is
# its first consumer, and it treats every non-grant as final. The reason a grant
# was refused is now a value (``AcquireOutcome``) rather than a bare ``False``:
# callers that must tell "someone else has it" from "we cannot ask" read it
# instead of re-deriving it from this WHERE clause.
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


def _acquire_in_memory(thread_id: str, ttl_seconds: float) -> AcquireOutcome:
    now = _utcnow()
    existing = _mem_leases.get(thread_id)
    # Mirrors the SQL, including the clause that is easy to miss: only a
    # *held* row can be a live owner. ``is_stale`` answers "held and expired",
    # so ``not is_stale`` is also True for an expired or released row -- and
    # refusing those would deny a takeover the SQL grants, leaving the two
    # backends answering the same question differently. The caller's TTL is
    # what it would apply if it won, not a verdict about the holder.
    #
    # The three conditions below *are* the definition of HELD_BY_LIVE_OWNER: a
    # held row, a foreign owner, a heartbeat inside its own budget. The SQL
    # backend reaches the same three through ``_ACQUIRE_SQL``'s WHERE. This
    # backend cannot answer UNKNOWN -- it cannot fail -- and that asymmetry is
    # what naming the outcomes removes.
    if (
        existing is not None
        and existing.state is LeaseState.HELD
        and existing.owner_id != _instance_id
        and not existing.is_stale(now=now)
    ):
        return AcquireOutcome.HELD_BY_LIVE_OWNER
    _mem_leases[thread_id] = LeaseRecord(
        thread_id=thread_id,
        owner_id=_instance_id,
        owner_started_at=_instance_started_at,
        acquired_at=now,
        heartbeat_at=now,
        ttl_seconds=ttl_seconds,
        state=LeaseState.HELD,
    )
    return AcquireOutcome.GRANTED


async def acquire_outcome(
    thread_id: str, *, ttl_seconds: float = LEASE_TTL_SECONDS
) -> AcquireOutcome:
    """Claim the lease, and say *which* no when it is refused.

    The three answers are evidence, not three spellings of "no":

    - :attr:`AcquireOutcome.GRANTED` -- the row is now this instance's.
    - :attr:`AcquireOutcome.HELD_BY_LIVE_OWNER` -- a fresh foreign heartbeat.
      Another instance is writing this thread, so a caller about to write the
      same checkpoint has to stand down. Both backends agree on this one, and
      it is the only value the takeover scan and the repair paths treat as
      final.
    - :attr:`AcquireOutcome.UNKNOWN` -- the store could not be asked. Ruling 2
      covers it: keep going, because failing closed whenever storage is
      unreachable is how a lease stops being observational.

    An empty ``thread_id`` is filed under UNKNOWN rather than given a fourth
    member. It is a programming-error guard, no caller can act on it, and a
    distinct value would invite a branch on a case that must not happen. It
    behaves exactly as it did when this returned a bare ``False``.
    """
    if not thread_id:
        return AcquireOutcome.UNKNOWN
    if not is_pool_ready():
        async with _mem_lock:
            return _acquire_in_memory(thread_id, ttl_seconds)
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
        return AcquireOutcome.UNKNOWN
    if granted:
        return AcquireOutcome.GRANTED
    logger.warning("execution_leases acquire refused for %s: held by a live owner", thread_id)
    return AcquireOutcome.HELD_BY_LIVE_OWNER


async def acquire(thread_id: str, *, ttl_seconds: float = LEASE_TTL_SECONDS) -> bool:
    """Whether this instance now holds the lease -- the boolean projection.

    :func:`acquire_outcome` is where the answer is decided; this is one
    comparison over it, not a second copy of the decision. Callers that act
    differently on the two ways of being refused ask for the outcome instead.
    """
    return await acquire_outcome(thread_id, ttl_seconds=ttl_seconds) is AcquireOutcome.GRANTED


async def renew_outcome(thread_id: str, *, ttl_seconds: float = LEASE_TTL_SECONDS) -> RenewOutcome:
    """Refresh this instance's lease, and say which answer the store gave.

    Same shape as :func:`acquire_outcome`, and for the same reason: the three
    answers are not interchangeable to the caller. ``LOST`` is a fact about the
    row; ``UNKNOWN`` is the absence of one, and the two arriving as a single
    ``False`` is what let a storage failure be read as a takeover.

    Both are still stop signals (:func:`renew` projects them to ``False``),
    because red line 4 -- one writer per checkpoint -- is not something a
    heartbeat may gamble on. What the name buys is that the two can be priced
    separately: ``LOST`` stops on the first one, while ``UNKNOWN`` gets
    ``HEARTBEAT_TRANSIENT_FAILURES_TOLERATED`` consecutive misses first.
    Neither price is picked by hand -- both are derived from the budget this
    module already derives its TTL from, so the worst case is a stop attempted
    a whole interval before the row becomes acquirable.

    An empty ``thread_id`` answers UNKNOWN rather than a fourth member: it is a
    caller bug, not a store answer, and it must not be a value a caller learns
    to branch on.
    """
    if not thread_id:
        return RenewOutcome.UNKNOWN
    if not is_pool_ready():
        async with _mem_lock:
            return _renew_in_memory(thread_id, ttl_seconds=ttl_seconds)
    try:
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_RENEW_SQL, (ttl_seconds, thread_id, _instance_id))
            renewed = await cur.fetchone() is not None
    except Exception as exc:
        logger.warning("execution_leases renew failed for %s: %s", thread_id, exc)
        return RenewOutcome.UNKNOWN
    return RenewOutcome.RENEWED if renewed else RenewOutcome.LOST


def _renew_in_memory(thread_id: str, *, ttl_seconds: float) -> RenewOutcome:
    """The no-Postgres branch, split out so the memory backend's *set* is readable.

    Called only from :func:`renew_outcome` and only while it holds ``_mem_lock``,
    the same way :func:`_acquire_in_memory` is called. It cannot fail, so it has
    no ``UNKNOWN`` -- the asymmetry the two backends share, and the reason both
    branches are named functions instead of inline blocks: a test can read the
    verbs out of one.
    """
    current = _mem_leases.get(thread_id)
    if current is None or current.state is not LeaseState.HELD or current.owner_id != _instance_id:
        return RenewOutcome.LOST
    current.heartbeat_at = _utcnow()
    current.ttl_seconds = ttl_seconds
    return RenewOutcome.RENEWED


async def renew(thread_id: str, *, ttl_seconds: float = LEASE_TTL_SECONDS) -> bool:
    """Whether this instance still holds the lease -- the boolean projection.

    :func:`renew_outcome` is where the answer is decided; this is one comparison
    over it, not a second copy of the decision. Both non-answers collapse to
    ``False`` here, and that collapse is the current ruling rather than an
    accident (see :class:`RenewOutcome`): the caller that asks this question --
    ``_runner._fence_on_lost_lease`` -- has to stop the run on either. Callers
    that need to tell them apart, or to record which one happened, ask for the
    outcome instead.
    """
    return await renew_outcome(thread_id, ttl_seconds=ttl_seconds) is RenewOutcome.RENEWED


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
) -> RenewOutcome:
    """Renew ``thread_id`` until cancelled or until an answer other than RENEWED.

    The non-answer is returned rather than merely logged, because it is the only
    place it exists: ``_runner._fence_on_lost_lease`` decides from *how this task
    ended*, and a task that returns carries ``.result()``. So the reason travels
    on the object that already crosses that boundary, and the fence can say which
    one it was instead of inferring a takeover from a stop.

    Three answers, three rows, and the rows are the ruling: ``RENEWED`` resets the
    count, ``LOST`` stops at once, ``UNKNOWN`` stops once it has missed
    ``HEARTBEAT_TRANSIENT_FAILURES_TOLERATED`` times *in a row*. See
    :class:`RenewOutcome` for why the two non-answers are priced differently, and
    :data:`HEARTBEAT_TRANSIENT_FAILURES_TOLERATED` for why the price is derived
    rather than chosen.
    """
    misses = 0
    while True:
        await asyncio.sleep(interval_seconds)
        outcome = await renew_outcome(thread_id, ttl_seconds=ttl_seconds)
        if outcome is RenewOutcome.RENEWED:
            # A successful renew moves heartbeat_at, which is the anchor the row
            # goes stale against -- so it resets the count. A cumulative count
            # would drift away from the clock the budget is measured against.
            misses = 0
            continue
        if outcome is RenewOutcome.LOST:
            # Evidence about the row rather than silence, and decided *before* the
            # budget is consulted, so widening it can never cover this one.
            logger.warning(
                "execution_leases heartbeat stopped for %s: another owner holds the row",
                thread_id,
            )
            return outcome
        misses += 1
        if misses > HEARTBEAT_TRANSIENT_FAILURES_TOLERATED:
            logger.warning(
                "execution_leases heartbeat stopped for %s: the store could not be asked",
                thread_id,
            )
            return outcome
        # A tolerated miss gets its own line: without it, "it hiccuped and kept
        # going" and "nothing happened" are the same in the log.
        logger.warning(
            "execution_leases heartbeat could not ask for %s: miss %d of %d tolerated",
            thread_id,
            misses,
            HEARTBEAT_TRANSIENT_FAILURES_TOLERATED,
        )


async def start_lease(
    thread_id: str,
    *,
    ttl_seconds: float = LEASE_TTL_SECONDS,
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> LeaseHold:
    """Acquire the lease and keep renewing it in the background.

    Returns a :class:`LeaseHold`: the outcome, and the heartbeat task for the
    caller to stop when it was GRANTED. The outcome travels with the answer
    rather than being asked for again -- it is decided here by
    :func:`acquire_outcome`, and a caller that re-read the store would be asking
    a different question at a later time.

    GRANTED and UNKNOWN are deliberately not a gate (P2b ruling 2): the runner
    executes either way, because failing closed whenever the store cannot reply
    is how a lease stops being observational. HELD_BY_LIVE_OWNER is not in that
    set -- it is evidence about the row rather than the absence of evidence --
    so the caller decides. The repair paths stand down; the takeover scan
    refuses. ``_runner._execution_lease`` carries the accounting for all three.
    """
    outcome = await acquire_outcome(thread_id, ttl_seconds=ttl_seconds)
    if outcome is not AcquireOutcome.GRANTED:
        return LeaseHold(outcome=outcome, heartbeat=None)
    return LeaseHold(
        outcome=outcome,
        heartbeat=asyncio.create_task(
            _heartbeat_until_cancelled(
                thread_id, interval_seconds=interval_seconds, ttl_seconds=ttl_seconds
            )
        ),
    )


async def end_lease(thread_id: str, heartbeat: asyncio.Task[RenewOutcome] | None) -> None:
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
    is computed here instead of read off ``state``: ``state`` lags the heartbeat.
    ``expire_scan`` is the only writer of ``expired`` and it runs on the takeover
    schedule (``api/routes/_takeover.py``) -- one pass at startup, then every
    ``takeover_interval_seconds``, 60s by default, against a 90s TTL. So between
    an owner's death and the sweep that flips its row, ``state`` still says
    ``held``, and reading it would answer about the past. Asking "is it still
    renewable" is the question callers actually have.
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
    "HEARTBEAT_TRANSIENT_FAILURES_TOLERATED",
    "LEASE_TTL_SECONDS",
    "AcquireOutcome",
    "LeaseDurability",
    "LeaseHold",
    "LeaseRecord",
    "LeaseState",
    "RenewOutcome",
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
    "renew_outcome",
    "start_lease",
    "thread_is_held",
]
