"""Unit tests for POST /api/evaluation/note — thread-less RQGM eval of a historical note.

Covers: note->state mapping (title/body/tags/cover_url/content_type), evaluator
invocation, missing niche safety, validation errors, missing note 404.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.db.accounts import AccountRow
from backend.services.creator_stats.types import NoteStats

_EXEC_PATCH = "backend.api.routes.evaluation._evaluator.execute"
_GET_NOTE = "backend.api.routes.evaluation.get_note_stats"
_GET_ACCOUNT = "backend.api.routes.evaluation.get_account"


@pytest.fixture
def client():
    graph = MagicMock()
    graph.store = MagicMock()
    app.state.graph = graph
    yield TestClient(app)
    if hasattr(app.state, "graph"):
        delattr(app.state, "graph")


def _note(**overrides) -> NoteStats:
    base = dict(
        note_id="n1",
        account_id="acct1",
        title="夏日穿搭分享",
        body_text="三套 OOTD，显瘦显高",
        tags=["穿搭", "OOTD"],
        cover_url="https://cdn.xhs.com/cover.jpg",
        content_type="note",
    )
    base.update(overrides)
    return NoteStats(**base)


def _account(niche: str = "fashion") -> AccountRow:
    return AccountRow(id="acct1", name="acct1", niche=niche, niche_source="manual")


def _patch_executor(result: dict | None = None):
    if result is None:
        result = {
            "overall_score": 82.0,
            "decision": "approved",
            "dimensions": [],
            "revision_hints": [],
            "bias_warning": "",
            "summary": "ok",
        }
    return patch(_EXEC_PATCH, AsyncMock(return_value={"evaluation_result": result}))


class TestRunNoteEvaluation:
    def test_maps_note_fields_to_eval_state_and_runs_evaluator(self, client):
        note = _note()
        with (
            patch(_GET_NOTE, AsyncMock(return_value=note)),
            patch(_GET_ACCOUNT, AsyncMock(return_value=_account())),
            _patch_executor() as mock_exec,
        ):
            r = client.post("/api/evaluation/note", json={"account_id": "acct1", "note_id": "n1"})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["account_id"] == "acct1"
        assert data["note_id"] == "n1"
        # A mock result without the required copywriting/compliance dimensions
        # is intentionally downgraded to a partial, scoreless result instead
        # of trusting a caller-supplied approval verdict.
        assert data["evaluation_result"]["decision"] is None
        assert data["evaluation_result"]["status"] == "partial"

        # state passed to EvaluatorAgent.execute carries the note fields
        state = mock_exec.call_args.args[0]
        copy_content = state["copy_content"]
        assert copy_content["selected_title"] == "夏日穿搭分享"
        assert copy_content["body_text"] == "三套 OOTD，显瘦显高"
        assert copy_content["hashtags"] == ["穿搭", "OOTD"]
        assert copy_content["cta"] == ""
        assert state["niche"] == "fashion"
        visual_plan = state["visual_plan"]
        assert visual_plan["image_urls"] == ["https://cdn.xhs.com/cover.jpg"]
        assert visual_plan["image_count"] == 1
        assert state["content_plan"]["content_type"] == "note"

    def test_cover_url_absent_yields_empty_image_urls(self, client):
        note = _note(cover_url="")
        with (
            patch(_GET_NOTE, AsyncMock(return_value=note)),
            patch(_GET_ACCOUNT, AsyncMock(return_value=_account())),
            _patch_executor() as mock_exec,
        ):
            r = client.post("/api/evaluation/note", json={"account_id": "acct1", "note_id": "n1"})
        assert r.status_code == 200, r.text
        visual_plan = mock_exec.call_args.args[0]["visual_plan"]
        assert visual_plan["image_urls"] == []
        assert visual_plan["image_count"] == 0

    def test_missing_account_niche_is_explicitly_unavailable(self, client):
        # Keep the fixture genuinely cold-start: a note with no niche signal
        # should remain unavailable rather than silently using a default.
        note = _note(title="随手记录", body_text="", tags=[])
        with (
            patch(_GET_NOTE, AsyncMock(return_value=note)),
            patch(_GET_ACCOUNT, AsyncMock(return_value=None)),
            _patch_executor() as mock_exec,
        ):
            r = client.post("/api/evaluation/note", json={"account_id": "acct1", "note_id": "n1"})
        assert r.status_code == 200, r.text
        state = mock_exec.call_args.args[0]
        assert state["niche"] == ""
        assert state["niche_context_available"] is False

    def test_missing_note_returns_404(self, client):
        with (
            patch(_GET_NOTE, AsyncMock(return_value=None)),
            patch(_GET_ACCOUNT, AsyncMock(return_value=_account())),
            _patch_executor() as mock_exec,
        ):
            r = client.post(
                "/api/evaluation/note", json={"account_id": "acct1", "note_id": "ghost"}
            )
        assert r.status_code == 404, r.text
        mock_exec.assert_not_called()

    def test_empty_account_id_rejected(self, client):
        r = client.post("/api/evaluation/note", json={"account_id": "", "note_id": "n1"})
        assert r.status_code == 400

    def test_empty_note_id_rejected(self, client):
        r = client.post("/api/evaluation/note", json={"account_id": "acct1", "note_id": ""})
        assert r.status_code == 400

    def test_passes_store_from_graph(self, client):
        note = _note()
        store = client.app.state.graph.store
        with (
            patch(_GET_NOTE, AsyncMock(return_value=note)),
            patch(_GET_ACCOUNT, AsyncMock(return_value=_account())),
            _patch_executor() as mock_exec,
        ):
            client.post("/api/evaluation/note", json={"account_id": "acct1", "note_id": "n1"})
        # EvaluatorAgent.execute(state, store) — store is positional arg #2
        assert mock_exec.call_args.args[1] is store
