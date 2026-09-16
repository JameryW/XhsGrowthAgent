"""POST /api/workflow/resume/{thread_id} — the publish-confirmation branch (P2a-S4b).

Same route as the evaluator pause, one gate further on.  What matters here is the
missing default.  brief / ripple / blogger all resume with a default action
because their default continues something a human already set in motion; this
gate cannot have one, because its default *is* the irreversible act.  So a body
without a decision must describe what to send and run nothing — an empty resume
must never read as a publish confirmation.

The graph is faked (parked at publish_gate) and execution is stubbed; the real
interrupt/resume round trip is covered by tests/integration/test_publish_gate_flow.py.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.state.enums import WorkflowPhase
from tests.unit.api.test_resume_evaluator_pause import (
    _DB_UPSERT,
    _START_RESUME,
    _client_for,
)

_RUN_AND_PERSIST = "backend.api.routes._runner._run_graph_and_persist"

#: What the stubbed run returns — the route echoes result["phase"] back.
_RUN_OK: dict[str, Any] = {"phase": WorkflowPhase.PUBLISHING}


def _awaiting_publish_values(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "thr1",
        "account_id": "acc1",
        "phase": WorkflowPhase.REVIEWING,
        "copy_content": {"selected_title": "露营装备清单"},
        "visual_plan": {"image_paths": ["a.jpg"]},
        "publish_result": {},
        "error": None,
    }
    base.update(overrides)
    return base


@contextlib.contextmanager
def _publish_env(
    values: dict[str, Any],
) -> Iterator[tuple[TestClient, MagicMock, AsyncMock, AsyncMock]]:
    """Client + fake graph parked at publish_gate, with execution stubbed out."""
    with _client_for(values) as (client, graph):
        # derive_status reads snapshot.next — that is what sends the route down
        # the AWAITING_PUBLISH branch instead of the legacy restart.
        graph.aget_state.return_value.next = ("publish_gate",)
        with (
            patch(_RUN_AND_PERSIST, new_callable=AsyncMock, return_value=_RUN_OK) as mock_run,
            patch(_START_RESUME, new_callable=AsyncMock) as mock_resume,
            patch(_DB_UPSERT, new_callable=AsyncMock),
        ):
            yield client, graph, mock_run, mock_resume


class TestWithoutADecisionNothingHappens:
    """No decision → describe the contract, execute nothing."""

    @pytest.mark.parametrize(
        "body",
        [
            None,
            {},
            {"resume_value": {}},
            {"resume_value": {"comments": "看着办"}},
            {"resume_value": "confirmed"},  # the bare value is not the contract
            {"resume_value": {"approved": True}},  # that is the review_gate dialect
        ],
    )
    def test_missing_decision_describes_what_to_send(self, body: Any):
        with _publish_env(_awaiting_publish_values()) as (client, graph, mock_run, mock_resume):
            resp = client.post("/api/workflow/resume/thr1", json=body)
            data = resp.json()["data"]

        assert resp.status_code == 200, resp.text
        assert data["status"] == "awaiting_publish"
        assert "confirmed" in data["message"]
        assert "cancelled" in data["message"]
        # Nothing ran: no graph execution, no background resume, no legacy restart
        # (falling through to the restart would re-run the whole pipeline).
        mock_run.assert_not_awaited()
        mock_resume.assert_not_awaited()
        graph.ainvoke.assert_not_awaited()
        graph.aupdate_state.assert_not_awaited()


class TestWithADecisionTheRunContinues:
    @pytest.mark.parametrize("decision", ["confirmed", "cancelled"])
    def test_the_decision_is_forwarded_verbatim(self, decision: str):
        with _publish_env(_awaiting_publish_values()) as (client, graph, mock_run, _):
            resp = client.post(
                "/api/workflow/resume/thr1", json={"resume_value": {"decision": decision}}
            )
            data = resp.json()["data"]

        assert resp.status_code == 200, resp.text
        assert data["status"] == "running"
        command = mock_run.await_args.args[3]
        assert command.resume == {"decision": decision}
        assert mock_run.await_args.kwargs["source"] == "publish_confirmation"

    def test_comments_travel_with_the_decision(self):
        body = {"resume_value": {"decision": "cancelled", "comments": "标题不合适"}}
        with _publish_env(_awaiting_publish_values()) as (client, _, mock_run, _):
            resp = client.post("/api/workflow/resume/thr1", json=body)

        assert resp.status_code == 200, resp.text
        assert mock_run.await_args.args[3].resume == {
            "decision": "cancelled",
            "comments": "标题不合适",
        }

    def test_an_unknown_decision_is_still_forwarded_not_guessed(self):
        """The route does not second-guess the decision — the gate refuses it.

        Deciding here would create a second source of truth for "is this a yes?";
        the gate's default-refuse is the only place that question is answered.
        """
        body = {"resume_value": {"decision": "yolo"}}
        with _publish_env(_awaiting_publish_values()) as (client, _, mock_run, _):
            resp = client.post("/api/workflow/resume/thr1", json=body)

        assert resp.status_code == 200, resp.text
        assert mock_run.await_args.args[3].resume == {"decision": "yolo"}
        assert mock_run.await_args.kwargs["source"] == "publish_confirmation"
