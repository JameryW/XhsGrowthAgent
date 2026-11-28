"""``analysis.topic_scorer`` exposes the GEO block only when switched on (#37).

The tool already reads the ranking hits and keyword rows that the signal needs,
so this wiring must add no request and must leave the payload byte-identical
with the switch off — a default deployment cannot tell phase 21 happened.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.services.geo_signals import GEO_SCORING_ENV
from backend.tools.analysis.topic_scorer import topic_scorer

MODULE = "backend.services.xhs_client.client_for_account"


class _Post:
    def __init__(self, likes: int, comments: int = 5, note_id: str = "n1") -> None:
        self.note_id = note_id
        self.note_url = f"https://x/{note_id}"
        self.title = "露营"
        self.desc = "露营笔记"
        self.likes = likes
        self.comments = comments
        self.collects = likes // 2
        self.author = "someone"
        self.published_at = ""


class _Client:
    """The two reads the scorer makes, plus the public read precondition."""

    def __init__(self, posts: list[_Post], keyword_rows: list[dict[str, Any]]) -> None:
        self._posts = posts
        self._keyword_rows = keyword_rows
        self.can_read = True
        self.cookie = ""
        self.user_id = ""
        self.account_id = ""
        self.search_calls = 0
        self.keyword_calls = 0
        self.closed = False

    async def search_posts(self, keyword: str, limit: int = 50) -> list[_Post]:
        self.search_calls += 1
        return self._posts

    async def monitor_keywords(self, keywords: list[str]) -> list[dict[str, Any]]:
        self.keyword_calls += 1
        return self._keyword_rows

    async def close(self) -> None:
        self.closed = True


def _patch_client(monkeypatch, client: _Client) -> _Client:
    async def _factory(account_id: str = "") -> _Client:
        client.account_id = account_id
        return client

    monkeypatch.setattr(MODULE, _factory)
    return client


@pytest.mark.asyncio
async def test_switch_off_returns_no_geo_key(monkeypatch) -> None:
    monkeypatch.delenv(GEO_SCORING_ENV, raising=False)
    client = _patch_client(
        monkeypatch,
        _Client([_Post(100), _Post(80)], [{"keyword": "露营", "avg_likes": 90}]),
    )

    result = await topic_scorer.ainvoke({"topic": "露营", "keywords": ["露营装备清单"]})

    assert "geo" not in result
    assert client.search_calls == 1


@pytest.mark.asyncio
async def test_switch_on_adds_geo_without_extra_requests(monkeypatch) -> None:
    monkeypatch.setenv(GEO_SCORING_ENV, "1")
    client = _patch_client(
        monkeypatch,
        _Client([_Post(1000), _Post(80), _Post(60)], [{"keyword": "露营", "avg_likes": 900}]),
    )

    result = await topic_scorer.ainvoke({"topic": "露营", "keywords": ["露营装备清单"]})

    geo = result["geo"]
    assert geo["enabled"] is True
    assert geo["signals"]["post_count"] == 3
    assert geo["signals"]["supply_density"] == pytest.approx(0.3333)
    # Both reads happen regardless — the GEO block re-uses them.
    assert client.search_calls == 1
    assert client.keyword_calls == 1


@pytest.mark.asyncio
async def test_geo_block_survives_the_untrusted_tool_boundary(monkeypatch) -> None:
    """``topic_scorer`` is an external-content tool; the sanitiser must keep
    the additive ``geo`` mapping reachable by the agent."""
    monkeypatch.setenv(GEO_SCORING_ENV, "yes")
    _patch_client(monkeypatch, _Client([_Post(1000), _Post(70)], []))

    result = await topic_scorer.ainvoke({"topic": "露营"})

    geo = result["geo"]
    assert geo["best_keyword"] == "露营"
    assert isinstance(geo["recommendation"], str) and geo["recommendation"]
    assert [item["keyword"] for item in geo["candidates"]] == ["露营"]


@pytest.mark.asyncio
async def test_a_default_payload_keeps_every_existing_key(monkeypatch) -> None:
    """The GEO block is additive: nothing else may shift shape or value."""
    monkeypatch.delenv(GEO_SCORING_ENV, raising=False)
    _patch_client(monkeypatch, _Client([_Post(100)], [{"keyword": "露营", "avg_likes": 90}]))

    result = await topic_scorer.ainvoke({"topic": "露营"})

    assert set(result) >= {
        "topic",
        "heat_score",
        "potential_score",
        "score_breakdown",
        "data_metrics",
        "competition_level",
        "recommendation",
        "novelty",
        "collect_first",
    }
    assert result["topic"] == "露营"
    assert result["novelty"]["is_duplicate_risk"] is False
