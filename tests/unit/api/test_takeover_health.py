"""The takeover summary on ``/health`` (P2b-S3).

The task's third acceptance criterion asks that behaviour without Postgres stay
the same **and** that the degradation be observable. The lease answers
``durability: none`` for the storage half; this is where the takeover half
becomes visible to whoever is looking at a running service -- "nothing was
taken over" and "nothing durable could have been taken over" have to look
different from outside.

Mirrors ``test_creator_stats_scheduler.py``'s approach: call the route with the
app state set up directly, rather than booting the whole lifespan.
"""

from __future__ import annotations

import pytest

from backend.api.app import app, health


@pytest.fixture(autouse=True)
def _remove_takeover_status(monkeypatch: pytest.MonkeyPatch):
    """Start every test from "the scan never ran"; monkeypatch restores after."""
    monkeypatch.delattr(app.state, "takeover_status", raising=False)
    yield


async def test_health_exposes_the_takeover_summary(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)
    monkeypatch.setattr(
        app.state,
        "takeover_status",
        {
            "enabled": True,
            "durability": "durable",
            "interval_seconds": 60.0,
            "status": "scheduled",
            "run_count": 3,
            "last_source": "periodic",
            "last_taken_over": 1,
            "last_refused": 2,
            "last_skipped": 0,
            "last_error": None,
            "last_decisions": [{"thread_id": "should_not_be_exposed"}],
        },
        raising=False,
    )

    response = await health()

    summary = response.data["execution_takeover"]
    assert summary["enabled"] is True
    assert summary["durability"] == "durable"
    assert summary["status"] == "scheduled"
    assert summary["run_count"] == 3
    assert summary["last_taken_over"] == 1
    assert summary["last_refused"] == 2
    # The decision log is per-thread detail; /health reports a summary.
    assert "last_decisions" not in summary


async def test_health_reports_the_degraded_lease_backend(monkeypatch: pytest.MonkeyPatch):
    """No Postgres means no durable lease, so no restart can take anything over.
    The surface says so instead of leaving a gap where a number would be."""
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)
    monkeypatch.setattr(
        app.state,
        "takeover_status",
        {
            "enabled": False,
            "durability": "none",
            "interval_seconds": 60.0,
            "status": "disabled",
            "run_count": 0,
        },
        raising=False,
    )

    response = await health()

    summary = response.data["execution_takeover"]
    assert summary["status"] == "disabled"
    assert summary["enabled"] is False
    assert summary["durability"] == "none"


async def test_health_survives_a_scan_that_never_started(monkeypatch: pytest.MonkeyPatch):
    """If the lifespan never ran the field is null, not absent -- a reader can
    tell "not wired" from "wired and found nothing"."""
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

    response = await health()

    assert "execution_takeover" in response.data
    assert response.data["execution_takeover"] is None
