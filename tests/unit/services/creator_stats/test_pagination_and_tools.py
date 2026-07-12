"""Pagination clamps, cookie strip, pattern confidence, report niche line."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.creator_stats import _reset_memory_store
from backend.services.creator_stats.client import CreatorStatsClient
from backend.services.creator_stats.pipeline import sync_account_stats, sync_from_fixture
from backend.tools.xhs import analytics as analytics_tools


@pytest.fixture(autouse=True)
def _clear():
    _reset_memory_store()
    yield
    _reset_memory_store()


@pytest.mark.asyncio
async def test_fetch_note_list_clamps_page_size_and_page_num():
    seen: list[dict] = []

    class T:
        async def get(self, url, *, headers, params=None):
            seen.append(dict(params or {}))
            return 200, {"list": []}

    client = CreatorStatsClient(cookie="c", transport=T())
    await client.fetch_note_list(page_num=0, page_size=0)
    assert seen[0]["page_num"] == 1
    assert seen[0]["page_size"] == 1

    await client.fetch_note_list(page_num=-3, page_size=500)
    assert seen[1]["page_num"] == 1
    assert seen[1]["page_size"] == 100  # capped


@pytest.mark.asyncio
async def test_fetch_all_with_page_size_zero_does_not_loop_forever():
    """page_size<=0 used to never stop on non-empty pages (len < 0 never true)."""
    calls = {"n": 0}

    class T:
        async def get(self, url, *, headers, params=None):
            if "/note/" in url:
                calls["n"] += 1
                # Always return one item — without clamp, page_size=0 never ends early
                return 200, {
                    "list": [
                        {
                            "note_id": f"n{calls['n']}",
                            "view_count": 1,
                            "like_count": 0,
                        }
                    ]
                }
            return 200, {"view_count": 1}

    client = CreatorStatsClient(cookie="c", transport=T())
    bundle = await client.fetch_all("pg0", page_size=0, max_pages=5)
    # With clamp page_size=1, each page returns 1 item == page_size so continues
    # until max_pages — still bounded.
    assert calls["n"] <= 5
    assert len(bundle.notes) <= 5


@pytest.mark.asyncio
async def test_cookie_whitespace_only_rejected_for_live_sync():
    r = await sync_account_stats("ws", cookie="   \t  ", dry_run=False)
    assert r.error is not None
    assert "cookie" in r.error.lower()
    assert r.notes_imported == 0


@pytest.mark.asyncio
async def test_pattern_detector_confidence_not_saturated_at_low_engagement():
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=None),
        patch("backend.db.accounts.update_account", new_callable=AsyncMock),
    ):
        await sync_from_fixture("pat_conf")
    patterns = await analytics_tools.pattern_detector.ainvoke(
        {"time_range": "30d", "account_id": "pat_conf"}
    )
    assert patterns
    assert patterns[0]["pattern"] != "示例模式"
    assert "score" in patterns[0]
    # Best note has sample_count=1 among 5 notes → confidence 0.2 not 1.0
    best = next(p for p in patterns if p["pattern"].startswith("best_note:"))
    assert best["confidence"] < 1.0
    assert best["confidence"] == pytest.approx(1 / 5, abs=0.01)


@pytest.mark.asyncio
async def test_report_generator_includes_niche_when_account_bound():
    acc = MagicMock()
    acc.niche = "母婴"
    acc.niche_source = "inferred"
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=acc),
        patch("backend.db.accounts.update_account", new_callable=AsyncMock),
    ):
        await sync_from_fixture("rep_niche")
        # After sync, report still reads get_account for niche line
        report = await analytics_tools.report_generator.ainvoke(
            {"account_id": "rep_niche", "period": "weekly"}
        )
    assert "导入笔记" in report
    assert "赛道绑定" in report
    assert "母婴" in report
