"""Tests for GET /api/workflow/account-totals (history multi-account badges)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes.workflow import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/workflow")
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


class TestWorkflowAccountTotals:
    def test_returns_owned_account_counts(self):
        owned = [MagicMock(id="acct-a"), MagicMock(id="acct-b")]
        with (
            patch("backend.api.routes.workflow.is_pool_ready", return_value=True),
            patch(
                "backend.db.accounts.list_accounts",
                new_callable=AsyncMock,
                return_value=owned,
            ),
            patch(
                "backend.db.workflows.count_workflows_for_accounts",
                new_callable=AsyncMock,
                return_value={"acct-a": 0, "acct-b": 2},
            ) as count_mock,
        ):
            resp = _client().get("/api/workflow/account-totals")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["totals"] == {"acct-a": 0, "acct-b": 2}
        count_mock.assert_awaited_once_with(["acct-a", "acct-b"], status=None)

    def test_status_filter_forwarded(self):
        owned = [MagicMock(id="acct-a")]
        with (
            patch("backend.api.routes.workflow.is_pool_ready", return_value=True),
            patch(
                "backend.db.accounts.list_accounts",
                new_callable=AsyncMock,
                return_value=owned,
            ),
            patch(
                "backend.db.workflows.count_workflows_for_accounts",
                new_callable=AsyncMock,
                return_value={"acct-a": 3},
            ) as count_mock,
        ):
            resp = _client().get("/api/workflow/account-totals?status=awaiting_review")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["totals"] == {"acct-a": 3}
        assert body["data"]["status"] == "awaiting_review"
        count_mock.assert_awaited_once_with(["acct-a"], status="awaiting_review")

    def test_empty_owned_accounts(self):
        with (
            patch("backend.api.routes.workflow.is_pool_ready", return_value=True),
            patch(
                "backend.db.accounts.list_accounts",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "backend.db.workflows.count_workflows_for_accounts",
                new_callable=AsyncMock,
            ) as count_mock,
        ):
            resp = _client().get("/api/workflow/account-totals")

        assert resp.status_code == 200
        assert resp.json()["data"]["totals"] == {}
        count_mock.assert_not_awaited()

    def test_db_unavailable_returns_zeros(self):
        owned = [MagicMock(id="acct-a")]
        with (
            patch("backend.api.routes.workflow.is_pool_ready", return_value=False),
            patch(
                "backend.db.accounts.list_accounts",
                new_callable=AsyncMock,
                return_value=owned,
            ),
            patch(
                "backend.db.workflows.count_workflows_for_accounts",
                new_callable=AsyncMock,
            ) as count_mock,
        ):
            resp = _client().get("/api/workflow/account-totals")

        assert resp.status_code == 200
        assert resp.json()["data"]["totals"] == {"acct-a": 0}
        count_mock.assert_not_awaited()
