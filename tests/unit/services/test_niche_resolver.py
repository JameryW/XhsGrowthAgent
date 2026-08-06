"""Niche inference + manual override resolution tests."""

from __future__ import annotations

import asyncio

import pytest

from backend.db.creator_stats import _reset_memory_store, upsert_notes
from backend.services import niche_resolver
from backend.services.creator_stats.types import NoteStats
from backend.services.niche_resolver import (
    infer_niche_from_notes,
    resolve_account_niche,
    resolve_niche,
)


@pytest.fixture(autouse=True)
def _clear():
    _reset_memory_store()
    yield
    _reset_memory_store()


def test_infer_niche_from_maternal_fixture_notes():
    notes = [
        {
            "note_id": "1",
            "title": "慢慢来也很好：三岁宝宝的温柔日常陪伴",
            "tags": ["母婴", "育儿日常"],
        },
        {
            "note_id": "2",
            "title": "5个方法解决宝宝夜醒：儿科护士干货清单",
            "tags": ["母婴", "睡眠训练"],
        },
        {"note_id": "3", "title": "辅食工具分享", "tags": ["辅食"]},
    ]
    res = infer_niche_from_notes(notes)
    assert res.cold_start is False
    assert res.source == "inferred"
    assert res.niche == "母婴"
    assert res.confidence > 0
    assert any(c["niche"] == "母婴" for c in res.candidates)


def test_infer_beauty_from_titles():
    notes = [
        {"title": "夏日防晒测评：这款精华真的稳", "tags": ["护肤", "防晒"]},
        {"title": "新手底妆三步骤", "tags": ["美妆"]},
    ]
    res = infer_niche_from_notes(notes)
    assert res.niche == "美妆"
    assert res.source == "inferred"


def test_empty_notes_cold_start_no_raise():
    res = infer_niche_from_notes([])
    assert res.cold_start is True
    assert res.niche == ""
    assert res.source == "cold_start"
    assert "no_historical_notes" in res.evidence


def test_manual_wins_over_inferred_notes():
    notes = [{"title": "宝宝辅食", "tags": ["母婴"]}]
    res = resolve_niche(manual_niche="数码", notes=notes)
    assert res.source == "manual"
    assert res.niche == "数码"
    assert res.confidence == 1.0


def test_manual_fills_when_history_empty():
    res = resolve_niche(manual_niche="健身", notes=[])
    assert res.niche == "健身"
    assert res.source == "manual"
    assert res.cold_start is False


def test_account_bound_used_when_no_manual_no_infer():
    res = resolve_niche(
        manual_niche="",
        notes=[{"title": "天气真好"}],  # no keyword match
        account_bound_niche="旅行",
    )
    assert res.niche == "旅行"
    assert res.source == "account_bound"


def test_cold_start_default_when_nothing():
    res = resolve_niche(manual_niche="", notes=[], cold_start_default="母婴")
    assert res.cold_start is True
    assert res.niche == "母婴"
    assert res.source == "cold_start"


@pytest.mark.asyncio
async def test_resolve_account_niche_from_imported_stats():
    await upsert_notes(
        [
            NoteStats(
                note_id="n1",
                account_id="niche_acc",
                title="宝宝夜醒怎么办",
                tags=["母婴", "育儿"],
                views=100,
            ),
            NoteStats(
                note_id="n2",
                account_id="niche_acc",
                title="辅食添加时间表",
                tags=["辅食"],
                views=50,
            ),
        ]
    )
    res = await resolve_account_niche("niche_acc", manual_niche="")
    assert res.niche == "母婴"
    assert res.source == "inferred"


@pytest.mark.asyncio
async def test_resolve_account_manual_override_with_imported_notes():
    await upsert_notes(
        [
            NoteStats(
                note_id="n1",
                account_id="niche_man",
                title="宝宝日常",
                tags=["母婴"],
                views=10,
            )
        ]
    )
    res = await resolve_account_niche("niche_man", manual_niche="美妆")
    assert res.niche == "美妆"
    assert res.source == "manual"


def _make_fake_gather():
    """Record awaitables passed to asyncio.gather, then delegate to real gather.

    Captures the real ``asyncio.gather`` up front — ``monkeypatch.setattr`` on
    ``niche_resolver.asyncio.gather`` mutates the shared ``asyncio`` module
    attribute, so the fake must not re-resolve ``asyncio.gather`` (else
    infinite recursion).
    """
    calls: list[tuple] = []
    real_gather = asyncio.gather

    async def fake_gather(*awaitables, **kwargs):
        calls.append(awaitables)
        return await real_gather(*awaitables, **kwargs)

    return fake_gather, calls


@pytest.mark.asyncio
async def test_resolve_account_niche_gathers_when_notes_none(monkeypatch):
    """notes=None path: get_account + load_notes_for_account gathered concurrently."""
    await upsert_notes(
        [
            NoteStats(
                note_id="g1",
                account_id="niche_gather",
                title="宝宝辅食添加时间表",
                tags=["母婴"],
                views=100,
            )
        ]
    )

    fake_gather, gather_calls = _make_fake_gather()
    monkeypatch.setattr(niche_resolver.asyncio, "gather", fake_gather)

    res = await resolve_account_niche("niche_gather", manual_niche="")

    assert res.niche == "母婴"
    assert res.source == "inferred"
    # Exactly one gather call with two awaitables (get_account path + load_notes_for_account)
    assert len(gather_calls) == 1
    assert len(gather_calls[0]) == 2
    # Discriminate by __qualname__: _fetch_account coroutine (nested in resolve_account_niche)
    # + load_notes_for_account coroutine
    qualnames = {aw.__qualname__ for aw in gather_calls[0]}
    assert any(q.endswith("._fetch_account") for q in qualnames)
    assert "load_notes_for_account" in qualnames


@pytest.mark.asyncio
async def test_resolve_account_niche_no_gather_when_notes_provided(monkeypatch):
    """notes= path: only _fetch_account runs serial — no gather call."""
    await upsert_notes(
        [
            NoteStats(
                note_id="ng1",
                account_id="niche_nogather",
                title="宝宝辅食添加时间表",
                tags=["母婴"],
                views=100,
            )
        ]
    )

    fake_gather, gather_calls = _make_fake_gather()
    monkeypatch.setattr(niche_resolver.asyncio, "gather", fake_gather)

    res = await resolve_account_niche(
        "niche_nogather",
        manual_niche="",
        notes=[{"title": "宝宝辅食", "tags": ["母婴"]}],
    )

    assert res.niche == "母婴"
    assert res.source == "inferred"
    # No gather — _fetch_account runs serial (nothing to gather with)
    assert gather_calls == []
