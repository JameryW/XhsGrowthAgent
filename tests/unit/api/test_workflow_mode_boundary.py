"""The request boundary that refuses an unknown workflow mode (P2c-S3a).

Before this slice ``WorkflowStartRequest.workflow_mode`` was a bare ``str``, so
``workflow_mode="brand_campaign"`` was accepted, stored in the checkpoint, and
then read at eight sites that each carried a ``"trend"`` default -- the run
behaved as trend and nothing anywhere said so.

Two halves, and the second matters as much as the first:

* the **request** model is typed, so an unknown value is refused with a 422 that
  names it;
* the **response** models stay ``str``. They echo what a stored row holds, and
  rows written before this boundary existed may hold anything, so narrowing them
  would turn exactly those threads into errors -- the red line that ``/status``
  keeps its full response shape.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api.deps import get_current_user
from backend.api.routes.workflow import (
    CheckpointSnapshot,
    WorkflowStartRequest,
    WorkflowStatusResponse,
)
from backend.api.routes.workflow import (
    router as workflow_router,
)
from backend.state.enums import WorkflowMode
from backend.state.modes import DEFAULT_WORKFLOW_MODE


class TestTheRequestModelRefuses:
    def test_it_names_the_value_it_refused(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            WorkflowStartRequest(workflow_mode="brand_campaign")
        message = str(excinfo.value)
        assert "brand_campaign" in message
        # The named error has to say what it would have accepted instead.
        assert "trend" in message and "brief" in message

    def test_the_declared_modes_pass(self) -> None:
        assert WorkflowStartRequest(workflow_mode="brief").workflow_mode is WorkflowMode.BRIEF
        assert WorkflowStartRequest(workflow_mode="trend").workflow_mode is WorkflowMode.TREND

    def test_the_default_is_the_declared_default(self) -> None:
        assert WorkflowStartRequest().workflow_mode is DEFAULT_WORKFLOW_MODE

    def test_the_field_is_the_enum_rather_than_a_string(self) -> None:
        assert WorkflowStartRequest.model_fields["workflow_mode"].annotation is WorkflowMode


class TestTheResponseModelsKeepTheirShape:
    def test_a_status_response_still_carries_an_unrecognised_value(self) -> None:
        row = WorkflowStatusResponse(
            thread_id="xhs_1",
            phase="scouting",
            current_agent="orchestrator",
            next_steps=[],
            workflow_mode="something_legacy",
        )
        assert row.workflow_mode == "something_legacy"

    def test_a_checkpoint_snapshot_still_carries_one(self) -> None:
        snapshot = CheckpointSnapshot(checkpoint_id="c1", workflow_mode="something_legacy")
        assert snapshot.workflow_mode == "something_legacy"

    def test_the_response_fields_are_still_strings(self) -> None:
        assert WorkflowStatusResponse.model_fields["workflow_mode"].annotation is str
        assert CheckpointSnapshot.model_fields["workflow_mode"].annotation is str


class TestOverHttp:
    def _client(self) -> TestClient:
        app = FastAPI()
        # The prefix lives where the app mounts the router (``backend/api/app.py``)
        # rather than on the router itself, so a stand-alone app has to add it.
        app.include_router(workflow_router, prefix="/api/workflow")

        async def _user() -> dict[str, str]:
            return {"id": "user-test", "username": "tester"}

        app.dependency_overrides[get_current_user] = _user
        return TestClient(app)

    def test_an_unknown_mode_never_reaches_the_handler(self) -> None:
        # A 422 here is FastAPI's body validation, so the handler (and with it
        # account resolution, the niche resolver and the graph) never runs --
        # which is what "refused at the boundary" has to mean.
        response = self._client().post(
            "/api/workflow/start", json={"workflow_mode": "brand_campaign"}
        )
        assert response.status_code == 422
        assert "brand_campaign" in response.text
