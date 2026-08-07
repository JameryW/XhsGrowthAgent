"""Resilience (analysis-after-persist) + agent/CLI/free wiring tests."""

from __future__ import annotations

import asyncio
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
from backend.services.creator_stats.analyze import analyze_notes, deposit_from_analysis
from backend.services.creator_stats.normalize import (
    normalize_account_overview,
    normalize_bundle,
)
from backend.services.creator_stats.pipeline import import_bundle, sync_from_fixture
from backend.services.creator_stats.types import AnalysisResult, NoteStats

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


def test_normalize_bundle_prefers_notes_list_over_inflated_overview_note_count():
    """Live audit: overview note_count/publish_* can be 14 while Note Manager is 3."""
    notes_raw = [
        {
            "note_id": "n1",
            "title": "今天的睡姿，你给打几分？",
            "view_count": 109,
            "like_count": 9,
            "comment_count": 0,
            "collect_count": 4,
            "share_count": 0,
        },
        {
            "note_id": "n2",
            "title": "Vlog｜简单快乐，公园里的30分钟",
            "view_count": 22,
            "like_count": 5,
            "collect_count": 2,
        },
        {
            "note_id": "n3",
            "title": "最美的风景就是不经意之间",
            "view_count": 18,
            "like_count": 6,
            "collect_count": 3,
        },
    ]
    # Inflated overview aliases that previously won and wrote note_count=14.
    account_raw = {
        "view_count": 3822,
        "like_count": 108,
        "comment_count": 9,
        "collect_count": 57,
        "share_count": 5,
        "fans_count": 8,
        "note_count": 14,
        "publish_count": 14,
        "publish_note_num": 14,
    }
    bundle = normalize_bundle(account_raw, notes_raw, "acc_note_count_fix")
    assert len(bundle.notes) == 3
    assert bundle.account.note_count == 3
    # Other metrics stay on the overview fields (not zeroed by reconcile).
    assert bundle.account.views == 3822
    assert bundle.account.likes == 108
    assert bundle.account.fans == 8
    assert bundle.notes[0].views == 109


def test_normalize_bundle_sets_note_count_from_list_when_overview_missing():
    bundle = normalize_bundle(
        {"view_count": 10},
        [{"note_id": "a", "view_count": 1}, {"note_id": "b", "view_count": 2}],
        "acc_note_count_fill",
    )
    assert bundle.account.note_count == 2
    assert bundle.account.views == 10


def test_normalize_bundle_keeps_agreeing_note_count():
    bundle = normalize_bundle(
        {"view_count": 5, "note_count": 1},
        [{"note_id": "only", "view_count": 5, "like_count": 1}],
        "acc_note_count_agree",
    )
    assert len(bundle.notes) == 1
    assert bundle.account.note_count == 1


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


# ── deposit_from_analysis writes concurrently via gather ─────────────────────


def _overlapping(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """True if the two [start, finish] windows overlap in time."""
    return a[0] <= b[1] and b[0] <= a[1]


@pytest.mark.asyncio
async def test_deposit_from_analysis_gathers_writes():
    """deposit_style + deposit_play + deposit_material run concurrently via gather.

    Uses the call-overlap discriminator (#519/#520 pattern): each mocked
    CreativeMemory deposit records a start/finish window and yields via
    asyncio.sleep(0). Under gather the writes overlap; under serial ``await``
    loops the intervals are disjoint. This avoids patching asyncio.gather
    globally (the shared-asyncio-module leak trap from #515). deposit_* methods
    self-isolate (try/except → logger.warning), so no _safe_* wrapper is used —
    the bare coros are gathered directly.
    """
    notes = [
        NoteStats(
            note_id="n1",
            account_id="acct_gather",
            title="3个方法让你轻松搞定",
            body_text="慢慢来比较快",
            views=1000,
            likes=200,
            comments=50,
            collects=50,
            engagement_rate=0.30,
        ),
        NoteStats(
            note_id="n2",
            account_id="acct_gather",
            title="避雷清单｜这些千万别买",
            body_text="姐妹们冲",
            views=800,
            likes=120,
            comments=30,
            collects=40,
            engagement_rate=0.24,
        ),
    ]
    analysis = analyze_notes(notes, "acct_gather")
    assert not analysis.cold_start

    windows: list[dict] = []

    async def _tracked_deposit(self_cm, payload):
        start = asyncio.get_event_loop().time()
        # Per-call slot captured by closure (not a shared-list index) so each
        # concurrent deposit updates its own finish without racing on the list.
        slot: dict = {
            "id": payload.get("style_id") or payload.get("play_id") or payload.get("material_id"),
            "start": start,
            "finish": start,
        }
        windows.append(slot)
        await asyncio.sleep(0.01)  # real suspension so sibling gather tasks overlap
        slot["finish"] = asyncio.get_event_loop().time()

    with (
        patch("backend.memory.creative.CreativeMemory.deposit_style", new=_tracked_deposit),
        patch("backend.memory.creative.CreativeMemory.deposit_play", new=_tracked_deposit),
        patch("backend.memory.creative.CreativeMemory.deposit_material", new=_tracked_deposit),
    ):
        result = await deposit_from_analysis(analysis, notes, store=None, account_niche="母婴")

    # 1 style + 1 play + 2 top notes × (1 title + 1 hook) = 6 deposits
    assert len(windows) == 6
    assert result.styles_deposited == 1
    assert result.plays_deposited == 1
    assert result.materials_deposited == 4

    # At least one pair of deposits must overlap in time (concurrent gather,
    # not serial). Serial awaits produce strictly disjoint windows.
    intervals = [(w["start"], w["finish"]) for w in windows]
    any_overlap = any(
        _overlapping(intervals[i], intervals[j])
        for i in range(len(intervals))
        for j in range(i + 1, len(intervals))
    )
    assert any_overlap, "deposit_* writes must overlap (concurrent gather), not run serially"


@pytest.mark.asyncio
async def test_deposit_from_analysis_cold_start_no_writes():
    """Cold-start early-return path is unchanged: no deposits, zero counters."""
    analysis = AnalysisResult(account_id="acct_cold", cold_start=True)

    async def _fail_deposit(*args, **kwargs):
        raise AssertionError("no deposit should run on cold-start path")

    with (
        patch("backend.memory.creative.CreativeMemory.deposit_style", new=_fail_deposit),
        patch("backend.memory.creative.CreativeMemory.deposit_play", new=_fail_deposit),
        patch("backend.memory.creative.CreativeMemory.deposit_material", new=_fail_deposit),
    ):
        result = await deposit_from_analysis(analysis, [], store=None)

    assert result.cold_start is True
    assert result.styles_deposited == 0
    assert result.materials_deposited == 0
    assert result.plays_deposited == 0


@pytest.mark.asyncio
async def test_deposit_from_analysis_counters_match_top_notes():
    """Counters computed from local iteration, not deposit returns.

    With one top note (title+snippet) the expected counts are style=1, play=1,
    materials=2 (one title entry + one hook entry). A second top note whose
    title matches its snippet still yields 2 materials (title + hook share
    content but use distinct material_ids).
    """
    notes = [
        NoteStats(
            note_id="solo",
            account_id="acct_count",
            title="绝绝子｜宝藏好物分享",
            body_text="",
            views=500,
            likes=80,
            comments=10,
            collects=20,
            engagement_rate=0.22,
        ),
    ]
    analysis = analyze_notes(notes, "acct_count")

    async def _noop_deposit(self_cm, payload):
        return None

    with (
        patch("backend.memory.creative.CreativeMemory.deposit_style", new=_noop_deposit),
        patch("backend.memory.creative.CreativeMemory.deposit_play", new=_noop_deposit),
        patch("backend.memory.creative.CreativeMemory.deposit_material", new=_noop_deposit),
    ):
        result = await deposit_from_analysis(analysis, notes, store=None)

    assert result.styles_deposited == 1
    assert result.plays_deposited == 1
    assert result.materials_deposited == 2
