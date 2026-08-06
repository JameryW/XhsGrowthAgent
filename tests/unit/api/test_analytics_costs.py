"""Tests for the /analytics/costs endpoint aggregation.

Covers the fix for the perpetually-$0 cost dashboard: kind:"llm" performance_log
entries (written by llm_perf_entry) must aggregate into by_model / total / today.
Also covers the accuracy fixes: errored-workflow cost inclusion and reading the
budget cap from ``Settings.models.daily_budget_usd`` (not a hardcoded 10.0).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.routes import analytics

TEST_USER_ID = "user-cost-test"


@pytest.fixture(autouse=True)
def _clear_cache():
    analytics._cache.clear()
    yield
    analytics._cache.clear()


@pytest.fixture
def client():
    """Test client with mocked graph and authenticated user."""
    app.state.graph = object()  # _get_completed_workflows is patched per-test

    async def _user():
        return {"id": TEST_USER_ID, "username": "tester"}

    app.dependency_overrides[analytics.get_current_user] = _user
    yield TestClient(app)
    app.dependency_overrides.pop(analytics.get_current_user, None)
    if hasattr(app.state, "graph"):
        delattr(app.state, "graph")


def _wf_with_llm_entries(entries: list[dict]) -> dict:
    return {"_state": {"performance_log": entries}}


class TestCostsAggregation:
    def test_llm_entries_aggregate_into_by_model_and_total(self, client):
        now_iso = datetime.now(UTC).isoformat()
        workflows = [
            _wf_with_llm_entries(
                [
                    {"kind": "node", "agent": "copywriter"},  # skipped (no cost)
                    {
                        "kind": "llm",
                        "model": "astron-code-latest",
                        "cost_usd": 0.005,
                        "timestamp": now_iso,
                    },
                    {
                        "kind": "llm",
                        "model": "astron-code-latest",
                        "cost_usd": 0.003,
                        "timestamp": now_iso,
                    },
                ]
            )
        ]
        with patch.object(analytics, "_get_completed_workflows", AsyncMock(return_value=workflows)):
            resp = client.get("/api/analytics/costs?period=weekly")

        data = resp.json()["data"]
        assert data["total_cost_usd"] == 0.01
        assert data["by_model"]["astron-code-latest"] == 0.01
        assert data["today_cost_usd"] == 0.01  # entries timestamped today
        assert data["period_cost_usd"] == 0.01  # within weekly window

    def test_empty_perf_log_yields_zero_cost(self, client):
        workflows = [_wf_with_llm_entries([])]
        with patch.object(analytics, "_get_completed_workflows", AsyncMock(return_value=workflows)):
            resp = client.get("/api/analytics/costs?period=weekly")

        data = resp.json()["data"]
        assert data["total_cost_usd"] == 0.0
        assert data["by_model"] == {}

    def test_node_and_human_wait_entries_skipped(self, client):
        workflows = [
            _wf_with_llm_entries(
                [
                    {"kind": "node", "agent": "copywriter", "cost_usd": 99.0},
                    {"kind": "human_wait", "gate": "review_gate", "cost_usd": 99.0},
                ]
            )
        ]
        with patch.object(analytics, "_get_completed_workflows", AsyncMock(return_value=workflows)):
            resp = client.get("/api/analytics/costs?period=weekly")

        data = resp.json()["data"]
        assert data["total_cost_usd"] == 0.0


class TestCostsIncludesErroredWorkflows:
    """/costs fetches with include_error=True so error-status workflows' LLM
    spend is not silently dropped (they retain checkpoint performance_log)."""

    def test_costs_passes_include_error_true(self, client):
        """The /costs endpoint must request the wide fetch (include_error=True)."""
        captured: dict[str, bool] = {}

        async def _capture(graph, *args, **kwargs):
            captured["include_error"] = kwargs.get("include_error", False)
            return []

        with patch.object(analytics, "_get_completed_workflows", AsyncMock(side_effect=_capture)):
            client.get("/api/analytics/costs?period=weekly")

        assert captured["include_error"] is True

    def test_errored_workflow_cost_included_in_total(self, client):
        """An error-status workflow with kind:"llm" entries contributes to total."""
        now_iso = datetime.now(UTC).isoformat()
        error_wf = _wf_with_llm_entries(
            [
                {
                    "kind": "llm",
                    "model": "deepseek-v4-flash",
                    "cost_usd": 0.02,
                    "timestamp": now_iso,
                },
            ]
        )
        with patch.object(
            analytics, "_get_completed_workflows", AsyncMock(return_value=[error_wf])
        ):
            resp = client.get("/api/analytics/costs?period=weekly")

        data = resp.json()["data"]
        assert data["total_cost_usd"] == 0.02
        assert data["by_model"]["deepseek-v4-flash"] == 0.02


class TestCostsBudgetFromSettings:
    """budget_remaining_usd reads Settings().models.daily_budget_usd, not 10.0."""

    def test_budget_reflects_configured_daily_budget(self, client):
        """DAILY_BUDGET_USD=50 → budget_remaining = 50 - total (not 10 - total)."""

        class _FakeModelSettings:
            daily_budget_usd = 50.0

        class _FakeSettings:
            models = _FakeModelSettings()

        workflows = [_wf_with_llm_entries([{"kind": "llm", "model": "m", "cost_usd": 3.0}])]
        with (
            patch("backend.api.routes.analytics.Settings", return_value=_FakeSettings()),
            patch.object(analytics, "_get_completed_workflows", AsyncMock(return_value=workflows)),
        ):
            resp = client.get("/api/analytics/costs?period=weekly")

        data = resp.json()["data"]
        # 50.0 budget - 3.0 cost = 47.0 (hardcoded 10.0 would have given 7.0)
        assert data["budget_remaining_usd"] == 47.0

    def test_budget_floors_at_zero_when_cost_exceeds_budget(self, client):
        class _FakeModelSettings:
            daily_budget_usd = 5.0

        class _FakeSettings:
            models = _FakeModelSettings()

        workflows = [_wf_with_llm_entries([{"kind": "llm", "model": "m", "cost_usd": 8.0}])]
        with (
            patch("backend.api.routes.analytics.Settings", return_value=_FakeSettings()),
            patch.object(analytics, "_get_completed_workflows", AsyncMock(return_value=workflows)),
        ):
            resp = client.get("/api/analytics/costs?period=weekly")

        data = resp.json()["data"]
        assert data["budget_remaining_usd"] == 0.0
