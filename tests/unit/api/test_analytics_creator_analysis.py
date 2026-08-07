"""Tests for gather-parallel DB reads in get_creator_analysis.

`get_creator_analysis` runs two independent read-only DB SELECTs:
``list_note_stats`` (creator_note_stats) and ``get_account_stats``
(creator_account_stats).  They were serial; now gathered.  These tests
prove both fetches run concurrently via asyncio.gather.

Revert-then-fail: reverting to serial ``await`` lines makes the two mocks
run strictly sequentially (list_note_stats completes before
get_account_stats starts), so the overlap detector FAILs.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.api.routes import analytics


def _patch_db(monkeypatch: pytest.MonkeyPatch):
    """Patch the two read-only DB fns at the source module.

    The route does a lazy ``from backend.db import creator_stats as stats_db``
    inside the function body, so the patch target is the source module
    ``backend.db.creator_stats`` — both the route-local alias and the
    module-level reference point at the same module object.

    Each mock records its start/finish time and yields once so that, under
    gather, the two coroutines interleave (overlap).  Under serial ``await``,
    list_note_stats finishes before get_account_stats starts (no overlap).
    """
    from backend.db import creator_stats as stats_db

    timeline: dict[str, list[float]] = {"list": [], "account": []}

    async def fake_list_note_stats(account_id, limit=100):
        timeline["list"].append(asyncio.get_event_loop().time())
        await asyncio.sleep(0)  # yield to allow interleaving under gather
        timeline["list"].append(asyncio.get_event_loop().time())
        return []  # empty notes — analyze_notes([]) + summarize_audience safe

    async def fake_get_account_stats(account_id):
        timeline["account"].append(asyncio.get_event_loop().time())
        await asyncio.sleep(0)  # yield to allow interleaving under gather
        timeline["account"].append(asyncio.get_event_loop().time())
        return None  # summarize_audience(None, []) returns safe empty dict

    monkeypatch.setattr(stats_db, "list_note_stats", fake_list_note_stats)
    monkeypatch.setattr(stats_db, "get_account_stats", fake_get_account_stats)
    return timeline


@pytest.mark.asyncio
async def test_get_creator_analysis_gathers_reads_concurrently(monkeypatch):
    """Both read-only fetches run under asyncio.gather (concurrent, overlapping).

    Under gather with a yield point in each mock, the two coroutines
    interleave: list_note_stats starts, yields; get_account_stats starts,
    yields; both finish.  The account-start timestamp therefore falls
    BETWEEN list_note_stats' start and finish — proving overlap.

    Revert-then-fail: with serial ``await list_note_stats`` then ``await
    get_account_stats``, list_note_stats runs to completion (start + finish)
    before get_account_stats even starts — account-start >= list-finish, no
    overlap, the assertion FAILs.
    """
    timeline = _patch_db(monkeypatch)

    monkeypatch.setattr(analytics, "require_owned_account", lambda *a, **kw: _noop_async())

    result = await analytics.get_creator_analysis(
        account_id="acc-a",
        user={"id": "user-1"},
    )

    # Both fetches were invoked (proves gather ran both, not just the first).
    assert len(timeline["list"]) == 2  # start + finish
    assert len(timeline["account"]) == 2  # start + finish

    # Concurrency discriminator: account-start must fall strictly between
    # list-start and list-finish.  Under serial execution, list-finish <=
    # account-start (list ran to completion before account started).
    list_start, list_finish = timeline["list"][0], timeline["list"][1]
    account_start = timeline["account"][0]
    assert list_start < account_start < list_finish, (
        f"not concurrent: list=[{list_start},{list_finish}] account_start={account_start}"
    )

    # Return shape intact — no behavior change.
    assert result.success is True
    data = result.data
    assert "analysis" in data
    assert "suggestions" in data
    assert "audience_analysis" in data


async def _noop_async() -> None:
    return None
