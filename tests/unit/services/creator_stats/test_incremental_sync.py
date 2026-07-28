"""Incremental-sync filters and crawl pacing tests.

The CDP crawl re-visits every note page by default.  Incremental sync compares
the posted-list payload against persisted rows and only visits notes that are
new, recent, or changed — and never re-scrapes a stored caption.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.db.creator_stats import _reset_memory_store
from backend.services.creator_stats import pipeline
from backend.services.creator_stats.normalize import normalize_bundle
from backend.services.creator_stats.pipeline import (
    _build_incremental_filters,
    _load_note_sync_state,
    import_bundle,
    sync_from_creator_center,
)
from backend.services.creator_stats.types import NoteStats, SyncResult

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


def _iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _list_note(note_id: str, *, days_ago: float, views: int = 100) -> dict:
    return {
        "note_id": note_id,
        "display_title": f"标题{note_id}",
        "view_count": views,
        "like_count": 10,
        "comment_count": 2,
        "collect_count": 3,
        "time": _iso(days_ago),
    }


def _stored(note_id: str, *, days_ago: float, views: int = 100, body: str = "") -> NoteStats:
    return NoteStats(
        note_id=note_id,
        account_id="acct",
        views=views,
        likes=10,
        comments=2,
        collects=3,
        body_text=body,
        published_at=_iso(days_ago),
    )


# ── Filter semantics ─────────────────────────────────────────────────────────


async def test_filters_skip_unchanged_old_note():
    existing = {"n1": _stored("n1", days_ago=60, body="已有正文")}
    detail_filter, body_filter = _build_incremental_filters(existing)

    assert detail_filter(_list_note("n1", days_ago=60)) is False
    assert body_filter(_list_note("n1", days_ago=60)) is False


async def test_detail_filter_visits_new_recent_and_changed_notes():
    existing = {
        "recent": _stored("recent", days_ago=3, body="已有正文"),
        "changed": _stored("changed", days_ago=60, views=100),
        "same": _stored("same", days_ago=60, views=100),
    }
    detail_filter, _body_filter = _build_incremental_filters(existing)

    assert detail_filter(_list_note("brand-new", days_ago=60)) is True
    assert detail_filter(_list_note("recent", days_ago=3)) is True
    assert detail_filter(_list_note("changed", days_ago=60, views=500)) is True
    assert detail_filter(_list_note("same", days_ago=60, views=100)) is False


async def test_body_filter_never_rescrapes_stored_caption():
    existing = {
        "has-body": _stored("has-body", days_ago=3, body="已有正文"),
        "no-body-recent": _stored("no-body-recent", days_ago=10),
        "no-body-old": _stored("no-body-old", days_ago=60),
    }
    _detail_filter, body_filter = _build_incremental_filters(existing)

    assert body_filter(_list_note("has-body", days_ago=3)) is False
    assert body_filter(_list_note("no-body-recent", days_ago=10)) is True
    assert body_filter(_list_note("no-body-old", days_ago=60)) is False
    # A brand-new recent note has no stored caption → scrape it once.
    assert body_filter(_list_note("brand-new", days_ago=1)) is True


async def test_filters_disabled_when_state_unavailable():
    """Unreadable DB state → list-only import, no per-note page visits."""
    detail_filter, body_filter = _build_incremental_filters(None)

    assert detail_filter(_list_note("brand-new", days_ago=1)) is False
    assert body_filter(_list_note("brand-new", days_ago=1)) is False


async def test_load_note_sync_state_roundtrip():
    bundle = normalize_bundle(
        {"view_count": 10},
        [{**_list_note("n1", days_ago=5), "body_text": "正文内容"}],
        "acct_state",
    )
    await import_bundle(bundle, run_creative_analysis=False)

    state = await _load_note_sync_state("acct_state")

    assert state is not None
    assert state["n1"].body_text == "正文内容"


# ── CDP wiring ────────────────────────────────────────────────────────────────


async def test_sync_from_creator_center_passes_incremental_filters_on_cdp():
    bundle = normalize_bundle({"view_count": 1}, [], "acct_cdp")
    with patch.object(pipeline, "CreatorStatsClient") as client_cls:
        client = client_cls.return_value
        client.fetch_all = AsyncMock(return_value=bundle)
        client.aclose = AsyncMock()

        result = await sync_from_creator_center(
            "acct_cdp",
            "",
            cdp_endpoint="http://127.0.0.1:9222",
            skip_login_preflight=True,
            run_creative_analysis=False,
        )

    kwargs = client.fetch_all.await_args.kwargs
    assert callable(kwargs["detail_filter"])
    assert callable(kwargs["body_filter"])
    assert result.error is None


async def test_sync_from_creator_center_skips_fresh_snapshot_before_opening_client(monkeypatch):
    """A scheduled refresh must not create a browser client for fresh data."""
    monkeypatch.setenv("CREATOR_STATS_MIN_REFRESH_HOURS", "18")
    with (
        patch.object(
            pipeline.stats_db,
            "get_account_stats",
            new=AsyncMock(return_value=SimpleNamespace(synced_at=_iso(0.1))),
        ),
        patch.object(pipeline, "CreatorStatsClient") as client_cls,
    ):
        result = await sync_from_creator_center(
            "acct_fresh",
            "",
            cdp_endpoint="http://127.0.0.1:9222",
            skip_login_preflight=True,
            run_creative_analysis=False,
        )

    assert result.account_synced is True
    assert result.notes_imported == 0
    assert result.niche_resolution["skipped"] == "fresh"
    client_cls.assert_not_called()


async def test_fresh_snapshot_skips_login_preflight_too(monkeypatch):
    monkeypatch.setenv("CREATOR_STATS_MIN_REFRESH_HOURS", "18")
    with (
        patch.object(
            pipeline.stats_db,
            "get_account_stats",
            new=AsyncMock(return_value=SimpleNamespace(synced_at=_iso(0.1))),
        ),
        patch.object(pipeline, "preflight_creator_login", new=AsyncMock()) as preflight,
    ):
        result = await sync_from_creator_center(
            "acct_fresh",
            "",
            cdp_endpoint="http://127.0.0.1:9222",
            run_creative_analysis=False,
        )

    assert result.account_synced is True
    preflight.assert_not_awaited()


async def test_nonfinite_refresh_window_config_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CREATOR_STATS_MIN_REFRESH_HOURS", "nan")
    with patch.object(
        pipeline.stats_db,
        "get_account_stats",
        new=AsyncMock(return_value=SimpleNamespace(synced_at=_iso(0.1))),
    ):
        should_skip, retry_after = await pipeline._account_freshness_skip("acct_fresh")

    assert should_skip is True
    assert retry_after > 0


async def test_sync_from_creator_center_forces_light_fetch_when_requested():
    bundle = normalize_bundle({"view_count": 1}, [], "acct_light")
    with patch.object(pipeline, "CreatorStatsClient") as client_cls:
        client = client_cls.return_value
        client.fetch_all = AsyncMock(return_value=bundle)
        client.aclose = AsyncMock()

        result = await sync_from_creator_center(
            "acct_light",
            "",
            cdp_endpoint="http://127.0.0.1:9222",
            skip_login_preflight=True,
            skip_freshness_check=True,
            force_light=True,
            run_creative_analysis=False,
        )

    assert result.error is None
    assert client.fetch_all.await_args.kwargs["force_light"] is True


# ── Current-active-account-only sync ─────────────────────────────────────────


async def test_batch_sync_only_syncs_current_active_account():
    """Switching the active account must stop the previous account's sync."""
    with (
        patch(
            "backend.db.accounts.get_active_account",
            AsyncMock(return_value=SimpleNamespace(id="current-1")),
        ),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            AsyncMock(return_value="http://127.0.0.1:9222"),
        ),
        patch.object(
            pipeline,
            "sync_account_stats",
            AsyncMock(return_value=SyncResult(account_id="current-1", account_synced=True)),
        ) as sync_mock,
    ):
        summary = await pipeline._sync_all_active_accounts_locked()

    assert summary["active_accounts"] == 1
    assert summary["succeeded"] == 1
    assert sync_mock.await_count == 1
    assert sync_mock.await_args.args[0] == "current-1"


async def test_batch_sync_propagates_freshness_override_to_account_sync():
    with (
        patch(
            "backend.db.accounts.get_active_account",
            AsyncMock(return_value=SimpleNamespace(id="current-1")),
        ),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            AsyncMock(return_value="http://127.0.0.1:9222"),
        ),
        patch.object(
            pipeline,
            "sync_account_stats",
            AsyncMock(return_value=SyncResult(account_id="current-1", account_synced=True)),
        ) as sync_mock,
    ):
        await pipeline._sync_all_active_accounts_locked(skip_freshness_check=True)

    assert sync_mock.await_args.kwargs["skip_freshness_check"] is True


async def test_batch_sync_without_active_account_is_empty_success():
    with patch("backend.db.accounts.get_active_account", AsyncMock(return_value=None)):
        summary = await pipeline._sync_all_active_accounts_locked()

    assert summary["ok"] is True
    assert summary["active_accounts"] == 0
    assert summary["results"] == []
