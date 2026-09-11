"""Tests for gather-parallel DB reads in get_creator_analysis.

`get_creator_analysis` runs two independent read-only DB SELECTs:
``list_note_stats`` (creator_note_stats) and ``get_account_stats``
(creator_account_stats).  They were serial; now gathered.  These tests
prove both fetches run concurrently by making each one wait, for a bounded
time, until the other has started — an overlap property rather than a
clock reading.

Revert-then-fail: restoring sequential ``await`` lines leaves the first mock
waiting for a second call that cannot start yet, so it records ``no-overlap``
and the assertions FAIL.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.api.routes import analytics

# Generous against CI scheduling noise, short enough that a sequential
# regression still reports in about a second instead of hanging the suite.
_RENDEZVOUS_TIMEOUT = 2.0


def _patch_db(monkeypatch: pytest.MonkeyPatch):
    """Patch the two read-only DB fns at the source module.

    The route does a lazy ``from backend.db import creator_stats as stats_db``
    inside the function body, so the patch target is the source module
    ``backend.db.creator_stats`` — both the route-local alias and the
    module-level reference point at the same module object.

    Each mock announces that it started and then waits, with a bounded timeout,
    for the *other* one to have started. That rendezvous can only complete if the
    two really overlap. Under a sequential ``await`` implementation the first mock
    waits on an event the second has not yet reached and records ``no-overlap``,
    so the assertions below fail instead of silently passing.

    Recording stages rather than clock samples matters: inferring interleaving
    from timestamps needs a clock that can separate two micro-task yields, and
    the Windows event-loop clock advances in ticks of roughly 15.6 ms, where both
    fetches land on the identical value.
    """
    from backend.db import creator_stats as stats_db

    started = {"list": asyncio.Event(), "account": asyncio.Event()}
    stages: dict[str, list[str]] = {"list": [], "account": []}

    async def _rendezvous(self_key: str, other_key: str) -> None:
        started[self_key].set()
        try:
            await asyncio.wait_for(started[other_key].wait(), timeout=_RENDEZVOUS_TIMEOUT)
        except TimeoutError:
            stages[self_key].append("no-overlap")
            raise

    async def fake_list_note_stats(account_id, limit=100):
        stages["list"].append("start")
        await _rendezvous("list", "account")
        stages["list"].append("finish")
        return []  # empty notes — analyze_notes([]) + summarize_audience safe

    async def fake_get_account_stats(account_id):
        stages["account"].append("start")
        await _rendezvous("account", "list")
        stages["account"].append("finish")
        return None  # summarize_audience(None, []) returns safe empty dict

    monkeypatch.setattr(stats_db, "list_note_stats", fake_list_note_stats)
    monkeypatch.setattr(stats_db, "get_account_stats", fake_get_account_stats)
    return stages


@pytest.mark.asyncio
async def test_get_creator_analysis_gathers_reads_concurrently(monkeypatch):
    """Both read-only fetches run under asyncio.gather (concurrent, overlapping).

    Each mock can only reach "finish" after the other has announced it started,
    so two complete stage sequences prove the fetches overlapped. Nothing here
    depends on how finely the host clock can separate two awaits, which the old
    `start < other_start < finish` comparison did: on Windows both samples landed
    on the same ~15.6 ms event-loop tick and the assertion failed while the code
    was in fact concurrent.

    Revert-then-fail: restoring sequential ``await`` lines leaves the first mock
    waiting for a call that cannot start yet, so it records ``no-overlap`` and
    never reaches ``finish``.
    """
    stages = _patch_db(monkeypatch)

    monkeypatch.setattr(analytics, "require_owned_account", lambda *a, **kw: _noop_async())

    result = await analytics.get_creator_analysis(
        account_id="acc-a",
        user={"id": "user-1"},
    )

    assert stages["list"] == ["start", "finish"], (
        f"list_note_stats never overlapped get_account_stats: {stages}"
    )
    assert stages["account"] == ["start", "finish"], (
        f"get_account_stats never overlapped list_note_stats: {stages}"
    )

    # Return shape intact — no behavior change.
    assert result.success is True
    data = result.data
    assert "analysis" in data
    assert "suggestions" in data
    assert "audience_analysis" in data


async def _noop_async() -> None:
    return None
