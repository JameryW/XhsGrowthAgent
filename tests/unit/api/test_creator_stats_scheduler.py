from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.app import _creator_stats_scheduler, app, health

app_module = importlib.import_module("backend.api.app")


def _scheduler_app() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(graph=SimpleNamespace(store=None)),
    )


@pytest.mark.asyncio
async def test_scheduler_runs_immediately_and_records_batch_summary(monkeypatch):
    app = _scheduler_app()
    result = {
        "ok": True,
        "status": "completed",
        "active_accounts": 2,
        "succeeded": 2,
        "failed": 0,
    }
    sleep_calls: list[float] = []

    async def stop_after_first_run(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_first_run)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ) as sync,
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, 0.5)

    sync.assert_awaited_once_with(store=None, period="30d")
    # Scheduler sleep carries ±10% jitter around the configured interval.
    assert len(sleep_calls) == 1
    assert 1800.0 * 0.9 <= sleep_calls[0] <= 1800.0 * 1.1
    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "completed"
    assert state["run_count"] == 1
    assert state["last_status"] == "completed"
    assert state["last_succeeded"] == 2
    assert state["last_failed"] == 0
    assert state["last_finished_at"]
    assert state["next_run_at"]


@pytest.mark.asyncio
async def test_scheduler_records_unexpected_failure_before_retry(monkeypatch):
    app = _scheduler_app()

    async def stop_after_failure(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_failure)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, 1)

    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "failed"
    assert state["last_error"] == "database unavailable"
    assert state["last_finished_at"]
    assert state["next_run_at"]


@pytest.mark.asyncio
async def test_scheduler_surfaces_per_account_errors_in_last_error(monkeypatch):
    app = _scheduler_app()
    result = {
        "ok": False,
        "status": "completed",
        "active_accounts": 1,
        "succeeded": 0,
        "failed": 1,
        "results": [
            {
                "account_id": "acc-1",
                "account_synced": False,
                "error": "creator center login page is showing; re-login",
            }
        ],
    }

    async def stop_after_first_run(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_first_run)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, 1)

    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "failed"
    assert state["last_failed"] == 1
    assert "acc-1" in (state["last_error"] or "")
    assert "login page" in (state["last_error"] or "")


@pytest.mark.asyncio
async def test_health_exposes_scheduler_summary_without_raw_results(monkeypatch):
    monkeypatch.setattr(
        "backend.db.pool.is_pool_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        app.state,
        "creator_stats_scheduler_status",
        {
            "enabled": True,
            "status": "completed",
            "last_status": "completed",
            "last_succeeded": 1,
            "last_failed": 0,
            "last_result": {"should_not": "be exposed"},
        },
        raising=False,
    )

    response = await health()

    assert response.success is True
    assert response.data["db"] == "connected"
    scheduler = response.data["creator_stats_scheduler"]
    assert scheduler["status"] == "completed"
    assert scheduler["last_succeeded"] == 1
    assert "last_result" not in scheduler
