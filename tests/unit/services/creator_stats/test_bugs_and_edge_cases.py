"""Regression tests for bugs found in creator-stats pipeline review."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import analytics as analytics_routes
from backend.db.creator_stats import _reset_memory_store, list_note_stats
from backend.services.creator_stats.analyze import (
    _infer_title_formula,
    analyze_notes,
    run_analysis,
)
from backend.services.creator_stats.client import CreatorStatsClient, FixtureTransport
from backend.services.creator_stats.normalize import (
    normalize_bundle,
    normalize_note,
    normalize_note_list,
)
from backend.services.creator_stats.pipeline import sync_account_stats, sync_from_fixture
from backend.services.creator_stats.types import NoteStats
from backend.services.niche_resolver import infer_niche_from_notes


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


def _make_store() -> AsyncMock:
    store = AsyncMock()
    store._data: dict = {}

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

    async def asearch(ns, query="", limit=5, filter=None):
        items = []
        for (n, k), v in store._data.items():
            if n != ns:
                continue
            item = MagicMock()
            item.value = v
            item.key = k
            items.append(item)
        return items[:limit]

    store.aput = AsyncMock(side_effect=aput)
    store.aget = AsyncMock(side_effect=aget)
    store.asearch = AsyncMock(side_effect=asearch)
    return store


# ── Silent fixture pollution ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_live_sync_without_cookie_errors_and_does_not_write():
    """Regression: dry_run=False + empty cookie used to silently import fixture."""
    result = await sync_account_stats("real_user_acc", cookie="", dry_run=False)
    assert result.error is not None
    assert "cookie" in result.error.lower() or "dry_run" in result.error
    assert result.notes_imported == 0
    assert await list_note_stats("real_user_acc") == []


@pytest.mark.asyncio
async def test_dry_run_still_uses_fixture():
    result = await sync_account_stats("dry_acc", dry_run=True)
    assert result.error is None
    assert result.notes_imported == 5
    assert result.source == "fixture"


@pytest.mark.asyncio
async def test_injected_client_used_without_cookie_when_not_dry_run():
    payload_account = {"view_count": 9, "like_count": 1}
    payload_notes = [
        {
            "note_id": "injected_1",
            "title": "注入笔记",
            "view_count": 100,
            "like_count": 10,
            "comment_count": 1,
            "collect_count": 2,
            "share_count": 0,
        }
    ]
    client = CreatorStatsClient(
        cookie="",
        transport=FixtureTransport(account_payload=payload_account, notes_payload=payload_notes),
    )
    result = await sync_account_stats("inj_acc", dry_run=False, client=client)
    assert result.error is None
    assert result.notes_imported == 1
    notes = await list_note_stats("inj_acc")
    assert notes[0].note_id == "injected_1"
    assert notes[0].views == 100


# ── Deposit counts honesty ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_analysis_with_store_reports_real_deposits():
    await sync_from_fixture("dep_yes")
    notes = await list_note_stats("dep_yes")
    store = _make_store()
    analysis = await run_analysis(notes, "dep_yes", store=store)
    assert analysis.styles_deposited >= 1
    assert analysis.materials_deposited >= 1
    assert analysis.plays_deposited >= 1
    assert any(ns[2] == "style_dna" for (ns, _k) in store._data)


# ── Fixture-only service path / browser-only API route ─────────────────────


@pytest.mark.asyncio
async def test_fixture_service_analyze_false_skips_analysis_but_persists():
    """Fixture behavior stays below the HTTP product route for offline tests."""
    result = await sync_from_fixture("api_no_an", run_creative_analysis=False)

    assert result.account_synced is True
    assert result.notes_imported == 5
    assert result.analysis is None
    assert result.suggestions == {}
    assert await list_note_stats("api_no_an")


@pytest.mark.asyncio
async def test_api_browser_sync_requires_bound_browser_even_with_legacy_fields():
    await sync_from_fixture("api_live_empty", run_creative_analysis=False)
    before = await list_note_stats("api_live_empty")

    app = FastAPI()
    app.include_router(analytics_routes.router, prefix="/api/analytics")
    app.state.graph = MagicMock()
    app.state.graph.store = None
    client = TestClient(app)

    with (
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "backend.services.creator_stats.pipeline.sync_account_stats",
            new_callable=AsyncMock,
        ) as sync,
    ):
        resp = client.post(
            "/api/analytics/creator-stats/sync",
            json={
                "account_id": "api_live_empty",
                "dry_run": True,
                "cookie": "legacy-cookie",
            },
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ok"] is False
    assert "浏览器会话" in data["error"]
    assert data["source"] == "creator_statistics"
    assert data["notes_imported"] == 0
    sync.assert_not_awaited()
    after = await list_note_stats("api_live_empty")
    assert [note.note_id for note in after] == [note.note_id for note in before]


def test_api_browser_sync_ignores_legacy_fields_and_uses_bound_browser():
    app = FastAPI()
    app.include_router(analytics_routes.router, prefix="/api/analytics")
    app.state.graph = MagicMock()
    app.state.graph.store = None
    client = TestClient(app)

    with (
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new_callable=AsyncMock,
            return_value="http://127.0.0.1:9225",
        ),
        patch(
            "backend.services.creator_stats.pipeline.sync_account_stats",
            new_callable=AsyncMock,
            return_value=MagicMock(
                account_id="api_browser",
                account_synced=True,
                error=None,
                analysis=None,
                to_dict=lambda: {
                    "account_id": "api_browser",
                    "notes_imported": 2,
                    "notes_updated": 0,
                    "account_synced": True,
                    "analysis": None,
                    "suggestions": {},
                    "source": "creator_statistics",
                    "error": None,
                    "niche_resolution": None,
                },
            ),
        ) as sync,
    ):
        resp = client.post(
            "/api/analytics/creator-stats/sync",
            json={
                "account_id": "api_browser",
                "dry_run": True,
                "cookie": "legacy-cookie",
            },
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ok"] is True
    assert data["source"] == "creator_statistics"
    sync.assert_awaited_once_with(
        "api_browser",
        cookie="",
        dry_run=False,
        store=None,
        period="30d",
        run_creative_analysis=True,
        cdp_endpoint="http://127.0.0.1:9225",
    )


def test_ai_and_software_titles_infer_tech_niche():
    result = infer_niche_from_notes(
        [
            {"title": "AI模型工具如何辅助内容创作"},
            {"title": "Claude Code 和 Codex 的编程体验"},
            {"title": "GPT 与 Gemini 大模型怎么选"},
        ]
    )

    assert result.niche == "数码"
    assert result.source == "inferred"
    assert result.cold_start is False


def test_ai_keyword_does_not_match_inside_unrelated_english_words():
    result = infer_niche_from_notes([{"title": "Daily routine recap"}])

    assert result.niche == ""
    assert result.source == "cold_start"
    assert result.cold_start is True


# ── Normalize edge cases ────────────────────────────────────────────────────


def test_int_field_accepts_float_string_and_commas():
    note = normalize_note(
        {
            "note_id": "n_float",
            "title": "t",
            "view_count": "1,234.0",
            "like_count": "50.0",
            "comment_count": 3,
        },
        "acc",
    )
    assert note is not None
    assert note.views == 1234
    assert note.likes == 50


def test_normalize_skips_notes_without_id():
    notes = normalize_note_list(
        [{"title": "no id", "view_count": 1}, {"note_id": "ok", "view_count": 2}],
        "acc",
    )
    assert len(notes) == 1
    assert notes[0].note_id == "ok"


def test_normalize_nested_interact_info_and_envelope():
    raw = {
        "success": True,
        "data": {
            "note_id": "nested1",
            "title": "嵌套指标",
            "interact_info": {
                "view_count": 500,
                "like_count": 40,
                "comment_count": 4,
                "collect_count": 8,
                "share_count": 2,
            },
        },
    }
    # list path with envelope-like item
    notes = normalize_note_list([raw["data"]], "acc")
    assert len(notes) == 1
    assert notes[0].views == 500
    assert notes[0].likes == 40
    assert notes[0].engagement_rate == round((40 + 4 + 8 + 2) / 500, 4)


def test_normalize_bundle_unix_ms_publish_time():
    bundle = normalize_bundle(
        {},
        [
            {
                "note_id": "ts1",
                "title": "时间戳",
                "view_count": 10,
                "like_count": 1,
                "publish_time": 1_717_200_000_000,  # ms
            }
        ],
        "acc_ts",
    )
    assert bundle.notes[0].published_at
    assert "2024" in bundle.notes[0].published_at or "T" in bundle.notes[0].published_at


# ── Title formula heuristics ────────────────────────────────────────────────


def test_title_formula_does_not_match_bare_yi():
    # "一起" / common 一 must not force 数字+痛点
    assert _infer_title_formula("一起来看宝宝日常") != "数字+痛点"
    assert _infer_title_formula("5个方法解决夜醒") == "数字+痛点"
    assert _infer_title_formula("有没有发现午睡更香") == "疑问钩子"


def test_analyze_findings_include_real_metric_numbers():
    notes = [
        NoteStats(
            note_id="a",
            account_id="x",
            title="5个方法干货清单",
            views=1000,
            likes=100,
            comments=10,
            collects=20,
            shares=5,
            engagement_rate=0.135,
            tags=["干货"],
            content_type="note",
        ),
        NoteStats(
            note_id="b",
            account_id="x",
            title="避雷别买这款",
            views=200,
            likes=5,
            comments=1,
            collects=1,
            shares=0,
            engagement_rate=0.035,
            tags=["避雷"],
            content_type="video",
        ),
    ]
    analysis = analyze_notes(notes, "x")
    best = next(f for f in analysis.findings if f.finding_type == "best_note")
    assert "1000" in best.evidence or "浏览1000" in best.evidence
    assert "a" in best.note_ids
    assert analysis.avg_engagement_rate == round((0.135 + 0.035) / 2, 4)


# ── Client envelope / failure ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_unwraps_success_envelope():
    transport = FixtureTransport(
        account_payload={"success": True, "data": {"view_count": 77, "like_count": 7}},
        notes_payload={
            "success": True,
            "data": {
                "list": [
                    {
                        "note_id": "env1",
                        "title": "信封",
                        "view_count": 11,
                        "like_count": 2,
                    }
                ]
            },
        },
    )
    # FixtureTransport returns payload as-is; client unwraps
    # For notes, nested data.list needs unwrap then normalize — fetch_note_list
    # unwraps to {"list": [...]}, fetch_all extracts list. Good.
    client = CreatorStatsClient(cookie="c", transport=transport)
    # account path returns envelope; unwrap → dict with view_count
    overview = await client.fetch_account_overview()
    assert overview["view_count"] == 77
    notes_data = await client.fetch_note_list()
    assert isinstance(notes_data, dict)
    bundle = await client.fetch_all("env_acc")
    assert bundle.account.views == 77
    assert len(bundle.notes) == 1
    assert bundle.notes[0].note_id == "env1"
