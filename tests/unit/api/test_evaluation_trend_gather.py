"""GET /api/evaluation/trend must gather its 3 independent DB reads.

The endpoint resolves thresholds (evaluator weights), workflow RQGM samples
(evaluator_samples), and historical-note quality runs
(quality_evaluation_runs) — all keyed by the same account_id, none depending
on another's return. Serial they cost 3 DB round trips; gathered they cost 1.
This is the per-account RQGM trend dashboard path.

Discriminator: peak concurrent in-flight count (not timing — avoids CI flake).
Patch each read to sleep briefly while tracking the high-water mark of
overlapping calls. gather → peak==3; serial → peak==1.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes.evaluation import router

_IS_POOL_READY = "backend.db.pool.is_pool_ready"
_RESOLVE_ACCOUNT = "backend.api.routes.evaluation.resolve_required_account_id"
_SCORE_THRESHOLDS = "backend.api.routes.evaluation._score_thresholds"
# fetch_trend is imported lazily inside the handler from evaluator_config, so
# patch it at its source module.
_FETCH_TREND = "backend.db.evaluator_config.fetch_trend"
_QUALITY_DB = "backend.db.quality_evaluations.fetch_trend_points"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/evaluation")
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def _tracking_read(shared_inflight: list[int], shared_peak: list[int], value: object) -> AsyncMock:
    """AsyncMock that bumps a shared in-flight counter while it 'sleeps',
    recording the shared peak, then returns ``value``. The shared counter is
    what proves overlap across the three different reads."""

    async def _impl(*args, **kwargs):
        shared_inflight[0] += 1
        shared_peak[0] = max(shared_peak[0], shared_inflight[0])
        await asyncio.sleep(0.05)
        shared_inflight[0] -= 1
        return value

    return AsyncMock(side_effect=_impl)


class TestEvaluatorTrendGathersThreeReads:
    def test_three_reads_run_concurrently(self):
        inflight = [0]
        peak = [0]
        thresholds_mock = _tracking_read(inflight, peak, {"pass": 70.0, "warn": 50.0})
        workflow_mock = _tracking_read(inflight, peak, [])
        note_mock = _tracking_read(inflight, peak, [])

        with (
            patch(_IS_POOL_READY, return_value=True),
            patch(_RESOLVE_ACCOUNT, AsyncMock(return_value="acct1")),
            patch(_SCORE_THRESHOLDS, thresholds_mock),
            patch(_FETCH_TREND, workflow_mock),
            patch(_QUALITY_DB, note_mock),
        ):
            resp = _client().get("/api/evaluation/trend?account_id=acct1")

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # All three reads overlapped → peak in-flight == 3. Serial would peak at 1.
        assert peak[0] == 3, f"expected 3 concurrent reads, peaked at {peak[0]}"

    def test_pool_not_ready_returns_thresholds_only(self):
        # pool down: thresholds still resolved (defaults), fetches degrade to [].
        inflight = [0]
        peak = [0]
        thresholds_mock = _tracking_read(inflight, peak, {"pass": 70.0, "warn": 50.0})
        workflow_mock = _tracking_read(inflight, peak, [])
        note_mock = _tracking_read(inflight, peak, [])

        with (
            patch(_IS_POOL_READY, return_value=False),
            patch(_RESOLVE_ACCOUNT, AsyncMock(return_value="acct1")),
            patch(_SCORE_THRESHOLDS, thresholds_mock),
            patch(_FETCH_TREND, workflow_mock),
            patch(_QUALITY_DB, note_mock),
        ):
            resp = _client().get("/api/evaluation/trend?account_id=acct1")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["db_ready"] is False
        assert body["points"] == []
        assert body["pass_threshold"] == 70.0
        # thresholds still gathered; the two fetches ran (degraded to []) but
        # their returns are unused on this path — what matters is no crash.
        thresholds_mock.assert_awaited_once()

    def test_merges_workflow_and_note_rows(self):
        workflow_row = {
            "created_at": "2026-08-01T10:00:00Z",
            "overall_score": 80.0,
            "decision": "approved",
            "dimensions": [],
            "account_id": "acct1",
            "status": "ready",
            "degraded": False,
        }
        note_row = {
            "created_at": "2026-08-02T10:00:00Z",
            "overall_score": 65.0,
            "decision": "needs_revision",
            "dimensions": [],
            "account_id": "acct1",
            "status": "ready",
            "degraded": False,
        }

        with (
            patch(_IS_POOL_READY, return_value=True),
            patch(_RESOLVE_ACCOUNT, AsyncMock(return_value="acct1")),
            patch(_SCORE_THRESHOLDS, AsyncMock(return_value={"pass": 70.0, "warn": 50.0})),
            patch(_FETCH_TREND, AsyncMock(return_value=[workflow_row])),
            patch(_QUALITY_DB, AsyncMock(return_value=[note_row])),
        ):
            resp = _client().get("/api/evaluation/trend?account_id=acct1")

        assert resp.status_code == 200
        points = resp.json()["data"]["points"]
        assert len(points) == 2
        # ascending by created_at
        assert points[0]["overall_score"] == 80.0
        assert points[1]["overall_score"] == 65.0

    def test_note_fetch_failure_degrades_to_workflow_only(self):
        # quality_db import / fetch raises → _safe_note_rows swallows → []
        workflow_row = {
            "created_at": "2026-08-01T10:00:00Z",
            "overall_score": 80.0,
            "decision": "approved",
            "dimensions": [],
            "account_id": "acct1",
            "status": "ready",
            "degraded": False,
        }

        with (
            patch(_IS_POOL_READY, return_value=True),
            patch(_RESOLVE_ACCOUNT, AsyncMock(return_value="acct1")),
            patch(_SCORE_THRESHOLDS, AsyncMock(return_value={"pass": 70.0, "warn": 50.0})),
            patch(_FETCH_TREND, AsyncMock(return_value=[workflow_row])),
            patch(_QUALITY_DB, AsyncMock(side_effect=RuntimeError("table missing"))),
        ):
            resp = _client().get("/api/evaluation/trend?account_id=acct1")

        assert resp.status_code == 200
        points = resp.json()["data"]["points"]
        assert len(points) == 1
        assert points[0]["overall_score"] == 80.0
