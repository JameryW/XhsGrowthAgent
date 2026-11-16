"""APMD policy anchor is persisted across creator-stats analysis runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from langgraph.store.memory import InMemoryStore

from backend.services.creator_stats.analyze import (
    _policy_anchor_namespace,
    run_analysis,
)
from backend.services.creator_stats.types import NoteStats

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def _notes() -> list[NoteStats]:
    return [
        NoteStats(
            note_id=f"n{index}",
            account_id="acct",
            title=f"笔记 {index}",
            views=1_000,
            collects=10,
            published_at=(NOW - timedelta(days=3)).isoformat(),
            content_type=("图文", "视频", "合集")[index % 3],
        )
        for index in range(13)
    ]


@pytest.mark.asyncio
async def test_policy_anchor_is_written_once_and_reused() -> None:
    store = InMemoryStore()
    notes = _notes()

    first = await run_analysis(notes, "acct", store=store, now=NOW)
    assert first.policy_reset["should_reset"] is True
    assert first.policy_reset["reason"] == "no_anchor"
    anchor = await store.aget(_policy_anchor_namespace("acct"), "current")
    assert anchor is not None
    assert anchor.value["note_count"] == 13

    second = await run_analysis(notes, "acct", store=store, now=NOW + timedelta(days=1))
    assert second.policy_reset["should_reset"] is False
    assert second.policy_reset["reason"] == "anchor_valid"
