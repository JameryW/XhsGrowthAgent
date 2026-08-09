"""Creator-stats client (mocked transport) + analysis/style deposit + modes."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.db.creator_stats import _reset_memory_store, list_note_stats
from backend.services.creator_stats.analyze import analyze_notes, run_analysis
from backend.services.creator_stats.audience import summarize_audience
from backend.services.creator_stats.client import (
    CREATOR_STATS_PAGE,
    CreatorStatsClient,
    CreatorStatsFetchError,
    FixtureTransport,
    _note_detail_id,
    _note_detail_snapshot,
)
from backend.services.creator_stats.pipeline import (
    load_fixture_payload,
    sync_account_stats,
    sync_from_creator_center,
    sync_from_fixture,
)
from backend.services.creator_stats.suggestions import (
    build_mode_creative_context,
    get_suggestions_for_mode,
    suggestions_from_analysis,
)
from backend.services.creator_stats.types import AccountStatsOverview, NoteStats

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "creator_stats_sample.json"


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


def _make_store() -> AsyncMock:
    store = AsyncMock()
    store._data: dict[tuple, dict] = {}

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


@pytest.mark.asyncio
async def test_client_fetch_all_with_fixture_transport():
    payload = load_fixture_payload(FIXTURE)
    transport = FixtureTransport(
        account_payload=payload["account"],
        notes_payload=payload["notes"],
    )
    client = CreatorStatsClient(cookie="web_session=fake", transport=transport)
    bundle = await client.fetch_all("acct_client")
    assert bundle.account.views == 128400
    assert len(bundle.notes) == 5
    assert all(n.note_id for n in bundle.notes)
    assert CREATOR_STATS_PAGE.startswith("https://creator.xiaohongshu.com/")


def test_note_detail_snapshot_normalizes_audience_dimensions():
    snapshot = _note_detail_snapshot(
        {
            "/api/galaxy/creator/datacenter/note/base": (
                200,
                {"data": {"view_count": 284, "note_info": {"title": "真实笔记"}}},
            ),
            "/api/galaxy/creator/datacenter/note/audience/source": (
                200,
                {"data": {"source": [{"title": "首页推荐", "value": 48}]}},
            ),
            "/api/galaxy/creator/datacenter/note/audience/source/detail": (
                200,
                {
                    "data": {
                        "gender": [{"title": "女性", "value": 48}],
                        "age": [{"title": "25-34", "value": 51}],
                    }
                },
            ),
            "/api/galaxy/creator/datacenter/note/analyze/audience/trend": (
                200,
                {"data": {"trend_list": [{"title": "10-11点", "value": 22}]}},
            ),
        }
    )

    assert snapshot["view_sources"] == [{"title": "首页推荐", "value": 48}]
    assert {row["dimension"] for row in snapshot["audience_profile"]} == {"gender", "age"}
    assert snapshot["audience_trend"][0]["value"] == 22
    assert snapshot["view_count"] == 284


def test_note_detail_id_accepts_page_and_api_query_names():
    assert (
        _note_detail_id("https://creator.xiaohongshu.com/statistics/note-detail?noteId=n-1")
        == "n-1"
    )
    assert _note_detail_id("https://creator.xiaohongshu.com/api/detail?note_id=n-2") == "n-2"
    assert _note_detail_id("https://creator.xiaohongshu.com/api/detail?note-id=n-3") == "n-3"
    assert _note_detail_id("https://creator.xiaohongshu.com/api/detail") == ""


def test_audience_analysis_falls_back_to_per_note_breakdowns():
    account = AccountStatsOverview(account_id="audience")
    notes = [
        NoteStats(
            note_id="note-1",
            account_id="audience",
            view_sources=[{"title": "首页推荐", "value": 48}],
            audience_profile=[{"dimension": "gender", "title": "女性", "value": 48}],
        ),
        NoteStats(
            note_id="note-2",
            account_id="audience",
            view_sources=[{"title": "首页推荐", "value": 52}],
            audience_profile=[{"dimension": "gender", "title": "女性", "value": 50}],
        ),
    ]

    result = summarize_audience(account, notes)

    assert result["coverage"]["sources"] is True
    assert result["coverage"]["profile"] is True
    assert result["source_distribution"][0]["value"] == 50
    assert result["audience_profile"][0]["value"] == 49


@pytest.mark.asyncio
async def test_client_auth_failure_does_not_persist(caplog):
    class BadTransport:
        async def get(self, url, *, headers, params=None):
            return 401, {"success": False, "msg": "unauthorized"}

    client = CreatorStatsClient(cookie="bad", transport=BadTransport())
    client.aclose = AsyncMock()
    with pytest.raises(CreatorStatsFetchError):
        await client.fetch_account_overview()

    # sync_from_creator_center should return error and leave store empty
    with caplog.at_level(logging.WARNING, logger="xhs_growth.creator_stats.pipeline"):
        result = await sync_from_creator_center("acct_fail", cookie="bad", client=client)
    assert result.error is not None
    assert result.notes_imported == 0
    notes = await list_note_stats("acct_fail")
    assert notes == []
    assert "CreatorStatsFetchError: creator stats auth failed" in caplog.text
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_failure_preserves_existing_rows():
    # Seed existing data
    await sync_from_fixture("acct_keep")
    before = await list_note_stats("acct_keep")
    assert len(before) == 5

    class BoomTransport:
        async def get(self, url, *, headers, params=None):
            return 500, {"success": False, "msg": "server error"}

    client = CreatorStatsClient(cookie="x", transport=BoomTransport())
    result = await sync_from_creator_center("acct_keep", cookie="x", client=client)
    assert result.error is not None
    after = await list_note_stats("acct_keep")
    assert len(after) == 5
    assert {n.note_id for n in after} == {n.note_id for n in before}


@pytest.mark.asyncio
async def test_analysis_produces_data_backed_findings_not_placeholder():
    await sync_from_fixture("acct_an")
    notes = await list_note_stats("acct_an")
    analysis = analyze_notes(notes, "acct_an")
    assert analysis.cold_start is False
    assert analysis.note_count == 5
    assert analysis.avg_engagement_rate > 0
    assert analysis.findings
    # Must reference fixture performance (not only 示例)
    joined = " ".join(f.evidence + f.label for f in analysis.findings)
    assert "示例" not in joined or "示例模式" not in joined
    assert any(f.finding_type == "tone" for f in analysis.findings)
    assert any(f.finding_type == "best_note" for f in analysis.findings)
    # Top note from fixture should be high-engagement heal note
    assert "note_heal_001" in analysis.top_note_ids or any(
        "慢慢来" in f.label or "note_heal_001" in f.note_ids for f in analysis.findings
    )


@pytest.mark.asyncio
async def test_run_analysis_deposits_style_dna():
    await sync_from_fixture("acct_dep")
    notes = await list_note_stats("acct_dep")
    store = _make_store()
    analysis = await run_analysis(notes, "acct_dep", store=store)
    assert analysis.styles_deposited >= 1
    assert analysis.materials_deposited >= 1
    assert analysis.plays_deposited >= 1
    # Durable style rows in store
    style_keys = [k for (ns, k), v in store._data.items() if ns[2] == "style_dna"]
    assert style_keys
    style_val = next(v for (ns, k), v in store._data.items() if ns[2] == "style_dna")
    assert style_val.get("tone")
    assert style_val.get("engagement_rate", 0) > 0 or style_val.get("sample_count", 0) >= 1


@pytest.mark.asyncio
async def test_suggestions_for_all_modes_non_empty_with_data():
    result = await sync_from_fixture("acct_modes")
    assert result.analysis is not None
    notes = await list_note_stats("acct_modes")
    all_sugs = suggestions_from_analysis(result.analysis, notes)
    for mode in ("trend", "brief", "free"):
        items = all_sugs[mode]
        assert items, f"expected non-empty suggestions for {mode}"
        assert any(s.category != "cold_start" for s in items)
        # Must reference fixture metrics / note ids / real evidence
        blob = " ".join(s.advice + s.evidence + s.title for s in items)
        assert "示例模式" not in blob
        assert (
            "note_" in blob
            or "互动" in blob
            or "治愈" in blob
            or "母婴" in blob
            or str(result.analysis.avg_engagement_rate) in blob
            or "0." in blob
        )


@pytest.mark.asyncio
async def test_cold_start_suggestions_defined_without_raise():
    for mode in ("trend", "brief", "free"):
        items = await get_suggestions_for_mode("acct_empty", mode)  # type: ignore[arg-type]
        assert items
        assert all(s.category == "cold_start" for s in items)
        ctx = await build_mode_creative_context("acct_empty", mode)  # type: ignore[arg-type]
        assert "暂无" in ctx or "冷启动" in ctx or "创作" in ctx


@pytest.mark.asyncio
async def test_sync_account_stats_dry_run_entry_twice():
    r1 = await sync_account_stats("acct_entry2", dry_run=True)
    r2 = await sync_account_stats("acct_entry2", dry_run=True)
    assert r1.error is None and r2.error is None
    assert r1.notes_imported == 5
    assert r2.notes_updated == 5  # second run updates
    assert r1.account_synced and r2.account_synced
    assert "trend" in r1.suggestions and r1.suggestions["trend"]
    assert "brief" in r1.suggestions and "free" in r1.suggestions
