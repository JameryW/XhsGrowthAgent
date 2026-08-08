"""Label resolution on /status must reuse the row _db_upsert already fetched.

Before this optimization, when ``update_fields`` carried no label (trend-only
workflows with no brief_content/brand_name), /status issued a second ``db_get``
round trip purely to read ``row.label``. ``_db_upsert`` now returns the row it
fetched internally, so /status resolves the label from that return value with
no extra DB hit. This is the highest-frequency path: the frontend polls /status
every 5s (frontend/src/stores/workflow.ts startPolling).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes.workflow import router
from backend.db.workflows import WorkflowRow


def _client(graph: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def _live_graph() -> MagicMock:
    graph = MagicMock()
    state = MagicMock()
    # No brief_content / content_plan → update_fields has no label, forcing the
    # label-resolution branch that previously did the redundant db_get.
    state.values = {
        "session_id": "xhs_acct_abcdef12",
        "account_id": "acct-live",
        "phase": "scouting",
        "current_agent": "trend_scout",
        "performance_log": [],
    }
    state.next = []
    graph.aget_state = AsyncMock(return_value=state)
    return graph


class TestStatusLabelReusesUpsertRow:
    def test_no_second_db_get_when_upsert_returns_row(self):
        graph = _live_graph()
        # _db_upsert returns the row it fetched internally; its label should be
        # surfaced in the response without a second db_get call.
        upsert_row = WorkflowRow(thread_id="xhs_acct_abcdef12", label="persisted-label")

        with (
            patch(
                "backend.api.routes.workflow.assert_thread_owned",
                new_callable=AsyncMock,
                return_value="acct-live",
            ),
            patch("backend.api.routes.workflow.is_pool_ready", return_value=True),
            patch(
                "backend.api.routes.workflow._db_upsert",
                new_callable=AsyncMock,
                return_value=upsert_row,
            ) as upsert_mock,
            patch("backend.api.routes.workflow.db_get", new_callable=AsyncMock) as db_get_mock,
        ):
            resp = _client(graph).get("/api/workflow/status/xhs_acct_abcdef12")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["label"] == "persisted-label"
        upsert_mock.assert_awaited_once()
        # The redundant db_get that used to run on every no-label poll is gone.
        db_get_mock.assert_not_awaited()

    def test_empty_label_when_upsert_returns_none(self):
        graph = _live_graph()
        # Pool unavailable / upsert raised → no row to read label from. Must
        # degrade to empty label, not crash, and not call db_get.
        with (
            patch(
                "backend.api.routes.workflow.assert_thread_owned",
                new_callable=AsyncMock,
                return_value="acct-live",
            ),
            patch("backend.api.routes.workflow.is_pool_ready", return_value=True),
            patch(
                "backend.api.routes.workflow._db_upsert",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("backend.api.routes.workflow.db_get", new_callable=AsyncMock) as db_get_mock,
        ):
            resp = _client(graph).get("/api/workflow/status/xhs_acct_abcdef12")

        assert resp.status_code == 200
        assert resp.json()["data"]["label"] == ""
        db_get_mock.assert_not_awaited()

    def test_generated_label_takes_precedence_over_row(self):
        graph = _live_graph()
        state = graph.aget_state.return_value
        # brief_content.brand_name drives update_fields["label"] — that must win
        # over the persisted row's label.
        state.values = {
            "session_id": "xhs_acct_abcdef12",
            "account_id": "acct-live",
            "phase": "planning",
            "current_agent": "content_strategist",
            "performance_log": [],
            "brief_content": {"brand_name": "BrandFromBrief"},
        }
        upsert_row = WorkflowRow(thread_id="xhs_acct_abcdef12", label="stale-persisted")

        with (
            patch(
                "backend.api.routes.workflow.assert_thread_owned",
                new_callable=AsyncMock,
                return_value="acct-live",
            ),
            patch("backend.api.routes.workflow.is_pool_ready", return_value=True),
            patch(
                "backend.api.routes.workflow._db_upsert",
                new_callable=AsyncMock,
                return_value=upsert_row,
            ),
            patch("backend.api.routes.workflow.db_get", new_callable=AsyncMock) as db_get_mock,
        ):
            resp = _client(graph).get("/api/workflow/status/xhs_acct_abcdef12")

        assert resp.status_code == 200
        assert resp.json()["data"]["label"] == "BrandFromBrief"
        db_get_mock.assert_not_awaited()
