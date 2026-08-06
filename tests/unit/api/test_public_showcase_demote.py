"""Concurrency + correctness tests for `_demote_orphaned_public_rows`.

The function demotes orphaned public showcase rows (rows whose account was
deleted) to private. Each row's demotion is an independent DB write with its
own try/except, so the gather-parallel idiom (matching `_backfill` at the
same module) applies: N serial DB writes collapse to 1 concurrent wave, with
per-row exception isolation preserved by a `_demote_one` wrapper.

These tests assert the concurrency property non-vacuously (patch
`asyncio.gather` and assert it is called once with N awaitables) — a revert
to the serial for-loop would call no gather and fail.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routes.public_showcase import _demote_orphaned_public_rows
from backend.db.workflows import WorkflowRow


def _row(
    thread_id: str,
    *,
    account_id: str = "live-account",
    visibility: str = "public",
    featured: bool = False,
    featured_rank: int | None = None,
) -> WorkflowRow:
    return WorkflowRow(
        thread_id=thread_id,
        account_id=account_id,
        status="completed",
        phase="completed",
        label="公开案例标题",
        workflow_mode="trend",
        showcase_visibility=visibility,
        showcase_featured=featured,
        featured_rank=featured_rank,
        created_at="2026-07-16T10:00:00Z",
        updated_at="2026-07-16T10:00:00Z",
    )


@pytest.mark.asyncio
async def test_gather_demotes_orphaned_public_rows_concurrently():
    """N orphaned-public rows → asyncio.gather called once with N awaitables.

    Revert-then-fail proof: the old serial for-loop never calls gather, so
    this assertion fails if the parallel idiom is removed.
    """
    live = _row("live-thread")
    orphans = [
        _row(f"orphan-{i}-thread", account_id=f"deleted-{i}", featured=True, featured_rank=i)
        for i in range(3)
    ]
    rows = [live, *orphans]

    def fake_gather(*awaitables):
        # Drive each awaitable so per-row mutation + db_update still run.
        async def _run() -> list:
            results = []
            for aw in awaitables:
                results.append(await aw)
            return results

        return _run()

    with (
        patch(
            "backend.api.routes.public_showcase._existing_account_ids",
            new_callable=AsyncMock,
            return_value={live.account_id},
        ),
        patch(
            "backend.api.routes.public_showcase.db_update",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ) as db_update_mock,
        patch(
            "backend.api.routes.public_showcase.asyncio.gather",
            side_effect=fake_gather,
        ) as gather_mock,
    ):
        kept = await _demote_orphaned_public_rows(rows)

    # Concurrency: one gather wave sized to the orphaned-public subset.
    # (gather is called once — `await asyncio.gather(...)` — with N awaitables.)
    assert gather_mock.call_count == 1
    gathered = gather_mock.call_args.args
    assert len(gathered) == len(orphans)

    # Correctness: kept = account-exists rows only; orphans demoted to private.
    assert kept == [live]
    assert db_update_mock.await_count == len(orphans)
    for orphan in orphans:
        assert orphan.showcase_visibility == "private"
        assert orphan.showcase_featured is False
        assert orphan.featured_rank is None


@pytest.mark.asyncio
async def test_kept_excludes_orphans_and_orphaned_non_public_rows_not_demoted():
    """Orphaned-non-public rows are skipped (not kept, not demoted); orphans never kept."""
    live = _row("live-thread", visibility="public")
    orphan_public = _row("orphan-public", account_id="deleted-1", visibility="public")
    orphan_unlisted = _row("orphan-unlisted", account_id="deleted-2", visibility="unlisted")
    orphan_private = _row("orphan-private", account_id="deleted-3", visibility="private")

    with (
        patch(
            "backend.api.routes.public_showcase._existing_account_ids",
            new_callable=AsyncMock,
            return_value={live.account_id},
        ),
        patch(
            "backend.api.routes.public_showcase.db_update",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ) as db_update_mock,
    ):
        kept = await _demote_orphaned_public_rows(
            [live, orphan_public, orphan_unlisted, orphan_private]
        )

    assert kept == [live]
    # public + unlisted are demoted (both in _PUBLIC_VISIBILITIES); private is not.
    assert db_update_mock.await_count == 2
    demoted_ids = {call.args[0] for call in db_update_mock.await_args_list}
    assert demoted_ids == {orphan_public.thread_id, orphan_unlisted.thread_id}
    # Orphaned-private row left untouched (not in kept, not demoted).
    assert orphan_private.showcase_visibility == "private"
    assert orphan_public.showcase_visibility == "private"
    assert orphan_unlisted.showcase_visibility == "private"


@pytest.mark.asyncio
async def test_empty_existing_set_demotes_all_public_rows():
    """Empty existing set → all public rows orphaned → all demoted (fail-open preserved)."""
    rows = [
        _row("public-1", account_id="acc-1", visibility="public"),
        _row("public-2", account_id="acc-2", visibility="unlisted", featured=True),
        _row("private-1", account_id="acc-3", visibility="private"),
    ]

    with (
        patch(
            "backend.api.routes.public_showcase._existing_account_ids",
            new_callable=AsyncMock,
            return_value=set(),
        ),
        patch(
            "backend.api.routes.public_showcase.db_update",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ) as db_update_mock,
    ):
        kept = await _demote_orphaned_public_rows(rows)

    assert kept == []
    assert db_update_mock.await_count == 2  # public + unlisted, not private


@pytest.mark.asyncio
async def test_per_row_failure_does_not_abort_other_demotions():
    """One db_update raising → others still demoted, warning logged, returns normally."""
    good_orphan = _row("orphan-good", account_id="deleted-1", visibility="public")
    bad_orphan = _row("orphan-bad", account_id="deleted-2", visibility="public", featured=True)
    live = _row("live-thread")

    call_count = 0

    async def db_update_side_effect(thread_id, **fields):
        nonlocal call_count
        call_count += 1
        if thread_id == bad_orphan.thread_id:
            raise RuntimeError("db write failed for this row")
        return MagicMock()

    with (
        patch(
            "backend.api.routes.public_showcase._existing_account_ids",
            new_callable=AsyncMock,
            return_value={live.account_id},
        ),
        patch(
            "backend.api.routes.public_showcase.db_update",
            side_effect=db_update_side_effect,
        ),
    ):
        kept = await _demote_orphaned_public_rows([live, good_orphan, bad_orphan])

    # Live row kept; both orphans attempted (bad one's failure isolated).
    assert kept == [live]
    assert call_count == 2
    # Good orphan mutated to private; bad orphan left as-is (mutation is after db_update).
    assert good_orphan.showcase_visibility == "private"
    assert good_orphan.showcase_featured is False
    assert good_orphan.featured_rank is None
    # bad_orphan still public — db_update raised before the mutation lines.
    assert bad_orphan.showcase_visibility == "public"


@pytest.mark.asyncio
async def test_empty_rows_short_circuits_without_account_lookup():
    """Empty input → return early, no DB/account lookup work."""
    with (
        patch(
            "backend.api.routes.public_showcase._existing_account_ids",
            new_callable=AsyncMock,
        ) as existing_mock,
        patch(
            "backend.api.routes.public_showcase.db_update",
            new_callable=AsyncMock,
        ) as db_update_mock,
    ):
        kept = await _demote_orphaned_public_rows([])

    assert kept == []
    existing_mock.assert_not_awaited()
    db_update_mock.assert_not_awaited()
