"""P3-S3: the creator-stats import is the producer the weak-label seam lacked.

The loop is ``publish → evaluator sample → real engagement → refit weights``.
Every piece of it existed, was wired, and had passing tests; ``maybe_evolve`` had
nevertheless never left ``below threshold``, because the only thing that fills
``evaluator_samples.engagement`` (``backfill_engagement``) was reached from
``analyst``, which reads metrics out of a publish-time ``publish_result`` — a
payload that carries identity and status only.  ``tests/unit/db/test_weak_label_contract.py``
registers that gap; this slice closes it from the other end, because a
creator-stats import *does* know the post id and its real counts.

``test_the_import_is_what_lets_the_loop_cross_the_threshold`` is the ticket's
stated entry condition — "a sample row with ``engagement`` → ``count_labeled_since``
≥ ``MIN_EVOLVE_SAMPLES`` → ``maybe_evolve`` returns ``evolved``".  It is measured
against a row store that the real writer really mutates and the real counter
really counts.  Mocking the counter instead (as the pre-existing ``maybe_evolve``
tests do, for their own reasons) would reproduce exactly the failure this ticket
exists to prevent: a mocked counter is green whether or not anything was ever
written.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.evaluator_config import (
    ENGAGEMENT_LABEL_SOURCE,
    MIN_EVOLVE_SAMPLES,
    WEAK_LABEL_METRIC_KEYS,
)
from backend.services.creator_stats.pipeline import import_bundle
from backend.services.creator_stats.types import (
    AccountStatsOverview,
    CreatorStatsBundle,
    NoteStats,
)

ACCOUNT = "acct-1"
#: ``count_labeled_since`` counts samples created *after* the active epoch, so
#: the rows below are dated after the epoch the tests hand to ``maybe_evolve``.
EPOCH_CREATED_AT = "2026-01-01T00:00:00+00:00"
SAMPLE_CREATED_AT = "2026-02-01T00:00:00+00:00"


# ── a row store, not a parameter recorder ────────────────────────────────────

#: The attach carries the label inside the SQL it runs, so the fixture reads
#: it from there rather than from an import.  A fixture that supplied the
#: expected label itself would answer *for* the production statement instead
#: of executing it: the label could vanish from the clause, or change value,
#: and the end-to-end ``labeled row -> counter -> evolved`` chain would still
#: pass -- which is precisely how this slice's own hole was found.
_LABEL_IN_SQL = re.compile(r"label_source = '([^']*)'")


class _Store:
    """A fake ``evaluator_samples`` table with just enough SQL to be counted.

    It recognises the two statements this path runs — by the table they name and
    the column they select on — and applies the UPDATE to the rows it keeps.  The
    point is that the label the import writes is the label the counter counts: a
    store that only recorded parameters would let "wrote nothing" and "wrote
    something the counter cannot see" pass alike.

    Anything it does not model raises rather than answering plausibly, so a
    statement that grows a new shape fails here instead of being silently
    answered from a stale reading of the query.

    The label it stores is parsed out of the statement for the same reason:
    the clause that decides the label is the production one, and this fixture
    must not be able to answer it correctly on its behalf.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(row) for row in rows]
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    async def run(self, sql: str, params: tuple[Any, ...]) -> tuple[int, int | None]:
        """Return ``(rowcount, single_value)`` for one statement."""
        self.statements.append((sql, params))
        if "UPDATE evaluator_samples" in sql:
            return self._attach(sql, params), None
        if "COUNT(*) FROM evaluator_samples" in sql:
            return 0, self._count(sql, params)
        raise AssertionError(f"statement the fixture does not model: {sql}")

    def _attach(self, sql: str, params: tuple[Any, ...]) -> int:
        assert "platform_post_id = %s" in sql, sql
        match = _LABEL_IN_SQL.search(sql)
        assert match is not None, f"the attach no longer writes label_source: {sql}"
        payload, platform_post_id = params
        labels = json.loads(payload)
        touched = 0
        for row in self.rows:
            if row["platform_post_id"] == platform_post_id:
                row["engagement"] = labels
                row["label_source"] = match.group(1)
                touched += 1
        return touched

    def _count(self, sql: str, params: tuple[Any, ...]) -> int:
        # Only answer the query this fixture claims to model: if the predicate
        # changes, failing loudly beats returning a number read off the wrong
        # parameters.
        assert "engagement IS NOT NULL" in sql, sql
        assert "created_at > %s" in sql, sql
        assert "account_id = %s" in sql, sql
        account_id, since = params
        return sum(
            1
            for row in self.rows
            if row["account_id"] == account_id
            and row["engagement"] is not None
            and row["created_at"] > since
        )


@asynccontextmanager
async def _ctx(value: Any):
    yield value


class _Cursor:
    """Cursor-shaped facade over the store — the shape ``count_labeled_since`` uses."""

    def __init__(self, store: _Store) -> None:
        self._store = store
        self.rowcount = 0
        self._one: tuple[Any, ...] | None = None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        rowcount, single = await self._store.run(sql, tuple(params))
        self.rowcount = rowcount
        self._one = None if single is None else (single,)

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._one


class _Conn:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Cursor:
        cursor = _Cursor(self._store)
        await cursor.execute(sql, params)
        return cursor

    def cursor(self) -> Any:
        return _ctx(_Cursor(self._store))

    def transaction(self) -> Any:
        return _ctx(None)


def _fake_pool(store: _Store) -> Any:
    @asynccontextmanager
    async def connection(*_args: Any, **_kwargs: Any):
        yield _Conn(store)

    pool = MagicMock()
    pool.connection = connection
    return pool


# ── fixtures ─────────────────────────────────────────────────────────────────


def _note(note_id: str, *, views: int = 120, likes: int = 7) -> NoteStats:
    return NoteStats(
        note_id=note_id,
        account_id=ACCOUNT,
        title=f"note {note_id}",
        views=views,
        likes=likes,
        collects=2,
        comments=1,
        shares=0,
    )


def _bundle(*notes: NoteStats) -> CreatorStatsBundle:
    return CreatorStatsBundle(
        account=AccountStatsOverview(account_id=ACCOUNT, note_count=len(notes)),
        notes=list(notes),
    )


def _sample(post_id: str, *, created_at: str = SAMPLE_CREATED_AT) -> dict[str, Any]:
    """One row as the evaluator node writes it: judged, not yet labeled."""
    return {
        "id": post_id,
        "account_id": ACCOUNT,
        "thread_id": f"xhs_{ACCOUNT}_{post_id}",
        "platform_post_id": post_id,
        "engagement": None,
        "label_source": "evaluator",
        "created_at": created_at,
    }


@asynccontextmanager
async def _sync_env(store: _Store, *, pool_ready: bool = True):
    """Everything an import needs faked, and nothing else.

    ``persist_bundle`` and the account-name refresh are stubbed because the note
    upsert has its own tests and this file is about what happens *after* it.  The
    niche resolver is stubbed because it writes through a pool this fixture does
    not model (upstream it is already best-effort).  The evolution scheduler is
    replaced by a recorder rather than left to spawn a task.
    """
    scheduled: list[str] = []
    with (
        patch(
            "backend.services.creator_stats.pipeline.persist_bundle",
            AsyncMock(return_value=(1, 0, 0)),
        ),
        patch(
            "backend.services.creator_stats.pipeline._sync_imported_account_name",
            AsyncMock(),
        ),
        patch(
            "backend.services.creator_stats.pipeline._schedule_weak_label_evolve",
            scheduled.append,
        ),
        patch(
            "backend.services.niche_resolver.resolve_account_niche",
            AsyncMock(side_effect=RuntimeError("not modelled here")),
        ),
        patch("backend.db.pool.is_pool_ready", lambda: pool_ready),
        patch("backend.db.evaluator_config.get_pool", lambda: _fake_pool(store)),
    ):
        yield scheduled


@asynccontextmanager
async def _evolve_env():
    """``maybe_evolve``'s collaborators, so only its decision is under test."""
    with (
        patch(
            "backend.db.evaluator_config.get_active_epoch",
            AsyncMock(
                return_value=MagicMock(created_at=EPOCH_CREATED_AT, bias_severity="standard")
            ),
        ),
        patch(
            "backend.db.evaluator_config.train_weights",
            AsyncMock(
                return_value=MagicMock(applied=True, n_samples=MIN_EVOLVE_SAMPLES, r_squared=0.4)
            ),
        ) as train,
        patch("backend.db.evaluator_config.avg_bias_score", AsyncMock(return_value=60.0)),
        patch("backend.db.evaluator_config.create_epoch", AsyncMock()) as epoch,
    ):
        yield train, epoch


# ── the attach ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_import_attaches_the_real_metrics_to_the_sample_that_judged_the_post():
    store = _Store([_sample("note-1")])

    async with _sync_env(store) as scheduled:
        await import_bundle(_bundle(_note("note-1")), run_creative_analysis=False)

    row = store.rows[0]
    assert row["engagement"] == {
        "views": 120,
        "likes": 7,
        "collects": 2,
        "comments": 1,
        "shares": 0,
    }
    # Tied to the contract rather than to the literal: a payload that grows or
    # renames a key has to change the declaration, not just this call site.
    assert set(row["engagement"]) == set(WEAK_LABEL_METRIC_KEYS)
    assert row["label_source"] == ENGAGEMENT_LABEL_SOURCE
    assert scheduled == [ACCOUNT]


@pytest.mark.asyncio
async def test_a_post_nobody_judged_attaches_nothing_and_asks_nothing():
    """The control for the attach: a sync with no matching sample is a no-op."""
    store = _Store([_sample("note-1")])

    async with _sync_env(store) as scheduled:
        await import_bundle(_bundle(_note("note-9")), run_creative_analysis=False)

    assert store.rows[0]["engagement"] is None
    assert store.rows[0]["label_source"] == "evaluator"
    # Nothing arrived, so there is no threshold question to ask.
    assert scheduled == []


@pytest.mark.asyncio
async def test_the_join_key_is_normalized_so_a_url_note_id_still_matches():
    """The producer side normalizes, so the key is the one the publisher stored."""
    store = _Store([_sample("note-1")])

    async with _sync_env(store):
        await import_bundle(
            _bundle(_note("https://www.xiaohongshu.com/explore/note-1")),
            run_creative_analysis=False,
        )

    assert store.rows[0]["engagement"] is not None
    assert store.statements[0][1][1] == "note-1"


@pytest.mark.asyncio
async def test_without_a_pool_the_import_does_not_touch_samples():
    store = _Store([_sample("note-1")])

    async with _sync_env(store, pool_ready=False) as scheduled:
        await import_bundle(_bundle(_note("note-1")), run_creative_analysis=False)

    assert store.statements == []
    assert scheduled == []


@pytest.mark.asyncio
async def test_a_failing_attach_does_not_fail_the_import(caplog):
    """Labels are best-effort; the notes are already durable by the time we run."""
    store = _Store([_sample("note-1")])

    async with _sync_env(store) as scheduled:
        with (
            patch(
                "backend.db.evaluator_config.backfill_engagement_for_posts",
                AsyncMock(side_effect=RuntimeError("relation does not exist")),
            ),
            caplog.at_level(logging.WARNING, logger="xhs_growth.creator_stats.pipeline"),
        ):
            result = await import_bundle(_bundle(_note("note-1")), run_creative_analysis=False)

    assert result.account_synced is True
    assert store.rows[0]["engagement"] is None
    assert scheduled == []
    assert "weak-label attach skipped" in caplog.text


# ── the ticket's entry condition ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_import_is_what_lets_the_loop_cross_the_threshold():
    """``engagement`` rows → ``count_labeled_since`` ≥ threshold → ``evolved``.

    Both ends are real: the rows are written by the production path under test and
    counted by the production ``count_labeled_since``.  Only the refit itself is
    stubbed — it is a different concern with its own tests, and it is what keeps
    the assertion about *reaching* evolution rather than about statistics.
    """
    from backend.db.evaluator_config import count_labeled_since, maybe_evolve

    post_ids = [f"note-{i}" for i in range(MIN_EVOLVE_SAMPLES)]
    store = _Store([_sample(p) for p in post_ids])

    async with _sync_env(store) as scheduled:
        before = await count_labeled_since(EPOCH_CREATED_AT, ACCOUNT)
        await import_bundle(_bundle(*(_note(p) for p in post_ids)), run_creative_analysis=False)
        after = await count_labeled_since(EPOCH_CREATED_AT, ACCOUNT)
        async with _evolve_env() as (train, epoch):
            report = await maybe_evolve(ACCOUNT)

    # The gap was never "the threshold is wrong" — it was that nothing arrived.
    assert before == 0, "the counter has to start where the registered gap says it starts"
    assert after == MIN_EVOLVE_SAMPLES
    assert report["action"] == "evolved"
    assert report["new_labeled_samples"] == MIN_EVOLVE_SAMPLES
    train.assert_awaited_once_with(ACCOUNT, apply=True)
    # Bias stayed in band, so the epoch is held — the refit is what happened.
    epoch.assert_not_awaited()
    assert scheduled == [ACCOUNT]


@pytest.mark.asyncio
async def test_one_sample_short_of_the_threshold_still_skips():
    """The control: the same write path, one row fewer, must not evolve."""
    from backend.db.evaluator_config import count_labeled_since, maybe_evolve

    post_ids = [f"note-{i}" for i in range(MIN_EVOLVE_SAMPLES - 1)]
    store = _Store([_sample(p) for p in post_ids])

    async with _sync_env(store):
        await import_bundle(_bundle(*(_note(p) for p in post_ids)), run_creative_analysis=False)
        after = await count_labeled_since(EPOCH_CREATED_AT, ACCOUNT)
        async with _evolve_env() as (train, epoch):
            report = await maybe_evolve(ACCOUNT)

    assert after == MIN_EVOLVE_SAMPLES - 1
    assert report["action"] == "skip"
    assert "below threshold" in report["reason"]
    train.assert_not_awaited()
    epoch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_sample_created_before_the_active_epoch_does_not_count():
    """The window is the *sample's* creation time, not the moment it was labeled.

    Registered rather than fixed: ``count_labeled_since`` predates this slice, and
    "which rows count toward a refit" is the write-condition question S4 owns.
    Knowing it matters here because a backfill can label an old row successfully
    and still move the counter by zero.
    """
    from backend.db.evaluator_config import count_labeled_since

    store = _Store([_sample(f"note-{i}", created_at="2025-06-01T00:00:00+00:00") for i in range(3)])

    async with _sync_env(store):
        await import_bundle(
            _bundle(*(_note(f"note-{i}") for i in range(3))), run_creative_analysis=False
        )
        counted = await count_labeled_since(EPOCH_CREATED_AT, ACCOUNT)

    assert all(row["engagement"] is not None for row in store.rows), "the label did land"
    assert counted == 0, "but it is outside the epoch window, so nothing evolves"
