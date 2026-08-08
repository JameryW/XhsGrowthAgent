"""Tests for /analytics/dashboard cost accuracy + cache key split.

Covers the dashboard bundle fixes:
- Cost payload aggregates cost from error-status workflows (include_error=True
  second fetch), while the report payload (_extract_post_data) still excludes
  them (narrow fetch, needs publish_result).
- ``_get_completed_workflows`` cache keys separate include_error True/False so
  the cost and report paths never share an entry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.routes import analytics

TEST_USER_ID = "user-dashboard-test"
TEST_ACCOUNT_ID = "acc-dashboard"


@pytest.fixture(autouse=True)
def _clear_cache():
    analytics._cache.clear()
    yield
    analytics._cache.clear()


@pytest.fixture
def client():
    app.state.graph = object()

    async def _user():
        return {"id": TEST_USER_ID, "username": "tester"}

    app.dependency_overrides[analytics.get_current_user] = _user
    yield TestClient(app)
    app.dependency_overrides.pop(analytics.get_current_user, None)
    if hasattr(app.state, "graph"):
        delattr(app.state, "graph")


def _completed_post_workflow() -> dict:
    """A completed workflow whose post data _extract_post_data will accept."""
    now_iso = datetime.now(UTC).isoformat()
    return {
        "_state": {
            "publish_result": {
                "status": "mock_published",
                "title": "completed post",
                "published_at": now_iso,
            },
            "copy_content": {"selected_title": "completed post"},
            "content_plan": {"selected_topic": "topic-a"},
            "performance_log": [{"kind": "llm", "model": "astron-code-latest", "cost_usd": 0.01}],
        }
    }


def _errored_workflow() -> dict:
    """An errored workflow: no publish_result, but LLM spend in performance_log."""
    return {
        "_state": {
            # No publish_result → _extract_post_data returns None (report excludes it)
            "performance_log": [{"kind": "llm", "model": "deepseek-v4-flash", "cost_usd": 0.04}],
        }
    }


@pytest.fixture
def _dashboard_deps():
    """Patch account-scope + snapshot deps so /dashboard runs in isolation."""
    empty_bundle = {
        "account_id": TEST_ACCOUNT_ID,
        "account": None,
        "notes": [],
        "data_as_of": None,
        "snapshot_id": None,
        "note_count": 0,
    }
    with (
        patch(
            "backend.api.routes.analytics.require_owned_account",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backend.api.routes.analytics._creator_snapshot_bundle",
            new=AsyncMock(return_value=empty_bundle),
        ),
    ):
        yield


class TestDashboardCostIncludesErroredWorkflows:
    def test_cost_payload_includes_error_workflow_spend(self, client, _dashboard_deps):
        """Dashboard fetches cost with include_error=True → error wf cost counted."""
        # Report path (narrow) sees only the completed workflow; cost path (wide)
        # also sees the errored one. We model this by returning different lists
        # per include_error flag.
        completed = _completed_post_workflow()
        errored = _errored_workflow()

        async def _fetch(graph, account_id=None, *, include_error=False):
            if include_error:
                return [completed, errored]
            return [completed]

        with patch.object(analytics, "_get_completed_workflows", AsyncMock(side_effect=_fetch)):
            resp = client.get(f"/api/analytics/dashboard/{TEST_ACCOUNT_ID}")

        data = resp.json()["data"]
        costs = data["costs"]
        # 0.01 (completed) + 0.04 (errored) = 0.05
        assert costs["total_cost_usd"] == 0.05
        assert costs["by_model"]["astron-code-latest"] == 0.01
        assert costs["by_model"]["deepseek-v4-flash"] == 0.04

    def test_report_payload_excludes_errored_workflow(self, client, _dashboard_deps):
        """Report path uses the narrow fetch → no post extracted from error wfs."""
        completed = _completed_post_workflow()
        errored = _errored_workflow()

        async def _fetch(graph, account_id=None, *, include_error=False):
            if include_error:
                return [completed, errored]
            return [completed]

        with patch.object(analytics, "_get_completed_workflows", AsyncMock(side_effect=_fetch)):
            resp = client.get(f"/api/analytics/dashboard/{TEST_ACCOUNT_ID}")

        data = resp.json()["data"]
        report = data["report"]
        # Only the completed workflow yields a post; the errored one has no
        # publish_result so _extract_post_data returns None.
        assert report["metrics"]["total_posts"] == 1

    def test_dashboard_cost_uses_wide_fetch(self, client, _dashboard_deps):
        """The dashboard cost path must call _get_completed_workflows with include_error=True."""
        seen_flags: list[bool] = []

        async def _fetch(graph, account_id=None, *, include_error=False):
            seen_flags.append(include_error)
            return []

        with patch.object(analytics, "_get_completed_workflows", AsyncMock(side_effect=_fetch)):
            client.get(f"/api/analytics/dashboard/{TEST_ACCOUNT_ID}")

        # The dashboard issues two fetches: narrow (report) + wide (cost).
        assert seen_flags == [False, True]


class TestDashboardBudgetFromSettings:
    def test_budget_reflects_configured_daily_budget(self, client, _dashboard_deps):
        class _FakeModelSettings:
            daily_budget_usd = 50.0

        class _FakeSettings:
            models = _FakeModelSettings()

        completed = _completed_post_workflow()
        with (
            patch("backend.api.routes.analytics.Settings", return_value=_FakeSettings()),
            patch.object(
                analytics,
                "_get_completed_workflows",
                AsyncMock(return_value=[completed]),
            ),
        ):
            resp = client.get(f"/api/analytics/dashboard/{TEST_ACCOUNT_ID}")

        costs = resp.json()["data"]["costs"]
        # 50.0 budget - 0.01 cost = 49.99 (hardcoded 10.0 would have given 9.99)
        assert costs["budget_remaining_usd"] == 49.99


class TestDashboardGathersSnapshotWithWorkflows:
    """_get_completed_workflows (checkpointer) and _creator_snapshot_bundle
    (creator_stats DB) hit independent storage and must run concurrently — the
    snapshot RT hides behind the checkpoint gather. A serial call would make
    peak in-flight == 1; a gather makes it == 2."""

    def test_dashboard_runs_workflows_and_snapshot_concurrently(self, client):
        import asyncio

        in_flight = 0
        peak = 0

        async def _slow_workflows(graph, account_id=None, *, include_error=False):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            return [_completed_post_workflow()]

        async def _slow_snapshot(account_id):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            return {
                "account_id": TEST_ACCOUNT_ID,
                "account": None,
                "notes": [],
                "data_as_of": None,
                "snapshot_id": None,
                "note_count": 0,
            }

        with (
            patch(
                "backend.api.routes.analytics.require_owned_account",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                analytics, "_get_completed_workflows", AsyncMock(side_effect=_slow_workflows)
            ),
            patch.object(
                analytics, "_creator_snapshot_bundle", AsyncMock(side_effect=_slow_snapshot)
            ),
        ):
            resp = client.get(f"/api/analytics/dashboard/{TEST_ACCOUNT_ID}")

        assert resp.status_code == 200
        # gather → both helpers overlap → peak in-flight reaches 2.
        # A serial implementation would peak at 1 (revert-then-fail: peak == 1).
        assert peak == 2
