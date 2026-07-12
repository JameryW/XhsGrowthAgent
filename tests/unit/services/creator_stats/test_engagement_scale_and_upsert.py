"""Cycle-5: engagement-rate scale consistency + invalid upsert skip."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import analytics as analytics_routes
from backend.api.routes.analytics import (
    _as_percent_engagement_rate,
    _build_growth_report,
    _extract_post_data,
    _imported_notes_as_posts,
)
from backend.db.creator_stats import (
    _reset_memory_store,
    get_account_stats,
    get_note_stats,
    list_note_stats,
    upsert_account_stats,
    upsert_note_stats,
    upsert_notes,
)
from backend.services.creator_stats.types import AccountStatsOverview, NoteStats


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

    with pytest.MonkeyPatch.context() as mp:

        async def _wf(*_a, **_k):
            return [{"_state": wf_state, "account_id": "mix_acc"}]

        mp.setattr(analytics_routes, "_get_completed_workflows", _wf)
        resp = client.get("/api/analytics/dashboard/mix_acc?period=weekly&limit=20")

    data = resp.json()["data"]
    rates = [p["engagement_rate"] for p in data["performance"]["posts"]]
    assert rates
    assert all(r >= 1.0 for r in rates)  # percent-like, not raw 0.05
    assert data["report"]["metrics"]["avg_engagement_rate"] == pytest.approx(5.0)


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
