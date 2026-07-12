"""Mode case-insensitivity + fixture path resolution outside project cwd."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import analytics as analytics_routes
from backend.db.creator_stats import _reset_memory_store
from backend.services.creator_stats.pipeline import (
    DEFAULT_FIXTURE_PATH,
    _resolve_fixture_path,
    load_fixture_payload,
    sync_from_fixture,
)
from backend.services.creator_stats.suggestions import (
    _normalize_mode,
    get_suggestions_for_mode,
)


@pytest.fixture(autouse=True)
def _clear():
    _reset_memory_store()
    yield
    _reset_memory_store()


def test_normalize_mode_case_and_whitespace():
    assert _normalize_mode("FREE") == "free"
    assert _normalize_mode(" Brief ") == "brief"
    assert _normalize_mode("TREND") == "trend"
    assert _normalize_mode("nope") == "trend"
    assert _normalize_mode(None) == "trend"
    assert _normalize_mode("") == "trend"


@pytest.mark.asyncio
async def test_get_suggestions_for_mode_accepts_uppercase_free():
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=None),
        patch("backend.db.accounts.update_account", new_callable=AsyncMock),
    ):
        await sync_from_fixture("mode_case")
    items = await get_suggestions_for_mode("mode_case", "FREE")  # type: ignore[arg-type]
    assert items
    assert all(s.mode == "free" for s in items)
    assert any(s.category != "cold_start" for s in items)


def test_resolve_fixture_path_relative_from_other_cwd(tmp_path):
    """Relative fixture path must resolve via project root when cwd is elsewhere."""
    assert DEFAULT_FIXTURE_PATH.is_file()
    rel = Path("tests/fixtures/creator_stats_sample.json")
    # ponytail: derive repo root from this file, not a hardcoded absolute path
    # (CI runners don't have /test/xhs). parents[3] = repo root from tests/.../creator_stats/
    project_root = Path(__file__).resolve().parents[3]
    # From project root works
    os.chdir(project_root)
    assert _resolve_fixture_path(rel).is_file()
    # From unrelated cwd still works
    os.chdir(tmp_path)
    try:
        resolved = _resolve_fixture_path(rel)
        assert resolved.is_file(), resolved
        payload = load_fixture_payload(rel)
        assert "notes" in payload
        assert len(payload["notes"]) >= 3
    finally:
        os.chdir(project_root)


def test_api_suggestions_mode_case_insensitive():
    app = FastAPI()
    app.include_router(analytics_routes.router, prefix="/api/analytics")
    app.state.graph = MagicMock()
    client = TestClient(app)

    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=None),
        patch("backend.db.accounts.update_account", new_callable=AsyncMock),
    ):
        sync = client.post(
            "/api/analytics/creator-stats/sync",
            json={"account_id": "api_mode", "dry_run": True},
        )
        assert sync.status_code == 200
        assert sync.json()["data"]["ok"] is True

        r = client.get("/api/analytics/creator-stats/api_mode/suggestions?mode=FREE")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["mode"] == "free"
        assert data["count"] > 0
        assert data["cold_start"] is False

        r2 = client.get("/api/analytics/creator-stats/api_mode/suggestions?mode=Brief")
        assert r2.status_code == 200
        assert r2.json()["data"]["mode"] == "brief"
