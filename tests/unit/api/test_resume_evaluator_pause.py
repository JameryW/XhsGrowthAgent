"""POST /api/workflow/resume/{thread_id} — evaluator fail-closed continuation.

P0-W5 round 2: a thread the evaluator parked (phase=paused +
pause_reason="evaluator_fail_closed") must NOT be resumable by the legacy
whole-pipeline restart. A human decision in the request body drives it:

  {"human_decision": "approve"} → gate patched to APPROVED, the run continues to
  the publisher without re-running upstream agents;
  {"human_decision": "revise"}  → gate patched to NEEDS_REVISION with a fresh
  revision budget;
  missing/invalid decision      → 4xx, nothing written, nothing restarted.

Compliance blocks are human-overridable BY DESIGN — fail-closed means "requires
a human", never "forbidden".
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.workflow import router
from backend.graph.routers import PAUSE_REASON_EVALUATOR_FAIL_CLOSED, evaluator_requires_human
from backend.state.enums import WorkflowPhase

_START_RESUME = "backend.api.routes._wf_runtime._start_resume_task"
# The legacy (non-evaluator) restart starts the resume from the endpoint body,
# which lives in the application layer -- a different namespace to patch.
_START_RESUME_LEGACY = "backend.api.routes._wf_application._start_resume_task"
_DB_UPSERT = "backend.api.routes._wf_application._db_upsert"


def _paused_evaluator_values(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "thr1",
        "account_id": "acc1",
        "phase": WorkflowPhase.PAUSED,
        "prev_phase": WorkflowPhase.REVIEWING,
        "pause_reason": PAUSE_REASON_EVALUATOR_FAIL_CLOSED,
        "revision_count": 2,
        "error": None,
        "copy_content": {"selected_title": "t", "body_text": "b"},
        "publish_options": {"dry_run": True},
        "evaluation_result": {
            "overall_score": None,
            "decision": None,
            "status": "degraded",
            "degraded": True,
            "dimensions": [{"dimension": "compliance", "score": 10, "is_blocking": True}],
            "revision_hints": [],
            "summary": "评估器异常，评估未完成",
        },
    }
    base.update(overrides)
    return base


def _make_graph(values: dict[str, Any]) -> MagicMock:
    graph = MagicMock()
    graph.store = MagicMock(name="store")
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = ()
    snapshot.tasks = ()
    snapshot.interrupts = []
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    graph.ainvoke = AsyncMock(return_value=values)
    return graph


@contextlib.contextmanager
def _client_for(values: dict[str, Any]) -> Iterator[tuple[TestClient, MagicMock]]:
    """Mounted router + fake graph, with thread ownership resolved (no DB)."""
    from backend.api.deps import get_current_user
    from backend.api.middleware import error_handler_middleware
    from backend.db.accounts import AccountRow
    from backend.db.workflows import WorkflowRow

    graph = _make_graph(values)
    app = FastAPI()
    app.include_router(router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    owned = AccountRow(id="acc1", name="acc1", is_active=True, owner_user_id="user-test")
    with (
        patch("backend.api.account_scope.get_account", AsyncMock(return_value=owned)),
        patch(
            "backend.db.workflows.get_workflow",
            AsyncMock(return_value=WorkflowRow(thread_id="thr1", account_id="acc1")),
        ),
    ):
        yield TestClient(app), graph


@contextlib.contextmanager
def _resume_env(
    values: dict[str, Any], *, start_resume: str = _START_RESUME
) -> Iterator[tuple[TestClient, MagicMock, AsyncMock]]:
    """Client + fake graph, with the background resume and DB writes stubbed out."""
    with (
        _client_for(values) as (client, graph),
        patch(start_resume, new_callable=AsyncMock) as mock_resume,
        patch(_DB_UPSERT, new_callable=AsyncMock),
    ):
        yield client, graph, mock_resume


class TestMissingDecisionIsRejected:
    """No/bogus human_decision → 4xx and NO legacy pipeline restart."""

    @pytest.mark.parametrize("body", [None, {}, {"human_decision": "yolo"}, {"human_decision": ""}])
    def test_resume_without_valid_decision_is_4xx(self, body):
        with _resume_env(_paused_evaluator_values()) as (client, graph, mock_resume):
            resp = client.post("/api/workflow/resume/thr1", json=body)

            assert resp.status_code == 400, resp.text
            payload = resp.json()
            assert payload["success"] is False
            assert "human_decision" in str(payload)
            # Nothing written, nothing restarted — no silent pipeline re-run.
            graph.aupdate_state.assert_not_awaited()
            mock_resume.assert_not_awaited()
            graph.ainvoke.assert_not_awaited()

    def test_legacy_pause_resume_is_untouched(self):
        """A plain user pause (no pause_reason) keeps the old restart semantics."""
        with _resume_env(
            _paused_evaluator_values(pause_reason=None), start_resume=_START_RESUME_LEGACY
        ) as (
            client,
            graph,
            mock_resume,
        ):
            resp = client.post("/api/workflow/resume/thr1")
            body = resp.json()["data"]

        assert resp.status_code == 200, resp.text
        assert body["status"] == "running"
        # Legacy path patches with the checkpoint's own as_node (NOT the gate).
        assert graph.aupdate_state.await_args.kwargs["as_node"] != "evaluator_gate"
        mock_resume.assert_awaited_once()


class TestApproveDecisionContinuesToPublisher:
    """approve → gate patched to APPROVED, execution continues at publisher."""

    def test_approve_patches_gate_and_continues(self):
        values = _paused_evaluator_values()
        with _resume_env(values) as (client, graph, mock_resume):
            resp = client.post("/api/workflow/resume/thr1", json={"human_decision": "approve"})
            body = resp.json()["data"]

        assert resp.status_code == 200, resp.text
        assert body["status"] == "running"
        assert body["human_decision"] == "approve"
        # Continued at the gate — never the whole-pipeline (SCOUTING) restart.
        assert body["phase"] == WorkflowPhase.PUBLISHING

        call = graph.aupdate_state.await_args
        assert call.kwargs["as_node"] == "evaluator_gate"
        updates = call.args[1]
        assert updates["pause_reason"] is None
        evaluation = updates["evaluation_result"]
        assert str(evaluation["decision"]) == "approved"
        assert evaluation.get("degraded") is False
        assert evaluation.get("status") != "degraded"
        # The human decision is auditable in the checkpoint.
        assert evaluation["human_override"]["decision"] == "approve"

        # The resumed run starts from the publishing phase, not from scouting.
        assert mock_resume.await_args.args[3] == WorkflowPhase.PUBLISHING

        # The patched result satisfies the SHARED predicate (single source of
        # truth with the evaluator node / router).
        assert evaluator_requires_human({**values, **updates}) is False


class TestReviseDecisionTakesFreshBudget:
    """revise → NEEDS_REVISION with a fresh revision budget, routed to revise."""

    def test_revise_resets_budget_and_continues(self):
        with _resume_env(_paused_evaluator_values(revision_count=2)) as (
            client,
            graph,
            mock_resume,
        ):
            resp = client.post("/api/workflow/resume/thr1", json={"human_decision": "revise"})
            body = resp.json()["data"]

        assert resp.status_code == 200, resp.text
        assert body["human_decision"] == "revise"

        call = graph.aupdate_state.await_args
        assert call.kwargs["as_node"] == "evaluator_gate"
        updates = call.args[1]
        evaluation = updates["evaluation_result"]
        assert str(evaluation["decision"]) == "needs_revision"
        assert evaluation.get("revision_hints"), "the writer needs a revision hint"
        # Fresh budget for the human-initiated cycle (the cap was already hit).
        assert updates["revision_count"] == 0
        assert updates["pause_reason"] is None
        mock_resume.assert_awaited_once()
        assert mock_resume.await_args.args[3] != WorkflowPhase.SCOUTING
