"""Cycle-10: period date_type mapping, engagement scale normalize, account_id strip."""

from __future__ import annotations

import pytest

from backend.db.creator_stats import (
    _reset_memory_store,
    count_note_stats,
    get_account_stats,
    list_note_stats,
)
from backend.services.creator_stats.analyze import (
    analyze_notes,
    as_fraction_engagement_rate,
)
from backend.services.creator_stats.client import (
    CreatorStatsClient,
    normalize_period,
    period_to_date_type,
)
from backend.services.creator_stats.pipeline import sync_account_stats
from backend.services.creator_stats.suggestions import (
    get_suggestions_for_mode,
    suggestions_from_analysis,
)
from backend.services.creator_stats.types import NoteStats


@pytest.fixture(autouse=True)
def _clear():
    _reset_memory_store()
    yield
    _reset_memory_store()


# ── Period → date_type ──────────────────────────────────────────────────────


def test_period_to_date_type_7d_vs_30d_vs_90d():
    """90d must NOT map to the 7d type (bug: `period == '30d' else 1`)."""
    assert period_to_date_type("7d") == 1
    assert period_to_date_type("7") == 1
    assert period_to_date_type("weekly") == 1
    assert period_to_date_type("30d") == 2
    assert period_to_date_type("30") == 2
    assert period_to_date_type("90d") == 2  # longest known window, not 1
    assert period_to_date_type("90") == 2
    assert period_to_date_type("quarter") == 2
    assert period_to_date_type("") == 2
    assert period_to_date_type(None) == 2
    assert period_to_date_type("  90D  ") == 2


def test_normalize_period_canonical_labels():
    assert normalize_period("7") == "7d"
    assert normalize_period("weekly") == "7d"
    assert normalize_period("90") == "90d"
    assert normalize_period("3m") == "90d"
    assert normalize_period("garbage") == "30d"
    assert normalize_period(None) == "30d"


@pytest.mark.asyncio
async def test_dry_run_respects_caller_period_not_only_fixture_file():
    """CLI/API period must label stored overview even on fixture dry-run path."""
    from backend.db.creator_stats import get_account_stats
    from backend.services.creator_stats.pipeline import sync_account_stats

    r = await sync_account_stats("period_dry_7d", dry_run=True, period="7d")
    assert r.error is None
    assert r.account_synced is True
    acc = await get_account_stats("period_dry_7d")
    assert acc is not None
    assert acc.period == "7d"

    await sync_account_stats("period_dry_90d", dry_run=True, period="90d")
    acc2 = await get_account_stats("period_dry_90d")
    assert acc2 is not None
    assert acc2.period == "90d"


@pytest.mark.asyncio
async def test_fetch_all_sends_date_type_2_for_90d():
    """Live client must pass date_type=2 for period=90d (not 1)."""
    captured: list[dict] = []

    class CaptureTransport:
        async def get(self, url, *, headers, params=None):
            captured.append({"url": url, "params": dict(params or {})})
            if "/note/" in url or url.rstrip("/").endswith("analyze/list"):
                return 200, {
                    "notes": [
                        {
                            "note_id": "n90",
                            "title": "90d window note 治愈",
                            "views": 1000,
                            "likes": 50,
                            "comments": 5,
                            "collects": 10,
                            "shares": 0,
                            "tags": ["母婴"],
                        }
                    ]
                }
            return 200, {"views": 1000, "likes": 50, "note_count": 1, "fans": 10}

    client = CreatorStatsClient(cookie="sess=1", transport=CaptureTransport())
    bundle = await client.fetch_all("acc90", period="90d")
    overview_calls = [c for c in captured if "account" in c["url"] or c["url"].endswith("base")]
    assert overview_calls, captured
    assert overview_calls[0]["params"].get("date_type") == 2
    assert bundle.account.period == "90d"
    assert len(bundle.notes) == 1


# ── Engagement fraction normalize ───────────────────────────────────────────


def test_as_fraction_engagement_rate():
    assert as_fraction_engagement_rate(0.1571) == 0.1571
    assert as_fraction_engagement_rate(15.71) == 0.1571
    assert as_fraction_engagement_rate(100) == 1.0
    assert as_fraction_engagement_rate(0) == 0.0
    assert as_fraction_engagement_rate(-3) == 0.0
    assert as_fraction_engagement_rate(None) == 0.0


def test_analyze_notes_coerces_percent_scale_rates():
    """Hand-built / legacy rows with percent engagement must not avg to 15.0."""
    notes = [
        NoteStats(
            note_id="p1",
            account_id="a",
            title="慢慢来也很好治愈陪伴",
            views=1000,
            likes=150,
            engagement_rate=15.0,  # percent scale bug input
            tags=["母婴"],
        ),
        NoteStats(
            note_id="p2",
            account_id="a",
            title="5个方法干货清单",
            views=500,
            likes=50,
            engagement_rate=0.10,  # already fraction
            tags=["干货"],
        ),
    ]
    result = analyze_notes(notes, "a")
    assert result.cold_start is False
    assert result.avg_engagement_rate <= 1.0
    # After coerce: 0.15 and 0.10 → avg 0.125
    assert abs(result.avg_engagement_rate - 0.125) < 1e-6
    # Display-style check used by suggestions
    text = f"{result.avg_engagement_rate:.2%}"
    assert text == "12.50%"
    assert notes[0].engagement_rate == 0.15  # mutated to fraction


def test_suggestions_avg_rate_display_sane_with_percent_input():
    notes = [
        NoteStats(
            note_id="s1",
            account_id="a",
            title="治愈日常",
            views=200,
            likes=30,
            engagement_rate=12.5,
            tags=["生活"],
        )
    ]
    analysis = analyze_notes(notes, "a")
    sug = suggestions_from_analysis(analysis, notes, mode="free")
    free = sug["free"]
    assert free
    summary = next(s for s in free if s.category == "timing")
    # Must not say "1250.00%" from raw percent scale
    assert "1250" not in summary.advice
    assert analysis.avg_engagement_rate == 0.125


# ── account_id strip on lookup ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_and_count_strip_account_id_whitespace():
    from backend.db.creator_stats import get_note_stats

    await sync_account_stats("  strip_me  ", dry_run=True)
    notes = await list_note_stats(" strip_me ")
    assert len(notes) == 5
    assert await count_note_stats("  strip_me") == 5
    acc = await get_account_stats(" strip_me ")
    assert acc is not None
    assert acc.account_id == "strip_me"
    assert acc.note_count == 5
    # get_note_stats must strip too (analytics_reader path)
    nid = notes[0].note_id
    one = await get_note_stats(" strip_me ", f" {nid} ")
    assert one is not None
    assert one.note_id == nid
    assert await get_note_stats("", nid) is None
    assert await get_note_stats("strip_me", "") is None


@pytest.mark.asyncio
async def test_suggestions_for_mode_after_import_uses_real_notes():
    await sync_account_stats("sug_real", dry_run=True)
    items = await get_suggestions_for_mode("sug_real", "FREE")  # type: ignore[arg-type]
    assert items
    assert all(s.mode == "free" for s in items)
    assert any(s.category != "cold_start" for s in items)
    # Evidence must reference fixture-driven metrics, not placeholder theater
    joined = " ".join(s.advice for s in items)
    assert "sug_real" in joined or "互动" in joined or "话题" in joined
