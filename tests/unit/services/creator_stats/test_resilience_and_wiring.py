"""Resilience (analysis-after-persist) + agent/CLI/free wiring tests."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from backend.api.routes import analytics as analytics_routes
from backend.api.routes import free as free_routes
from backend.cli.main import app as cli_app
from backend.db.creator_stats import _reset_memory_store, list_note_stats
from backend.services.creator_stats.analyze import analyze_notes
from backend.services.creator_stats.normalize import (
    normalize_account_overview,
    normalize_bundle,
)
from backend.services.creator_stats.pipeline import import_bundle, sync_from_fixture
from backend.services.creator_stats.types import NoteStats

from .conftest import grant_test_user


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


# ── Analysis failure must not erase import ──────────────────────────────────


@pytest.mark.asyncio
async def test_import_bundle_survives_analysis_failure():
    bundle = normalize_bundle(
        {"view_count": 10},
        [{"note_id": "n_fail", "title": "t", "view_count": 100, "like_count": 5}],
        "acc_an_fail",
    )
    with patch(
        "backend.services.creator_stats.pipeline.run_analysis",
        side_effect=RuntimeError("llm down"),
    ):
        result = await import_bundle(bundle)

    assert result.account_synced is True
    assert result.notes_imported == 1
    assert result.error is not None
    assert "import succeeded" in result.error
    assert result.analysis is None
    notes = await list_note_stats("acc_an_fail")
    assert len(notes) == 1
    assert notes[0].note_id == "n_fail"
    assert notes[0].views == 100


@pytest.mark.asyncio
async def test_topic_prefers_higher_engagement_not_frequency():
    """Regression: most-common tag used to win even with worse engagement."""
    notes = [
        NoteStats(
            note_id="freq1",
            account_id="t",
            title="普通A",
            tags=["高频"],
            views=1000,
            likes=10,
            engagement_rate=0.01,
        ),
        NoteStats(
            note_id="freq2",
            account_id="t",
            title="普通B",
            tags=["高频"],
            views=1000,
            likes=10,
            engagement_rate=0.01,
        ),
        NoteStats(
            note_id="hot1",
            account_id="t",
            title="爆款",
            tags=["高转化"],
            views=1000,
            likes=200,
            comments=50,
            collects=50,
            engagement_rate=0.3,
        ),
    ]
    analysis = analyze_notes(notes, "t")
    topic = next(f for f in analysis.findings if f.finding_type == "topic")
    assert topic.label == "高转化"
    assert topic.score >= 0.3


def test_note_count_ignores_ambiguous_total_field():
    overview = normalize_account_overview(
        {"view_count": 1, "total": 999, "note_count": 3},
        "acc",
    )
    assert overview.note_count == 3
    overview2 = normalize_account_overview({"view_count": 1, "total": 999}, "acc")
    # "total" alone must not become note_count
    assert overview2.note_count == 0


# ── CLI ─────────────────────────────────────────────────────────────────────


def test_cli_sync_stats_dry_run_succeeds():
    runner = CliRunner()
    result = runner.invoke(cli_app, ["sync-stats", "--account-id", "cli_ok", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "notes_imported" in result.output
    assert "5" in result.output


def test_cli_live_without_cookie_fails_honestly():
    """--no-dry-run without cookie must not silently load fixture."""
    runner = CliRunner()
    result = runner.invoke(
        cli_app,
        ["sync-stats", "--account-id", "cli_live", "--no-dry-run"],
    )
    assert result.exit_code == 1
    assert "cookie" in result.output.lower() or "失败" in result.output


def test_cli_live_prepares_db_and_uses_account_cdp_endpoint():
    """A standalone live CLI must prepare durable storage before it pulls data."""
    fake_result = SimpleNamespace(
        account_id="cli_live",
        source="creator_statistics",
        notes_imported=1,
        notes_updated=0,
        notes_deleted=0,
        account_synced=True,
        analysis=None,
        niche_resolution=None,
        suggestions={},
        error=None,
    )
    with (
        patch("backend.db.pool.is_pool_ready", return_value=False),
        patch("backend.db.pool.init_pool", new_callable=AsyncMock) as init_pool,
        patch("backend.db.pool.close_pool", new_callable=AsyncMock) as close_pool,
        patch("backend.db.accounts.ensure_tables", new_callable=AsyncMock) as ensure_accounts,
        patch("backend.db.creator_stats.ensure_tables", new_callable=AsyncMock) as ensure_stats,
        patch("backend.db.creative_memory.ensure_tables", new_callable=AsyncMock) as ensure_memory,
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new_callable=AsyncMock,
            return_value="http://127.0.0.1:9225",
        ),
        patch(
            "backend.services.creator_stats.pipeline.sync_account_stats",
            new_callable=AsyncMock,
            return_value=fake_result,
        ) as sync,
    ):
        result = CliRunner().invoke(
            cli_app,
            ["sync-stats", "--account-id", "cli_live", "--no-dry-run"],
        )

    assert result.exit_code == 0, result.output
    init_pool.assert_awaited_once()
    ensure_accounts.assert_awaited_once()
    ensure_stats.assert_awaited_once()
    ensure_memory.assert_awaited_once()
    sync.assert_awaited_once_with(
        "cli_live",
        cookie="",
        dry_run=False,
        period="30d",
        cdp_endpoint="http://127.0.0.1:9225",
    )
    close_pool.assert_awaited_once()


# ── Agent wiring uses real build_mode_creative_context ──────────────────────


@pytest.mark.asyncio
async def test_copywriter_injects_creator_stats_context():
    from unittest.mock import PropertyMock

    from backend.agents.copywriter import CopywriterAgent

    await sync_from_fixture("cw_acc")
    agent = CopywriterAgent()
    mock_response = MagicMock()
    mock_response.content = (
        '{"selected_title":"标题","body_text":"正文","hashtags":[],"title_candidates":[]}'
    )

    captured: dict = {}

    def capture_prompt(state, extra_context=""):
        captured["extra"] = extra_context
        return "sys {ripple_context}"

    agent._build_system_prompt = capture_prompt  # type: ignore[method-assign]
    agent._build_ripple_context = MagicMock(return_value="")  # type: ignore[method-assign]
    agent._recall_memory = AsyncMock(return_value=[])  # type: ignore[method-assign]

    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    store.aput = AsyncMock()
    store.aget = AsyncMock(return_value=None)

    state = {
        "account_id": "cw_acc",
        "workflow_mode": "trend",
        "content_plan": {"selected_topic": "育儿", "content_type": "note"},
        "niche": "母婴",
        "brief_content": {},
        "human_feedback": {},
        "blogger_notes": [],
    }
    with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        mock_model_prop.return_value = mock_model
        await agent.execute(state, store=store)  # type: ignore[arg-type]

    extra = captured.get("extra", "")
    assert "创作数据建议" in extra or "创作者中心" in extra
    assert "cw_acc" in extra or "互动" in extra or "笔记" in extra


@pytest.mark.asyncio
async def test_content_strategist_calls_build_mode_creative_context():
    """Strategist execute path must call shared free/trend/brief advice entry."""
    from unittest.mock import PropertyMock

    from backend.agents.content_strategist import ContentStrategistAgent

    await sync_from_fixture("st_acc")
    agent = ContentStrategistAgent()
    mock_response = MagicMock()
    mock_response.content = '{"selected_topic":"x","content_angle":"y","target_audience":"z"}'

    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    store.aput = AsyncMock()
    store.aget = AsyncMock(return_value=None)

    agent._recall_memory = AsyncMock(return_value=[])  # type: ignore[method-assign]
    agent._score_trend_topics = AsyncMock(return_value="")  # type: ignore[method-assign]
    agent._extract_candidate_topics = MagicMock(return_value=[])  # type: ignore[method-assign]

    with (
        patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop,
        patch(
            "backend.services.creator_stats.suggestions.build_mode_creative_context",
            new_callable=AsyncMock,
            return_value="创作数据建议（来自创作者中心导入分析）：\n- [style] test",
        ) as mock_build,
        patch(
            "backend.config.settings.Settings",
        ) as mock_settings,
    ):
        mock_settings.return_value.ripple.workflow_timeout = 1
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        mock_model_prop.return_value = mock_model
        # Ripple/later steps may fail; wiring under test already ran before that.
        with contextlib.suppress(Exception):
            await agent.execute(
                {
                    "account_id": "st_acc",
                    "niche": "母婴",
                    "trend_data": {},
                    "session_id": "t1",
                },
                store=store,
            )

    mock_build.assert_awaited()
    assert mock_build.await_args.args[0] == "st_acc"
    assert mock_build.await_args.args[1] == "trend"


# ── Free draft returns creative suggestions ─────────────────────────────────


@pytest.mark.asyncio
async def test_free_draft_create_includes_creative_suggestions():
    app = FastAPI()
    app.include_router(free_routes.router, prefix="/api/free")
    app.include_router(analytics_routes.router, prefix="/api/analytics")

    store = AsyncMock()
    store._data = {}

    async def aput(ns, key, value):
        store._data[(ns, key)] = value

    async def aget(ns, key):
        val = store._data.get((ns, key))
        if val is None:
            return None
        item = MagicMock()
        item.value = val
        item.key = key
        return item

    store.aput = AsyncMock(side_effect=aput)
    store.aget = AsyncMock(side_effect=aget)
    store.asearch = AsyncMock(return_value=[])

    app.state.graph = MagicMock()
    app.state.graph.store = store
    # Fixture seeding stays on the internal service path; the product HTTP
    # import route is browser-only.
    sync = await sync_from_fixture("free_wire", store=store)
    assert sync.account_synced is True
    assert sync.source == "fixture"

    client = TestClient(app)

    with grant_test_user(app):
        resp = client.post(
            "/api/free/draft",
            json={
                "account_id": "free_wire",
                "title": "草稿标题",
                "body": "草稿正文",
                "hashtags": ["母婴"],
                "niche": "母婴",
            },
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["draft_id"]
    assert "creative_suggestions" in data
    assert data["creative_suggestions_count"] > 0
    # With imported data, not only cold_start
    cats = {s["category"] for s in data["creative_suggestions"]}
    assert "cold_start" not in cats or len(cats) > 1
    assert any(s.get("mode") == "free" for s in data["creative_suggestions"])
