"""API/CLI entry + analytics tools against the shipped pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import analytics as analytics_routes
from backend.api.routes import free as free_routes
from backend.db.creator_stats import (
    _reset_memory_store,
    list_note_stats,
    upsert_bundle,
)
from backend.services.creator_stats.pipeline import (
    sync_account_stats,
    sync_all_active_accounts,
    sync_from_fixture,
)
from backend.services.creator_stats.types import AccountStatsOverview, NoteStats, SyncResult
from backend.tools.xhs import analytics as analytics_tools

from .conftest import grant_test_user


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(analytics_routes.router, prefix="/api/analytics")
    app.include_router(free_routes.router, prefix="/api/free")
    app.state.graph = MagicMock()
    app.state.graph.store = None
    return app


@pytest.mark.asyncio
async def test_fixture_service_path_returns_import_counts():
    result = await sync_from_fixture("api_acc")
    assert result.error is None
    assert result.source == "fixture"
    assert result.notes_imported == 5
    assert result.account_synced is True
    assert result.account_id == "api_acc"
    assert result.analysis is not None
    assert result.analysis.note_count == 5
    assert result.suggestions["trend"]
    assert result.suggestions["brief"]
    assert result.suggestions["free"]


@pytest.mark.asyncio
async def test_batch_sync_uses_only_current_active_account():
    """Only the currently active account is synced, never previous ones."""

    async def sync(account_id: str, **kwargs):
        return SyncResult(account_id=account_id, account_synced=True)

    with (
        patch(
            "backend.db.accounts.get_active_account",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id="active-1"),
        ),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new_callable=AsyncMock,
            return_value="http://127.0.0.1:9001",
        ),
        patch(
            "backend.services.creator_stats.pipeline.sync_account_stats",
            new_callable=AsyncMock,
            side_effect=sync,
        ) as sync_mock,
    ):
        result = await sync_all_active_accounts(run_creative_analysis=False)

    assert result["ok"] is True
    assert result["active_accounts"] == 1
    assert result["succeeded"] == 1
    assert [call.args[0] for call in sync_mock.await_args_list] == ["active-1"]


@pytest.mark.asyncio
async def test_batch_sync_returns_already_running_when_postgres_lock_is_busy():
    class _Cursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, *_args):
            return None

        async def fetchone(self):
            return (False,)

    class _Connection:
        def connection(self):
            return self

        def transaction(self):
            return self

        def cursor(self):
            return _Cursor()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class _Pool:
        def connection(self):
            return _Connection()

    with (
        patch("backend.db.pool.is_pool_ready", return_value=True),
        patch("backend.db.pool.get_pool", return_value=_Pool()),
    ):
        result = await sync_all_active_accounts(run_creative_analysis=False)

    assert result["ok"] is False
    assert result["status"] == "already_running"


def test_batch_sync_endpoint_returns_atomic_batch_summary():
    app = _app()
    client = TestClient(app)
    summary = {
        "ok": True,
        "status": "completed",
        "active_accounts": 1,
        "succeeded": 1,
        "failed": 0,
        "results": [],
    }
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new_callable=AsyncMock,
            return_value=summary,
        ) as sync_all,
        grant_test_user(app),
    ):
        response = client.post(
            "/api/analytics/creator-stats/sync-all",
            json={"period": "7d", "analyze": False},
        )

    assert response.status_code == 200
    assert response.json()["data"] == summary
    sync_all.assert_awaited_once_with(store=None, period="7d", run_creative_analysis=False)


@pytest.mark.asyncio
async def test_fixture_service_path_twice_is_consistent():
    r1 = await sync_from_fixture("api_twice")
    r2 = await sync_from_fixture("api_twice")
    assert r1.notes_imported == 5
    assert r1.notes_deleted == 0
    assert r2.notes_updated == 5
    assert r2.notes_deleted == 0


@pytest.mark.asyncio
async def test_sync_from_fixture_deletes_stale_local_notes():
    """Full import path must surface notes_deleted and drop orphan local rows."""
    await upsert_bundle(
        AccountStatsOverview(account_id="api_prune", note_count=1),
        [
            NoteStats(
                note_id="orphan-local",
                account_id="api_prune",
                title="deleted on creator center",
                views=9,
            )
        ],
    )
    result = await sync_from_fixture("api_prune", run_creative_analysis=False)
    assert result.error is None
    assert result.account_synced is True
    assert result.notes_imported == 5
    assert result.notes_deleted == 1
    note_ids = {n.note_id for n in await list_note_stats("api_prune")}
    assert "orphan-local" not in note_ids
    assert len(note_ids) == 5


@pytest.mark.asyncio
async def test_get_creator_stats_after_fixture_service_import():
    await sync_from_fixture("api_get")
    app = _app()
    client = TestClient(app)
    with grant_test_user(app):
        resp = client.get("/api/analytics/creator-stats/api_get")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["account"]["views"] == 128400
    assert data["account"]["creator_user_id"] == "creator_fixture_001"
    assert data["account"]["creator_name"] == "温柔育儿笔记"
    assert data["account"]["red_id"] == "gentle_parenting"
    assert data["account"]["avatar_url"] == "https://example.com/avatar.jpg"
    assert data["account"]["bio"] == "记录轻松、可靠的育儿日常"
    assert data["account"]["creator_role"] == "creator"
    assert data["account"]["zone"] == "上海"
    assert "phone" not in data["account"]
    assert "permissions" not in data["account"]
    assert "real_name_verified" not in data["account"]
    assert data["total"] == 5
    assert data["audience_analysis"]["coverage"] == {
        "sources": False,
        "periods": False,
        "profile": False,
        "notes_with_view_sources": 0,
    }
    ids = {n["note_id"] for n in data["notes"]}
    assert "note_heal_001" in ids
    note = next(n for n in data["notes"] if n["note_id"] == "note_heal_001")
    assert note["likes"] == 3800
    assert note["views"] == 42000


@pytest.mark.asyncio
async def test_get_creator_stats_total_ignores_limit():
    """total must be full note count even when page limit < total."""
    await sync_from_fixture("api_limit")
    app = _app()
    client = TestClient(app)
    with grant_test_user(app):
        resp = client.get("/api/analytics/creator-stats/api_limit?limit=2")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["notes"]) == 2
    assert data["total"] == 5
    assert data["limit"] == 2
    assert data["snapshot_id"].startswith("snapshot:")
    assert data["engagement_rate_unit"] == "fraction"


@pytest.mark.asyncio
async def test_suggestions_endpoint_each_mode():
    await sync_from_fixture("api_sug")
    app = _app()
    client = TestClient(app)
    for mode in ("trend", "brief", "free"):
        with grant_test_user(app):
            resp = client.get(f"/api/analytics/creator-stats/api_sug/suggestions?mode={mode}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["mode"] == mode
        assert data["count"] > 0
        assert data["cold_start"] is False
        assert any("示例模式" not in s["advice"] for s in data["suggestions"])


@pytest.mark.asyncio
async def test_free_mode_suggestions_route():
    await sync_from_fixture("api_free")
    app = _app()
    client = TestClient(app)
    with grant_test_user(app):
        resp = client.get("/api/free/suggestions/api_free")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["mode"] == "free"
    assert data["count"] > 0
    assert data["cold_start"] is False


def test_cold_start_suggestions_endpoint():
    app = _app()
    client = TestClient(app)
    with grant_test_user(app):
        resp = client.get("/api/analytics/creator-stats/no_data_yet/suggestions?mode=trend")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cold_start"] is True
    assert data["count"] > 0


@pytest.mark.asyncio
async def test_analytics_reader_reads_imported_note():
    await sync_account_stats("tool_acc", dry_run=True)
    # LangChain @tool wraps coroutine — call .ainvoke or underlying func
    result = await analytics_tools.analytics_reader.ainvoke(
        {"post_id": "note_heal_001", "account_id": "tool_acc"}
    )
    assert result["views"] == 42000
    assert result["likes"] == 3800
    assert result["source"] == "fixture" or result["source"] == "creator_statistics"


@pytest.mark.asyncio
async def test_pattern_detector_not_placeholder_when_data_exists():
    await sync_account_stats("tool_pat", dry_run=True)
    patterns = await analytics_tools.pattern_detector.ainvoke(
        {"time_range": "30d", "account_id": "tool_pat"}
    )
    assert patterns
    assert patterns[0]["pattern"] != "示例模式"
    assert "evidence" in patterns[0]


@pytest.mark.asyncio
async def test_report_generator_includes_fixture_metrics():
    await sync_account_stats("tool_rep", dry_run=True)
    report = await analytics_tools.report_generator.ainvoke(
        {"account_id": "tool_rep", "period": "weekly"}
    )
    assert "tool_rep" in report
    assert "导入笔记" in report
    assert "5" in report
    # Durable style DNA deposited on import should surface in report
    assert "风格DNA" in report or "治愈" in report


@pytest.mark.asyncio
async def test_analytics_reader_strips_account_id_whitespace():
    await sync_account_stats("tool_strip", dry_run=True)
    result = await analytics_tools.analytics_reader.ainvoke(
        {"post_id": "note_heal_001", "account_id": " tool_strip "}
    )
    assert result["views"] == 42000
    assert result.get("source") != "unavailable"


@pytest.mark.asyncio
async def test_free_suggestions_after_import_not_cold_start():
    await sync_account_stats("free_sug_acc", dry_run=True)
    app = _app()
    client = TestClient(app)
    with grant_test_user(app):
        resp = client.get("/api/free/suggestions/free_sug_acc")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] > 0
    assert data.get("cold_start") is False
    assert data["mode"] == "free"
