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
from backend.services.creator_stats.types import NoteStats

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


# ── Inter-account pacing ──────────────────────────────────────────────────────


async def test_active_accounts_sync_paces_between_accounts_but_not_before_first():
    accounts = [SimpleNamespace(id="a1"), SimpleNamespace(id="a2"), SimpleNamespace(id="a3")]
    with (
        patch(
            "backend.db.accounts.list_active_accounts",
            AsyncMock(return_value=accounts),
        ),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            AsyncMock(return_value=""),
        ),
        patch.object(pipeline, "_pace_between_accounts", AsyncMock()) as pace,
    ):
        summary = await pipeline._sync_all_active_accounts_locked()

    assert pace.await_count == 2
    assert summary["active_accounts"] == 3


async def test_pace_between_accounts_zero_delay_disables_sleep(monkeypatch):
    monkeypatch.setenv("CREATOR_STATS_INTER_ACCOUNT_DELAY_MAX_S", "0")
    with patch.object(pipeline.random, "uniform", side_effect=AssertionError("must not sleep")):
        await pipeline._pace_between_accounts()
