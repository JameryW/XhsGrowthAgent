"""Wiring tests for the Phase-2 services (outcome, DM gate, bandit tool)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.services.creator_stats.analyze import analyze_notes
from backend.services.creator_stats.types import NoteStats
from backend.services.dm_qualification import QualificationFSM
from backend.services.xhs_engagement import BLOCKED, XHSEngagement

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def _stats(note_id: str, *, age_hours: float, collects: int) -> NoteStats:
    return NoteStats(
        note_id=note_id,
        account_id="acct",
        title=note_id,
        views=1_000,
        collects=collects,
        published_at=(NOW - timedelta(hours=age_hours)).isoformat(),
    )


def test_analyze_notes_exposes_outcome_learning() -> None:
    notes = [_stats(f"old-{index}", age_hours=24 * 20, collects=5) for index in range(10)]
    notes.extend(_stats(f"new-{index}", age_hours=24 * 3, collects=100) for index in range(3))

    result = analyze_notes(notes, "acct", now=NOW)

    assert result.cold_start is False
    assert result.outcome_learning["mature"] is True
    assert result.outcome_learning["promotable"] is True
    assert result.to_dict()["outcome_learning"]["mature_count"] == 13
    assert result.distribution["note_count"] == 13
    assert result.distribution["followers"] == 0
    assert result.to_dict()["distribution"] == result.distribution


@pytest.mark.asyncio
async def test_send_dm_blocks_before_the_effect_ledger_when_slots_are_incomplete() -> None:
    engagement = XHSEngagement()

    result = await engagement.send_dm(
        "user-1",
        "您好，请问有什么可以帮您？",
        qualification=QualificationFSM(),
    )

    assert result["status"] == BLOCKED
    assert result["error_code"] == "qualification_gate"


@pytest.mark.asyncio
async def test_ab_test_manager_returns_bandit_and_canary_decision() -> None:
    from backend.tools.xhs.publisher import ab_test_manager

    result = await ab_test_manager.ainvoke(
        {
            "base_post_id": "post-1",
            "variant_titles": ["A", "B"],
            "observations": [
                {"variant_id": "v0", "impressions": 100, "conversions": 5},
                {"variant_id": "v1", "impressions": 100, "conversions": 30},
            ],
        }
    )

    assert result["bandit"]["status"] == "ready_for_canary"
    assert result["bandit"]["leader"] == "v1"
    assert result["canary"]["enabled"] is True
