"""Tests for the /analytics/costs endpoint aggregation.

Covers the fix for the perpetually-$0 cost dashboard: kind:"llm" performance_log
entries (written by llm_perf_entry) must aggregate into by_model / total / today.
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
