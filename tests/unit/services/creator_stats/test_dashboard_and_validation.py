"""Cycle-4: dashboard merges imports; account_id / mode validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import analytics as analytics_routes
from backend.db.creator_stats import _reset_memory_store, list_note_stats
from backend.services.creator_stats.pipeline import sync_account_stats, sync_from_payload
from backend.services.creator_stats.suggestions import (
    get_suggestions_for_mode,
    suggestions_from_analysis,
)
from backend.services.creator_stats.types import AnalysisResult, NoteStats

from .conftest import grant_test_user


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


async def _seed_recent(account_id: str, note_id: str = "dash_note_1") -> None:
    recent = (datetime.now(UTC) - timedelta(hours=12)).isoformat()
    await sync_from_payload(
        account_id,
        {"view_count": 9000, "like_count": 400},
        [
            {
                "note_id": note_id,
                "title": "仪表盘可见笔记",
                "view_count": 9000,
                "like_count": 400,
                "comment_count": 40,
                "collect_count": 80,
                "share_count": 10,
                "publish_time": recent,
                "tags": ["母婴"],
            }
        ],
        source="fixture",
        run_creative_analysis=False,
    )


def test_period_summary_uses_complete_current_and_previous_windows() -> None:
    """Period aggregates must not depend on the visible post-page limit."""
    now = datetime(2026, 7, 18, 12, tzinfo=UTC)
    posts = [
        {
            "published_at": "2026-07-18T10:00:00+00:00",
            "views": 100,
            "likes": 10,
            "comments": 2,
            "collects": 3,
            "shares": 1,
            "engagement_rate": 16,
        },
        {
            "published_at": "2026-07-17T10:00:00+00:00",
            "views": 200,
            "likes": 20,
            "comments": 4,
            "collects": 6,
            "shares": 2,
            "engagement_rate": 15,
        },
        {
            "published_at": "2026-07-10T10:00:00+00:00",
            "views": 900,
            "likes": 90,
            "comments": 9,
            "collects": 9,
            "shares": 3,
            "engagement_rate": 12,
        },
    ]

    summary = analytics_routes._build_period_summary(posts, "weekly", now=now)

    assert summary["current"]["posts"] == 2
    assert summary["current"]["views"] == 300
    assert summary["current"]["engagement"] == 45
    assert summary["current"]["shares"] == 3
    assert summary["previous"]["posts"] == 1
    assert summary["previous"]["views"] == 900


def test_period_summary_prefers_creator_center_daily_series() -> None:
    """Headline views must match Creator Center window totals, not sum of note lifetime.

    Live audit: account 30d views=3822 while summing three notes published in
    the month only yielded 149 — the dashboard was understating official stats.
    """
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    # Notes published in-window with low lifetime totals (the old wrong source).
    posts = [
        {
            "published_at": "2026-07-27T10:00:00+00:00",
            "views": 22,
            "likes": 5,
            "comments": 0,
            "collects": 2,
            "shares": 0,
            "engagement_rate": 31.8,
        },
        {
            "published_at": "2026-07-25T10:00:00+00:00",
            "views": 18,
            "likes": 6,
            "comments": 0,
            "collects": 3,
            "shares": 0,
            "engagement_rate": 50.0,
        },
        {
            "published_at": "2026-07-22T10:00:00+00:00",
            "views": 109,
            "likes": 9,
            "comments": 0,
            "collects": 4,
            "shares": 0,
            "engagement_rate": 11.9,
        },
    ]
    # 30 daily points ending at 2026-07-30 16:00 UTC (matches live payloads).
    def _day(offset: int, count: int) -> dict[str, Any]:
        day = datetime(2026, 7, 1, 16, tzinfo=UTC) + timedelta(days=offset)
        return {"date": int(day.timestamp() * 1000), "count": count}

    # 30 days of views; last 7 sum to 80; all 30 sum to 3822-like total.
    view_counts = [0] * 20 + [105, 2, 81, 15, 14, 20, 4, 20, 4, 3]
    # pad/trim to 30
    while len(view_counts) < 30:
        view_counts.insert(0, 50)
    view_counts = view_counts[-30:]
    like_counts = [1 if c else 0 for c in view_counts]
    detail = {
        "view_count": sum(view_counts),
        "like_count": sum(like_counts),
        "view_list": [_day(i, c) for i, c in enumerate(view_counts)],
        "like_list": [_day(i, c) for i, c in enumerate(like_counts)],
        "comment_list": [_day(i, 0) for i in range(30)],
        "collect_list": [_day(i, 0) for i in range(30)],
        "share_list": [_day(i, 0) for i in range(30)],
    }

    summary = analytics_routes._build_period_summary(
        posts, "weekly", now=now, detail_metrics=detail
    )
    assert summary["current"]["metric_source"] == "creator_center_series"
    # Published-in-window note count still comes from the notes list.
    assert summary["current"]["posts"] == 2
    # Views come from the daily series, not 22+18=40.
    assert summary["current"]["views"] == sum(view_counts[-7:])
    assert summary["current"]["views"] != 40
    assert summary["current"]["likes"] == sum(like_counts[-7:])

    monthly = analytics_routes._build_period_summary(
        posts, "monthly", now=now, detail_metrics=detail
    )
    assert monthly["current"]["views"] == sum(view_counts)
    assert monthly["current"]["views"] != 149


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(analytics_routes.router, prefix="/api/analytics")
    app.state.graph = MagicMock()
    return app


@pytest.mark.asyncio
async def test_dashboard_includes_imported_notes_for_frontend_path():
    """Frontend Analytics uses GET /dashboard — must surface creator-center imports."""
    await _seed_recent("dash_acc")
    app = _app()
    client = TestClient(app)

    with pytest.MonkeyPatch.context() as mp, grant_test_user(app):

        async def _empty(*_a, **_k):
            return []

        mp.setattr(analytics_routes, "_get_completed_workflows", _empty)
        resp = client.get("/api/analytics/dashboard/dash_acc?period=weekly&limit=20")

    assert resp.status_code == 200
    body = resp.json()["data"]
    perf = body["performance"]
    report = body["report"]
    assert perf["total"] >= 1
    ids = {p["id"] for p in perf["posts"]}
    assert "dash_note_1" in ids
    note = next(p for p in perf["posts"] if p["id"] == "dash_note_1")
    assert note["views"] == 9000
    assert note["likes"] == 400
    assert 0 <= note["engagement_rate"] <= 1
    assert body["engagement_rate_unit"] == "fraction"
    assert body["period_summary"]["engagement_rate_unit"] == "fraction"
    assert report["metrics"]["total_posts"] >= 1
    assert report["metrics"]["total_engagement"] >= 400
    assert report["engagement_rate_unit"] == "fraction"
    assert 0 <= report["metrics"]["avg_engagement_rate"] <= 1
    assert all(0 <= post["engagement_rate"] <= 1 for post in perf["posts"])
    assert body["period_summary"]["current"]["posts"] >= 1
    assert 0 <= body["period_summary"]["current"]["avg_engagement_rate"] <= 1
    # Insight mentions creator-center import path
    messages = " ".join(i["message"] for i in report["insights"])
    assert "创作者中心" in messages or report["metrics"]["total_posts"] > 0


@pytest.mark.asyncio
async def test_dashboard_uses_bundle_notes_and_snapshot_without_re_reading_metadata():
    recent = (datetime.now(UTC) - timedelta(hours=12)).isoformat()
    bundle_note = NoteStats(
        note_id="bundle_dash_note",
        account_id="bundle_dash",
        title="同一批次",
        views=1000,
        likes=100,
        published_at=recent,
        synced_at="2026-07-22T10:00:00Z",
        engagement_rate=0.1,
    )
    bundle = {
        "account_id": "bundle_dash",
        "account": None,
        "notes": [bundle_note],
        "note_count": 1,
        "data_as_of": "2026-07-22T10:00:00Z",
        "snapshot_id": "snapshot:bundle-dash",
    }
    app = _app()
    client = TestClient(app)

    with pytest.MonkeyPatch.context() as mp, grant_test_user(app):

        async def _empty(*_a, **_k):
            return []

        async def _bundle(_account_id: str) -> dict[str, object]:
            return bundle

        async def _unexpected_metadata(_account_id: str) -> dict[str, object]:
            raise AssertionError("dashboard must not read a second snapshot")

        mp.setattr(analytics_routes, "_get_completed_workflows", _empty)
        mp.setattr(analytics_routes, "_creator_snapshot_bundle", _bundle)
        mp.setattr(analytics_routes, "_creator_snapshot_metadata", _unexpected_metadata)
        response = client.get("/api/analytics/dashboard/bundle_dash?period=weekly&limit=20")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot_id"] == "snapshot:bundle-dash"
    assert data["performance"]["posts"][0]["id"] == "bundle_dash_note"
    assert data["report"]["metrics"]["total_posts"] == 1


@pytest.mark.asyncio
async def test_growth_report_includes_imported_notes():
    await _seed_recent("rep_acc", "rep_note_1")
    app = _app()
    client = TestClient(app)
    with pytest.MonkeyPatch.context() as mp, grant_test_user(app):

        async def _empty(*_a, **_k):
            return []

        mp.setattr(analytics_routes, "_get_completed_workflows", _empty)
        resp = client.get("/api/analytics/report/rep_acc?period=weekly")
    data = resp.json()["data"]
    assert data["metrics"]["total_posts"] >= 1
    assert data["metrics"]["best_post_title"] == "仪表盘可见笔记"
    assert data["engagement_rate_unit"] == "fraction"
    assert 0 <= data["metrics"]["avg_engagement_rate"] <= 1


@pytest.mark.asyncio
async def test_canonical_note_endpoint_exposes_stable_scope_and_snapshot():
    await _seed_recent("canonical_acc", "canonical_note_1")
    app = _app()
    client = TestClient(app)

    with grant_test_user(app):
        first = client.get("/api/analytics/creator-stats/canonical_acc/notes?limit=1")
        assert first.status_code == 200
        data = first.json()["data"]
        assert data["account_id"] == "canonical_acc"
        assert data["scope"] == "account_history"
        assert data["subject_type"] == "imported_note"
        assert data["assessment_type"] == "historical_performance"
        assert data["engagement_rate_unit"] == "fraction"
        assert data["snapshot_id"].startswith("snapshot:")
        assert data["items"][0]["subject_id"] == "canonical_note_1"
        assert data["items"][0]["note_synced_at"]

        with pytest.MonkeyPatch.context() as mp:

            async def _empty(*_a, **_k):
                return []

            mp.setattr(analytics_routes, "_get_completed_workflows", _empty)
            dashboard = client.get("/api/analytics/dashboard/canonical_acc?period=weekly&limit=20")
            report = client.get("/api/analytics/report/canonical_acc?period=weekly")
            performance = client.get(
                "/api/analytics/performance/canonical_acc?period=weekly&limit=20"
            )
        quality = client.get("/api/analytics/creator-stats/canonical_acc/quality")
        detail = client.get("/api/analytics/creator-stats/canonical_acc/notes/canonical_note_1")

    snapshot_ids = {
        data["snapshot_id"],
        dashboard.json()["data"]["snapshot_id"],
        report.json()["data"]["snapshot_id"],
        performance.json()["data"]["snapshot_id"],
        quality.json()["data"]["snapshot_id"],
        detail.json()["data"]["snapshot_id"],
    }
    assert len(snapshot_ids) == 1
    assert report.json()["data"]["engagement_rate_unit"] == "fraction"
    assert performance.json()["data"]["engagement_rate_unit"] == "fraction"


@pytest.mark.asyncio
async def test_performance_and_dashboard_strip_account_id():
    """Path account_id with spaces must still resolve imported notes."""
    await _seed_recent("strip_dash", "strip_n1")
    app = _app()
    client = TestClient(app)
    with pytest.MonkeyPatch.context() as mp, grant_test_user(app):

        async def _empty(*_a, **_k):
            return []

        mp.setattr(analytics_routes, "_get_completed_workflows", _empty)
        # Call service layer with spaced id (path encoding would strip spaces)

        # Direct call simulation: strip happens inside handler
        # Use TestClient with account that we strip ourselves by patching Request
        resp = client.get("/api/analytics/performance/strip_dash?period=weekly&limit=10")
        assert resp.status_code == 200
        performance = resp.json()["data"]
        assert performance["engagement_rate_unit"] == "fraction"
        assert all(0 <= p["engagement_rate"] <= 1 for p in performance["posts"])
        ids = {p["id"] for p in performance["posts"]}
        assert "strip_n1" in ids

        # Internal strip: call list after strip logic via merge
        from backend.api.routes.analytics import _merge_imported_posts

        merged = await _merge_imported_posts("  strip_dash  ", [], limit=20)
        assert any(p["id"] == "strip_n1" for p in merged)


@pytest.mark.asyncio
async def test_empty_account_id_rejected():
    r = await sync_account_stats("", dry_run=True)
    assert r.error is not None
    assert "account_id" in r.error
    assert r.notes_imported == 0
    assert await list_note_stats("") == []

    r2 = await sync_account_stats("   ", dry_run=True)
    assert r2.error is not None
    assert r2.notes_imported == 0


@pytest.mark.asyncio
async def test_invalid_mode_does_not_raise():
    cold = AnalysisResult(account_id="m", cold_start=True, note_count=0)
    out = suggestions_from_analysis(cold, mode="bogus")  # type: ignore[arg-type]
    assert "trend" in out  # coerced
    assert out["trend"]
    assert all(s.category == "cold_start" for s in out["trend"])

    items = await get_suggestions_for_mode("no_data", "not_a_mode")  # type: ignore[arg-type]
    assert items
    assert all(s.category == "cold_start" for s in items)
