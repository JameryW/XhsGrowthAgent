"""Cycle-5: engagement-rate scale consistency + invalid upsert skip."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import analytics as analytics_routes
from backend.api.routes.analytics import (
    _as_fraction_engagement_rate,
    _as_percent_engagement_rate,
    _build_growth_report,
    _extract_post_data,
    _imported_notes_as_posts,
)
from backend.db.creator_stats import (
    _reset_memory_store,
    get_account_stats,
    get_creator_stats_snapshot,
    get_note_stats,
    list_note_stats,
    upsert_account_stats,
    upsert_bundle,
    upsert_note_stats,
    upsert_notes,
)
from backend.services.creator_stats.types import AccountStatsOverview, NoteStats

from .conftest import grant_test_user


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


# ── Engagement rate scale ───────────────────────────────────────────────────


def test_as_percent_engagement_rate_converts_fraction_and_keeps_percent():
    assert _as_percent_engagement_rate(0.05) == 5.0
    assert _as_percent_engagement_rate(0.1567) == 15.67
    assert _as_percent_engagement_rate(1.0) == 100.0
    assert _as_percent_engagement_rate(5.0) == 5.0
    assert _as_percent_engagement_rate(12.5) == 12.5
    assert _as_percent_engagement_rate(-1) == 0.0
    assert _as_percent_engagement_rate(None) == 0.0


def test_as_fraction_engagement_rate_preserves_public_precision():
    assert _as_fraction_engagement_rate(0.123456) == 0.123456
    assert _as_fraction_engagement_rate(12.3456) == 0.123456
    assert _as_fraction_engagement_rate(100) == 1.0
    assert _as_fraction_engagement_rate(-1) == 0.0


def test_extract_post_data_normalizes_fraction_engagement():
    state = {
        "publish_result": {
            "status": "published",
            "post_id": "p1",
            "published_at": "2026-07-11T00:00:00+00:00",
        },
        "analytics": {
            "views": 1000,
            "likes": 50,
            "comments": 0,
            "collects": 0,
            "shares": 0,
            "engagement_rate": 0.05,
        },
        "copy_content": {"selected_title": "工作流帖"},
        "content_plan": {},
    }
    post = _extract_post_data(state)
    assert post is not None
    assert post["engagement_rate"] == 5.0


def test_extract_post_data_derives_rate_when_missing():
    state = {
        "publish_result": {"status": "published", "post_id": "p2"},
        "analytics": {"views": 200, "likes": 10, "comments": 5, "collects": 5, "shares": 0},
        "copy_content": {"selected_title": "无 rate"},
        "content_plan": {},
    }
    post = _extract_post_data(state)
    assert post is not None
    # (10+5+5)/200 = 0.1 → 10%
    assert post["engagement_rate"] == 10.0


def test_mixed_workflow_and_import_avg_uses_percent_scale():
    """Regression: workflow 0.05 + imported 0.05 must not average to ~2.5."""
    wf = _extract_post_data(
        {
            "publish_result": {
                "status": "published",
                "post_id": "wf1",
                "published_at": datetime.now(UTC).isoformat(),
            },
            "analytics": {
                "views": 100,
                "likes": 5,
                "engagement_rate": 0.05,
            },
            "copy_content": {"selected_title": "wf"},
            "content_plan": {},
        }
    )
    assert wf is not None
    imported = _imported_notes_as_posts(
        [
            NoteStats(
                note_id="imp1",
                account_id="a",
                title="imp",
                views=100,
                likes=5,
                engagement_rate=0.05,
                published_at=datetime.now(UTC).isoformat(),
            )
        ]
    )
    posts = [wf, imported[0]]
    avg = sum(p["engagement_rate"] for p in posts) / len(posts)
    assert avg == pytest.approx(5.0)
    report = _build_growth_report("a", "weekly", posts, {})
    assert report["metrics"]["avg_engagement_rate"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_dashboard_avg_rate_consistent_after_merge():
    recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    await upsert_note_stats(
        NoteStats(
            note_id="mix1",
            account_id="mix_acc",
            title="导入",
            views=1000,
            likes=50,
            comments=0,
            collects=0,
            shares=0,
            engagement_rate=0.05,
            published_at=recent,
            source="fixture",
        )
    )

    app = FastAPI()
    app.include_router(analytics_routes.router, prefix="/api/analytics")
    app.state.graph = MagicMock()
    client = TestClient(app)

    wf_state = {
        "publish_result": {
            "status": "published",
            "post_id": "wf_mix",
            "published_at": recent,
            "title": "工作流",
        },
        "analytics": {
            "views": 1000,
            "likes": 50,
            "comments": 0,
            "collects": 0,
            "shares": 0,
            "engagement_rate": 0.05,
        },
        "copy_content": {"selected_title": "工作流帖"},
        "content_plan": {},
    }

    with pytest.MonkeyPatch.context() as mp, grant_test_user(app):

        async def _wf(*_a, **_k):
            return [{"_state": wf_state, "account_id": "mix_acc"}]

        mp.setattr(analytics_routes, "_get_completed_workflows", _wf)
        resp = client.get("/api/analytics/dashboard/mix_acc?period=weekly&limit=20")

    data = resp.json()["data"]
    rates = [p["engagement_rate"] for p in data["performance"]["posts"]]
    assert rates
    assert all(r == pytest.approx(0.05) for r in rates)  # public contract is fraction
    assert data["report"]["metrics"]["avg_engagement_rate"] == pytest.approx(0.05)
    assert data["engagement_rate_unit"] == "fraction"


@pytest.mark.asyncio
async def test_bundle_persists_one_snapshot_identity_for_account_and_notes():
    account = AccountStatsOverview(
        account_id="bundle_acc",
        synced_at="2026-07-22T10:00:00Z",
        note_count=1,
    )
    note = NoteStats(
        note_id="bundle_note",
        account_id="bundle_acc",
        views=100,
        likes=5,
        engagement_rate=0.05,
        published_at="2026-07-21T10:00:00Z",
        synced_at="2026-07-22T10:00:00Z",
    )

    imported, updated, deleted = await upsert_bundle(account, [note])
    assert (imported, updated, deleted) == (1, 0, 0)
    stored = await get_account_stats("bundle_acc")
    snapshot = await get_creator_stats_snapshot("bundle_acc")

    assert stored is not None
    assert stored.snapshot_id == snapshot["snapshot_id"]
    assert stored.snapshot_id is not None


@pytest.mark.asyncio
async def test_upsert_bundle_reconciles_inflated_note_count_to_snapshot_len():
    """Persist path must not store overview note_count that outruns the notes list."""
    account = AccountStatsOverview(
        account_id="note_count_persist",
        views=3822,
        likes=108,
        fans=8,
        note_count=14,  # inflated overview alias
        synced_at="2026-07-31T00:00:00Z",
    )
    notes = [
        NoteStats(
            note_id="p1",
            account_id="note_count_persist",
            title="a",
            views=109,
            likes=9,
            synced_at="2026-07-31T00:00:00Z",
        ),
        NoteStats(
            note_id="p2",
            account_id="note_count_persist",
            title="b",
            views=22,
            likes=5,
            synced_at="2026-07-31T00:00:00Z",
        ),
        NoteStats(
            note_id="p3",
            account_id="note_count_persist",
            title="c",
            views=18,
            likes=6,
            synced_at="2026-07-31T00:00:00Z",
        ),
    ]
    imported, updated, deleted = await upsert_bundle(account, notes)
    assert (imported, updated, deleted) == (3, 0, 0)
    stored = await get_account_stats("note_count_persist")
    assert stored is not None
    assert stored.note_count == 3
    assert stored.views == 3822
    assert stored.likes == 108
    assert stored.fans == 8
    assert len(await list_note_stats("note_count_persist")) == 3


@pytest.mark.asyncio
async def test_upsert_bundle_deletes_notes_missing_from_snapshot():
    """Account-wide snapshot must drop local notes removed on Creator Center."""
    account = AccountStatsOverview(account_id="prune_acc", note_count=2, synced_at="t1")
    keep = NoteStats(
        note_id="keep",
        account_id="prune_acc",
        title="still live",
        views=10,
        likes=1,
        published_at="2026-07-20T00:00:00Z",
        synced_at="t1",
    )
    gone = NoteStats(
        note_id="gone",
        account_id="prune_acc",
        title="deleted remotely",
        views=5,
        likes=0,
        published_at="2026-07-19T00:00:00Z",
        synced_at="t1",
    )
    imported, updated, deleted = await upsert_bundle(account, [keep, gone])
    assert (imported, updated, deleted) == (2, 0, 0)
    assert {n.note_id for n in await list_note_stats("prune_acc")} == {"keep", "gone"}

    account.note_count = 1
    account.synced_at = "t2"
    keep.synced_at = "t2"
    keep.views = 20
    imported, updated, deleted = await upsert_bundle(account, [keep])
    assert imported == 0
    assert updated == 1
    assert deleted == 1
    remaining = await list_note_stats("prune_acc")
    assert len(remaining) == 1
    assert remaining[0].note_id == "keep"
    assert remaining[0].views == 20
    assert await get_note_stats("prune_acc", "gone") is None


@pytest.mark.asyncio
async def test_upsert_bundle_empty_snapshot_deletes_all_local_notes():
    account = AccountStatsOverview(account_id="empty_acc", note_count=1, synced_at="t1")
    await upsert_bundle(
        account,
        [
            NoteStats(
                note_id="only",
                account_id="empty_acc",
                title="will vanish",
                views=1,
                published_at="2026-07-18T00:00:00Z",
            )
        ],
    )
    account.note_count = 0
    imported, updated, deleted = await upsert_bundle(account, [])
    assert (imported, updated, deleted) == (0, 0, 1)
    assert await list_note_stats("empty_acc") == []
    stored = await get_account_stats("empty_acc")
    assert stored is not None
    assert stored.note_count == 0


@pytest.mark.asyncio
async def test_upsert_bundle_deduplicates_note_ids_before_counting():
    first = NoteStats(note_id="same", account_id="dedupe_acc", views=1)
    last = NoteStats(note_id="same", account_id="dedupe_acc", views=9)

    imported, updated, deleted = await upsert_bundle(
        AccountStatsOverview(account_id="dedupe_acc", note_count=2),
        [first, last],
    )

    assert (imported, updated, deleted) == (1, 0, 0)
    notes = await list_note_stats("dedupe_acc")
    assert len(notes) == 1
    assert notes[0].views == 9
    stored = await get_account_stats("dedupe_acc")
    assert stored is not None
    assert stored.note_count == 1


@pytest.mark.asyncio
async def test_upsert_bundle_does_not_delete_other_account_notes():
    a1 = AccountStatsOverview(account_id="a1", note_count=1)
    a2 = AccountStatsOverview(account_id="a2", note_count=1)
    await upsert_bundle(
        a1,
        [NoteStats(note_id="n1", account_id="a1", title="a1 note", views=1)],
    )
    await upsert_bundle(
        a2,
        [NoteStats(note_id="n2", account_id="a2", title="a2 note", views=1)],
    )
    # Re-sync a1 with empty notes — only a1 should be pruned.
    imported, updated, deleted = await upsert_bundle(a1, [])
    assert deleted == 1
    assert await list_note_stats("a1") == []
    other = await list_note_stats("a2")
    assert len(other) == 1
    assert other[0].note_id == "n2"


# ── Invalid upsert skip ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_skips_blank_account_and_note_ids():
    await upsert_account_stats(AccountStatsOverview(account_id="", views=1))
    assert await get_account_stats("") is None

    assert await upsert_note_stats(NoteStats(note_id="x", account_id="", views=1)) is False
    assert await get_note_stats("", "x") is None

    assert await upsert_note_stats(NoteStats(note_id="  ", account_id="a", views=1)) is False
    assert await list_note_stats("a") == []

    imported, updated = await upsert_notes(
        [
            NoteStats(note_id="", account_id="a", views=1),
            NoteStats(note_id="ok", account_id="a", title="good", views=3, likes=1),
            NoteStats(note_id="ok2", account_id="", views=1),
        ]
    )
    assert imported == 1
    assert updated == 0
    notes = await list_note_stats("a")
    assert len(notes) == 1
    assert notes[0].note_id == "ok"
    assert notes[0].views == 3


# ── Postgres path: batched upsert (N+1 collapse) ────────────────────────────


def _make_mock_pool(conn: MagicMock) -> MagicMock:
    pool = MagicMock()

    @asynccontextmanager
    async def connection_context():
        yield conn

    pool.connection = connection_context
    return pool


def _make_mock_conn(cursor: AsyncMock, *, transactional: bool = False) -> MagicMock:
    conn = MagicMock()

    @asynccontextmanager
    async def cursor_context():
        yield cursor

    conn.cursor = cursor_context
    conn.execute = AsyncMock()
    if transactional:
        tx = MagicMock()

        @asynccontextmanager
        async def transaction_context():
            yield tx

        conn.transaction = transaction_context
    return conn


@pytest.mark.asyncio
async def test_upsert_notes_batches_pg_path():
    """PG path issues one batched SELECT + one executemany, not 2N executes."""
    cursor = AsyncMock()
    cursor.fetchall.return_value = []  # no existing rows → all imported
    conn = _make_mock_conn(cursor)
    pool = _make_mock_pool(conn)

    notes = [NoteStats(note_id=f"n{i}", account_id="acc", title=f"t{i}", views=i) for i in range(3)]

    with (
        patch("backend.db.creator_stats.is_pool_ready", return_value=True),
        patch("backend.db.creator_stats.get_pool", return_value=pool),
    ):
        imported, updated = await upsert_notes(notes)

    # One batched existence SELECT, not one per note.
    assert cursor.execute.call_count == 1
    # One executemany carrying all 3 rows — not 3 separate upsert executes.
    assert cursor.executemany.call_count == 1
    executemany_args, _ = cursor.executemany.call_args
    assert len(executemany_args[1]) == 3
    # The per-note conn.execute upsert path must be gone.
    assert conn.execute.call_count == 0
    assert (imported, updated) == (3, 0)


@pytest.mark.asyncio
async def test_upsert_notes_pg_path_counts_mixed():
    """Count semantics: pre-existing note_ids count as updated, rest imported."""
    cursor = AsyncMock()
    cursor.fetchall.return_value = [("acc", "n1")]  # n1 already exists
    conn = _make_mock_conn(cursor)
    pool = _make_mock_pool(conn)

    notes = [
        NoteStats(note_id="n1", account_id="acc", views=1),
        NoteStats(note_id="n2", account_id="acc", views=2),
        NoteStats(note_id="n3", account_id="acc", views=3),
    ]

    with (
        patch("backend.db.creator_stats.is_pool_ready", return_value=True),
        patch("backend.db.creator_stats.get_pool", return_value=pool),
    ):
        imported, updated = await upsert_notes(notes)

    assert cursor.executemany.call_count == 1
    assert len(cursor.executemany.call_args[0][1]) == 3
    assert (imported, updated) == (2, 1)


@pytest.mark.asyncio
async def test_upsert_notes_pg_path_multi_account_single_select():
    """Multi-account import issues ONE existence SELECT (not one per account)
    and keeps counts account-scoped when a note_id recurs across accounts.

    PK is (account_id, note_id): note_id "shared" exists for acc-a but not
    acc-b. The single cross-account SELECT returns the (account_id, note_id)
    pair, so acc-b's "shared" counts as imported — proving the batched query
    did not leak acc-a's existence into acc-b (the regression a bare-note_id
    set would reintroduce).
    """
    cursor = AsyncMock()
    # acc-a/n1 exists; acc-a/"shared" exists; acc-b has nothing pre-existing.
    cursor.fetchall.return_value = [("acc-a", "n1"), ("acc-a", "shared")]
    conn = _make_mock_conn(cursor)
    pool = _make_mock_pool(conn)

    notes = [
        NoteStats(note_id="n1", account_id="acc-a", views=1),
        NoteStats(note_id="shared", account_id="acc-a", views=1),  # exists for acc-a
        NoteStats(note_id="shared", account_id="acc-b", views=1),  # NEW for acc-b
        NoteStats(note_id="n2", account_id="acc-b", views=1),
    ]

    with (
        patch("backend.db.creator_stats.is_pool_ready", return_value=True),
        patch("backend.db.creator_stats.get_pool", return_value=pool),
    ):
        imported, updated = await upsert_notes(notes)

    # One cross-account existence SELECT — not one per account.
    assert cursor.execute.call_count == 1
    assert cursor.executemany.call_count == 1
    assert len(cursor.executemany.call_args[0][1]) == 4
    # acc-a: n1 + shared updated (2); acc-b: shared + n2 imported (2).
    assert (imported, updated) == (2, 2)
    """upsert_bundle batches the note upsert inside its existing transaction."""
    cursor = AsyncMock()
    cursor.fetchall.return_value = []
    cursor.rowcount = 0  # _delete_stale_notes_on_conn deletes nothing
    conn = _make_mock_conn(cursor, transactional=True)
    pool = _make_mock_pool(conn)

    account = AccountStatsOverview(account_id="bacc", note_count=2, synced_at="t1")
    notes = [
        NoteStats(note_id="bn1", account_id="bacc", views=1),
        NoteStats(note_id="bn2", account_id="bacc", views=2),
    ]

    with (
        patch("backend.db.creator_stats.is_pool_ready", return_value=True),
        patch("backend.db.creator_stats.get_pool", return_value=pool),
    ):
        imported, updated, deleted = await upsert_bundle(account, notes)

    # Account upsert is a single conn.execute; the note batch is one executemany.
    assert conn.execute.call_count == 1
    assert cursor.executemany.call_count == 1
    assert len(cursor.executemany.call_args[0][1]) == 2
    # Existence SELECT (1) + stale-notes DELETE (1) on the shared cursor.
    assert cursor.execute.call_count == 2
    assert (imported, updated, deleted) == (2, 0, 0)
