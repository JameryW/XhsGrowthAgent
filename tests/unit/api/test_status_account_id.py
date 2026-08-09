"""Status responses expose owning account_id for multi-account dashboard UI."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes.workflow import (
    _account_id_from_thread,
    _resolve_status_account_id,
    router,
)


def _client(graph: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


class TestAccountIdFromThread:
    def test_parses_uuid_account(self):
        aid = "9eaec02e-e1a4-429b-bed2-ce33ce7fc9dd"
        assert _account_id_from_thread(f"xhs_{aid}_7176d7ff") == aid

    def test_rejects_malformed(self):
        assert _account_id_from_thread("nope") == ""
        assert _account_id_from_thread("xhs_only") == ""


class TestResolveStatusAccountId:
    def test_prefers_state_over_thread_parse(self):
        tid = "xhs_from-thread_12345678"
        assert _resolve_status_account_id(tid, {"account_id": "from-state"}) == "from-state"

    def test_falls_back_to_db_then_thread(self):
        aid = "c056e160-6c6e-424b-96df-67733a5d9c56"
        tid = f"xhs_{aid}_4673f6f9"
        assert _resolve_status_account_id(tid, {}, db_account_id="from-db") == "from-db"
        assert _resolve_status_account_id(tid, {}) == aid


class TestStatusEndpointAccountId:
    def test_live_status_includes_account_id(self):
        graph = MagicMock()
        state = MagicMock()
        state.values = {
            "session_id": "xhs_acct_abcdef12",
            "account_id": "acct-live",
            "phase": "creating",
            "current_agent": "copywriter",
            "performance_log": [],
        }
        state.next = []
        graph.aget_state = AsyncMock(return_value=state)

        with (
            patch(
                "backend.api.routes.workflow.assert_thread_owned",
                new_callable=AsyncMock,
                return_value="acct-live",
            ),
            patch("backend.api.routes.workflow.is_pool_ready", return_value=False),
            patch(
                "backend.api.routes.workflow._db_upsert",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = _client(graph).get("/api/workflow/status/xhs_acct_abcdef12")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["account_id"] == "acct-live"
