"""What ``POST /start`` starts, now that its intent is a value (P2c-S3b).

The endpoint used to build its graph input from a 24-key literal and then patch
one key when the mode was ``brief``. Two of those keys are what this file is
about:

* **``phase``** came straight from the request. It never decided anything: the
  graph's entry is always ``orchestrator`` (``backend/graph/builder.py``) and
  that node unconditionally writes the mode's phase
  (``OrchestratorAgent.execute``), so a caller-supplied phase only made this
  endpoint's response and the DB row name a phase the graph was not in --
  ``phase=analyzing`` on a trend run answered ``"analyzing"`` while the run
  started at ``scouting``. The field is gone; the phase is the mode's.
* **``brief_content`` versus ``artifacts.brief_content``** depended on whether
  the artifact store accepted the body. That pair is
  ``backend.state.goal.BriefInput`` now.

The response's ``phase`` staying honest is the observable half of the change: it
is the phase the graph is about to be in, not the one somebody asked for.
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes import _runner
from backend.api.routes.workflow import WorkflowStartRequest, get_progress
from backend.api.routes.workflow import router as workflow_router
from backend.state.enums import WorkflowMode

_NICHE_PATH = "backend.services.niche_resolver.resolve_account_niche"
#: The fourth positional argument of ``_run_graph_and_persist`` -- the mapping a
#: run starts from. Read off the call rather than off the state, because the
#: graph input is the thing under test.
_GRAPH_INPUT_ARG = 3


def _client(graph: Any) -> TestClient:
    app = FastAPI()
    # The prefix lives where the app mounts the router (``backend/api/app.py``)
    # rather than on the router itself, so a stand-alone app has to add it.
    app.include_router(workflow_router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def _graph(store: Any = None) -> MagicMock:
    graph = MagicMock()
    graph.store = InMemoryStore() if store is None else store
    graph.aupdate_state = AsyncMock()
    return graph


@contextlib.contextmanager
def _start_env(run_mock: AsyncMock, upsert_mock: AsyncMock):
    """Everything ``/start`` touches outside its own logic."""
    niche_res = MagicMock()
    niche_res.niche = "母婴"
    niche_res.to_dict = MagicMock(return_value={"source": "inferred"})

    with (
        patch(
            "backend.api.routes.workflow.resolve_required_account_id",
            new_callable=AsyncMock,
            return_value="acc1",
        ),
        patch(
            "backend.api.routes.workflow.require_owned_account",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.api.routes.workflow.is_pool_ready", return_value=False),
        patch("backend.api.routes.workflow._db_upsert", upsert_mock),
        patch("backend.api.routes._runner._run_graph_and_persist", run_mock),
        patch(_NICHE_PATH, new_callable=AsyncMock, return_value=niche_res),
    ):
        yield


def _start(payload: dict[str, Any], graph: MagicMock | None = None, *, async_mode: bool = False):
    """POST /start and hand back (response, run_mock, upsert_mock, graph).

    ``async_mode`` matters to the *response*: the synchronous branch answers from
    the DB row, which is unavailable under test, while the asynchronous one
    answers from the phase the run was compiled with. Tests that are about the
    response ask for the latter; everything else stays synchronous so that no run
    is left registered in the runner's task registry.
    """
    graph = graph or _graph()
    run_mock = AsyncMock(return_value={})
    upsert_mock = AsyncMock(return_value=None)
    with _start_env(run_mock, upsert_mock):
        try:
            resp = _client(graph).post(
                "/api/workflow/start",
                json={"account_id": "acc1", "async_mode": async_mode, **payload},
            )
        finally:
            # The asynchronous branch registers the run; leaving it there would
            # let a later test see a live execution for a thread it invented.
            _runner._background_tasks.clear()
    return resp, run_mock, upsert_mock, graph


class TestTheRequestNoLongerOffersAPhase:
    def test_the_field_is_gone(self) -> None:
        # Reverse assertion: adding ``phase`` back would make this file's subject
        # -- that the mode owns the start phase -- no longer true, so it must not
        # pass quietly.
        assert "phase" not in WorkflowStartRequest.model_fields

    def test_a_client_still_sending_one_is_not_refused(self) -> None:
        # ``extra="ignore"`` (pydantic's default) is why removing the field is
        # backward compatible. If the model ever turns ``extra="forbid"`` on,
        # this becomes a 422 and this test is where that shows up.
        resp, _, _, _ = _start({"phase": "analyzing", "workflow_mode": "trend"})
        assert resp.status_code == 200, resp.text

    def test_a_client_still_sending_one_changes_nothing(self) -> None:
        with_phase, run_with, _, _ = _start({"phase": "analyzing", "workflow_mode": "trend"})
        without_phase, run_without, _, _ = _start({"workflow_mode": "trend"})
        assert with_phase.status_code == without_phase.status_code == 200

        def _stable(call: AsyncMock) -> dict[str, Any]:
            # ``thread_id`` (a random suffix) and ``created_at`` (now) are the
            # two keys a run is allowed to differ in.
            state = dict(call.await_args.args[_GRAPH_INPUT_ARG])
            state.pop("thread_id")
            state.pop("session_id")
            state.pop("created_at")
            state.pop("updated_at")
            return state

        assert _stable(run_with) == _stable(run_without)


class TestTheStartPhaseIsTheModes:
    def test_a_trend_run_starts_at_scouting(self) -> None:
        resp, run_mock, _, _ = _start({"workflow_mode": "trend"})
        assert resp.status_code == 200, resp.text
        assert run_mock.await_args.args[_GRAPH_INPUT_ARG]["phase"] == "scouting"

    def test_a_trend_run_starts_at_scouting_however_it_asked(self) -> None:
        # The regression this slice exists for: the request asked for
        # ``analyzing`` and the graph started at ``scouting`` regardless -- but
        # the response used to agree with the request, not the graph.
        resp, run_mock, _, _ = _start(
            {"workflow_mode": "trend", "phase": "analyzing"}, async_mode=True
        )
        assert run_mock.await_args.args[_GRAPH_INPUT_ARG]["phase"] == "scouting"
        assert resp.json()["data"]["phase"] == "scouting"

    def test_a_brief_run_starts_at_briefing(self) -> None:
        resp, run_mock, upsert_mock, _ = _start(
            {"workflow_mode": "brief", "brief_text": "这是 brief 原文"}
        )
        assert resp.status_code == 200, resp.text
        assert run_mock.await_args.args[_GRAPH_INPUT_ARG]["phase"] == "briefing"
        assert upsert_mock.await_args_list[0].kwargs["phase"] == "briefing"

    def test_the_response_names_the_phase_the_graph_is_about_to_be_in(self) -> None:
        resp, run_mock, _, _ = _start({"workflow_mode": "trend"}, async_mode=True)
        assert resp.json()["data"]["phase"] == run_mock.await_args.args[_GRAPH_INPUT_ARG]["phase"]

    def test_the_db_row_is_written_with_the_same_phase(self) -> None:
        # The row and the graph used to disagree in exactly one case (a
        # non-default request phase on a trend run); the row is now derived from
        # the same fact the graph is.
        _, run_mock, upsert_mock, _ = _start({"workflow_mode": "trend", "phase": "analyzing"})
        first_call = upsert_mock.await_args_list[0]
        assert first_call.kwargs["phase"] == "scouting"
        assert first_call.kwargs["phase"] == run_mock.await_args.args[_GRAPH_INPUT_ARG]["phase"]

    def test_the_progress_percent_matches_the_phase_it_reports(self) -> None:
        resp, _, _, _ = _start({"workflow_mode": "trend"}, async_mode=True)
        data = resp.json()["data"]
        assert data["progress_percent"] == get_progress(data["phase"])


class TestBriefModeWaiting:
    def test_a_brief_run_without_a_body_parks_instead_of_starting(self) -> None:
        resp, run_mock, upsert_mock, graph = _start({"workflow_mode": "brief"})
        assert resp.json()["data"]["status"] == "awaiting_brief"
        assert resp.json()["data"]["phase"] == "briefing"
        # No graph run at all -- the upload triggers it later.
        assert run_mock.await_count == 0
        graph.aupdate_state.assert_awaited_once()
        # The checkpoint holds the phase the graph will resume in.
        written = graph.aupdate_state.await_args.args[1]
        assert written["phase"] == "briefing"
        assert upsert_mock.await_args_list[-1].kwargs["status"] == "awaiting_brief"

    def test_a_trend_run_never_parks(self) -> None:
        _, run_mock, _, graph = _start({"workflow_mode": "trend"})
        assert run_mock.await_count == 1
        assert graph.aupdate_state.await_count == 0

    def test_a_brief_run_whose_body_the_store_took_carries_the_ref(self) -> None:
        _, run_mock, _, _ = _start({"workflow_mode": "brief", "brief_text": "这是 brief 原文"})
        state = run_mock.await_args.args[_GRAPH_INPUT_ARG]
        assert state["artifacts"]["brief_content"]["ref"] == "artifact://brief_content/latest"
        assert "brief_content" not in state

    def test_a_brief_run_whose_store_declined_keeps_the_body_inline(self) -> None:
        graph = _graph()
        graph.store = None  # no store at all: put_artifact declines
        _, run_mock, _, _ = _start(
            {"workflow_mode": "brief", "brief_text": "这是 brief 原文"}, graph
        )
        state = run_mock.await_args.args[_GRAPH_INPUT_ARG]
        assert state["brief_content"] == {"raw_text": "这是 brief 原文", "source_type": "text"}
        assert "artifacts" not in state

    def test_a_trend_run_never_carries_a_brief_body(self) -> None:
        # ``brief_text`` on a trend run was ignored before this slice and still is;
        # the mode decides whether there is a body to place at all.
        _, run_mock, _, _ = _start({"workflow_mode": "trend", "brief_text": "无关正文"})
        state = run_mock.await_args.args[_GRAPH_INPUT_ARG]
        assert "brief_content" not in state
        assert "artifacts" not in state


class TestTheModeReachesTheGraphInput:
    def test_it_arrives_as_the_mode_it_was_asked_for(self) -> None:
        _, run_mock, _, _ = _start({"workflow_mode": "brief", "brief_text": "x"})
        assert run_mock.await_args.args[_GRAPH_INPUT_ARG]["workflow_mode"] is WorkflowMode.BRIEF

    def test_the_default_is_the_declared_default(self) -> None:
        _, run_mock, _, _ = _start({})
        assert run_mock.await_args.args[_GRAPH_INPUT_ARG]["workflow_mode"] is WorkflowMode.TREND
