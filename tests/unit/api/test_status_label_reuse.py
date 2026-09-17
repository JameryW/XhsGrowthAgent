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
                "backend.api.routes._wf_application.assert_thread_owned",
                new_callable=AsyncMock,
                return_value="acct-live",
            ),
            patch("backend.api.routes._wf_application.is_pool_ready", return_value=True),
            patch(
                "backend.api.routes._wf_application._db_upsert",
                new_callable=AsyncMock,
                return_value=upsert_row,
            ) as upsert_mock,
            patch(
                "backend.api.routes._wf_application.db_get", new_callable=AsyncMock
            ) as db_get_mock,
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
                "backend.api.routes._wf_application.assert_thread_owned",
                new_callable=AsyncMock,
                return_value="acct-live",
            ),
            patch("backend.api.routes._wf_application.is_pool_ready", return_value=True),
            patch(
                "backend.api.routes._wf_application._db_upsert",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "backend.api.routes._wf_application.db_get", new_callable=AsyncMock
            ) as db_get_mock,
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
            "brief_content": {"brand_name": "BrandFromBrief"},
        }
        upsert_row = WorkflowRow(thread_id="xhs_acct_abcdef12", label="stale-persisted")

        with (
            patch(
                "backend.api.routes._wf_application.assert_thread_owned",
                new_callable=AsyncMock,
                return_value="acct-live",
            ),
            patch("backend.api.routes._wf_application.is_pool_ready", return_value=True),
            patch(
                "backend.api.routes._wf_application._db_upsert",
                new_callable=AsyncMock,
                return_value=upsert_row,
            ),
            patch(
                "backend.api.routes._wf_application.db_get", new_callable=AsyncMock
            ) as db_get_mock,
        ):
            resp = _client(graph).get("/api/workflow/status/xhs_acct_abcdef12")

        assert resp.status_code == 200
        assert resp.json()["data"]["label"] == "BrandFromBrief"
        db_get_mock.assert_not_awaited()

    def test_live_status_hydrates_pause_reason(self):
        """P1a-S1 wire-neutrality guard.

        S1 moved the /status stage-key enumeration behind ``**status_view(...)``,
        but ``pause_reason`` is a RuntimeState scalar that is NOT a stage-view
        key — the live branch must keep reading it straight from state, exactly
        as it did pre-S1. If the consolidation drops it, an evaluator_fail_closed
        parked thread would render ``pause_reason=null`` and the UI would show a
        plain resume button instead of the required approve/revise prompt. The
        history-file branch never hydrated pause_reason, so this pins the live
        path only.
        """
        graph = _live_graph()
        state = graph.aget_state.return_value
        state.values = {
            "session_id": "xhs_acct_abcdef12",
            "account_id": "acct-live",
            "phase": "paused",
            "current_agent": "evaluator",
            "pause_reason": "evaluator_fail_closed",
        }

        with (
            patch(
                "backend.api.routes._wf_application.assert_thread_owned",
                new_callable=AsyncMock,
                return_value="acct-live",
            ),
            patch("backend.api.routes._wf_application.is_pool_ready", return_value=True),
            patch(
                "backend.api.routes._wf_application._db_upsert",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("backend.api.routes._wf_application.db_get", new_callable=AsyncMock),
        ):
            resp = _client(graph).get("/api/workflow/status/xhs_acct_abcdef12")

        assert resp.status_code == 200
        assert resp.json()["data"]["pause_reason"] == "evaluator_fail_closed"


class TestStatusTimelineSource:
    """P1a-S2: /status builds agent_timeline from the Event store.

    Telemetry no longer rides the checkpoint, so the live branch must read the
    Event store instead of ``state.values["performance_log"]``. A legacy
    checkpoint that still carries the inline list keeps rendering (decision D1:
    no checkpoint rewrite).
    """

    def _get(self, graph: MagicMock):
        with (
            patch(
                "backend.api.routes._wf_application.assert_thread_owned",
                new_callable=AsyncMock,
                return_value="acct-live",
            ),
            patch("backend.api.routes._wf_application.is_pool_ready", return_value=True),
            patch(
                "backend.api.routes._wf_application._db_upsert",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("backend.api.routes._wf_application.db_get", new_callable=AsyncMock),
        ):
            return _client(graph).get("/api/workflow/status/xhs_acct_abcdef12")

    async def test_timeline_comes_from_event_store(self):
        from backend.db.workflow_events import append_events

        graph = _live_graph()
        await append_events(
            "xhs_acct_abcdef12",
            [
                {
                    "kind": "node",
                    "agent": "copywriter",
                    "started_at": "2026-09-13T00:00:00+00:00",
                    "completed_at": "2026-09-13T00:00:02+00:00",
                    "duration_seconds": 2.0,
                    "status": "success",
                    "error": None,
                    "retries": 0,
                },
                # non-node kinds share the store but not the timeline schema
                {"kind": "llm", "agent": "copywriter", "cost_usd": 0.01},
            ],
        )

        resp = self._get(graph)

        assert resp.status_code == 200
        timeline = resp.json()["data"]["agent_timeline"]
        assert [entry["agent"] for entry in timeline] == ["copywriter"]
        assert timeline[0]["status"] == "success"

    def test_legacy_inline_log_still_renders(self):
        graph = _live_graph()
        graph.aget_state.return_value.values = {
            "session_id": "xhs_acct_abcdef12",
            "account_id": "acct-live",
            "phase": "scouting",
            "current_agent": "trend_scout",
            # Pre-P1a checkpoint: telemetry inline.
            "performance_log": [
                {
                    "kind": "node",
                    "agent": "trend_scout",
                    "started_at": "2026-09-13T00:00:00+00:00",
                    "completed_at": "2026-09-13T00:00:01+00:00",
                    "status": "success",
                }
            ],
        }

        resp = self._get(graph)

        assert resp.status_code == 200
        timeline = resp.json()["data"]["agent_timeline"]
        assert [entry["agent"] for entry in timeline] == ["trend_scout"]


class TestStatusCarriesTheThreadsMode:
    """The write-back reads the thread's own mode, through the registry.

    ``/status`` used to read ``values.get("workflow_mode")`` inline, behind an
    ``if "workflow_mode" not in update_fields`` guard that could never be false
    (that dict is built a few lines above, from phase/status/progress/error and
    the label, and never carries the mode). The read now goes through
    ``backend/state/modes.py`` so the state key is known in one place; what must
    not change is that the value crosses over **unnormalised** -- a thread
    created before the S3a boundary keeps whatever it was created with, because
    rewriting it to the default would erase the only record that it predates the
    boundary.
    """

    def _upsert(self, graph: MagicMock) -> MagicMock:
        with (
            patch(
                "backend.api.routes._wf_application.assert_thread_owned",
                new_callable=AsyncMock,
                return_value="acct-live",
            ),
            patch("backend.api.routes._wf_application.is_pool_ready", return_value=True),
            patch(
                "backend.api.routes._wf_application._db_upsert",
                new_callable=AsyncMock,
                return_value=WorkflowRow(thread_id="xhs_acct_abcdef12", label="L"),
            ) as upsert_mock,
            patch("backend.api.routes._wf_application.db_get", new_callable=AsyncMock),
        ):
            resp = _client(graph).get("/api/workflow/status/xhs_acct_abcdef12")

        assert resp.status_code == 200
        return upsert_mock

    def test_the_threads_own_mode_is_written_back(self):
        graph = _live_graph()
        graph.aget_state.return_value.values = {
            **graph.aget_state.return_value.values,
            "workflow_mode": "brief",
        }

        upsert = self._upsert(graph)

        assert upsert.await_args.kwargs["workflow_mode"] == "brief"

    def test_an_unrecognised_mode_is_carried_through_unnormalised(self):
        graph = _live_graph()
        graph.aget_state.return_value.values = {
            **graph.aget_state.return_value.values,
            "workflow_mode": "brand_campaign",
        }

        upsert = self._upsert(graph)

        assert upsert.await_args.kwargs["workflow_mode"] == "brand_campaign"

    def test_a_thread_with_no_mode_does_not_overwrite_the_column(self):
        # ``_live_graph``'s values carry no workflow_mode at all -- the shape the
        # old ``if wm:`` test existed for, and the DB column's own
        # DEFAULT 'trend' still covers it.
        graph = _live_graph()

        upsert = self._upsert(graph)

        assert "workflow_mode" not in upsert.await_args.kwargs
