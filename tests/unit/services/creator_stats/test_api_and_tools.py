"""API/CLI entry + analytics tools against the shipped pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import analytics as analytics_routes
from backend.api.routes import free as free_routes
from backend.db.creator_stats import _reset_memory_store
from backend.services.creator_stats.pipeline import sync_account_stats
from backend.tools.xhs import analytics as analytics_tools

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "creator_stats_sample.json"


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


def test_sync_endpoint_dry_run_returns_import_counts():
    client = TestClient(_app())
    resp = client.post(
        "/api/analytics/creator-stats/sync",
        json={"account_id": "api_acc", "dry_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["ok"] is True
    assert data["notes_imported"] == 5
    assert data["account_synced"] is True
    assert data["account_id"] == "api_acc"
    assert data["analysis"] is not None
    assert data["analysis"]["note_count"] == 5
    assert data["suggestions"]["trend"]
    assert data["suggestions"]["brief"]
    assert data["suggestions"]["free"]


def test_sync_endpoint_twice_is_consistent():
    client = TestClient(_app())
    r1 = client.post(
        "/api/analytics/creator-stats/sync",
        json={"account_id": "api_twice", "dry_run": True},
    ).json()["data"]
    r2 = client.post(
        "/api/analytics/creator-stats/sync",
        json={"account_id": "api_twice", "dry_run": True},
    ).json()["data"]
    assert r1["ok"] and r2["ok"]
    assert r1["notes_imported"] == 5
    assert r2["notes_updated"] == 5


def test_get_creator_stats_after_import():
    client = TestClient(_app())
    client.post(
        "/api/analytics/creator-stats/sync",
        json={"account_id": "api_get", "dry_run": True},
    )
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
    ids = {n["note_id"] for n in data["notes"]}
    assert "note_heal_001" in ids
    note = next(n for n in data["notes"] if n["note_id"] == "note_heal_001")
    assert note["likes"] == 3800
    assert note["views"] == 42000


def test_get_creator_stats_total_ignores_limit():
    """total must be full note count even when page limit < total."""
    client = TestClient(_app())
    client.post(
        "/api/analytics/creator-stats/sync",
        json={"account_id": "api_limit", "dry_run": True},
    )
    resp = client.get("/api/analytics/creator-stats/api_limit?limit=2")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["notes"]) == 2
    assert data["total"] == 5
    assert data["limit"] == 2


def test_suggestions_endpoint_each_mode():
    client = TestClient(_app())
    client.post(
        "/api/analytics/creator-stats/sync",
        json={"account_id": "api_sug", "dry_run": True},
    )
    for mode in ("trend", "brief", "free"):
        resp = client.get(f"/api/analytics/creator-stats/api_sug/suggestions?mode={mode}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["mode"] == mode
        assert data["count"] > 0
        assert data["cold_start"] is False
        assert any("示例模式" not in s["advice"] for s in data["suggestions"])


def test_free_mode_suggestions_route():
    client = TestClient(_app())
    client.post(
        "/api/analytics/creator-stats/sync",
        json={"account_id": "api_free", "dry_run": True},
    )
    resp = client.get("/api/free/suggestions/api_free")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["mode"] == "free"
    assert data["count"] > 0
    assert data["cold_start"] is False


def test_cold_start_suggestions_endpoint():
    client = TestClient(_app())
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
    client = TestClient(_app())
    resp = client.get("/api/free/suggestions/free_sug_acc")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] > 0
    assert data.get("cold_start") is False
    assert data["mode"] == "free"
