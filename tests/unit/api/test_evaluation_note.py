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
_GET_BUNDLE = "backend.db.creator_stats.get_creator_stats_snapshot_bundle"
_GET_ACCOUNT = "backend.api.routes.evaluation.get_account"


@pytest.fixture
def client():
    from backend.api.deps import get_current_user

    graph = MagicMock()
    graph.store = MagicMock()
    app.state.graph = graph

    async def _user():
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user

    # Owned by the overridden console user so account_scope checks pass.
    owned = AccountRow(id="acct1", name="acct1", owner_user_id="user-test")

    with (
        # account_scope imports get_account directly; resolve_required_account_id /
        # require_owned_account / assert_note_owned all resolve through it.
        patch("backend.api.account_scope.get_account", AsyncMock(return_value=owned)),
        # No active/owned fallback: an empty account_id must stay a 400.
        patch("backend.api.account_scope.get_active_account", AsyncMock(return_value=None)),
        patch("backend.api.account_scope.list_accounts", AsyncMock(return_value=[])),
        # assert_note_owned imports get_note_stats from backend.db.creator_stats.
        patch("backend.db.creator_stats.get_note_stats", AsyncMock(return_value=_note())),
    ):
        yield TestClient(app)

    app.dependency_overrides.pop(get_current_user, None)
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


def _bundle(note: NoteStats, snapshot_id: str = "snapshot:test") -> dict:
    return {
        "account_id": note.account_id,
        "account": None,
        "notes": [note],
        "data_as_of": note.synced_at or "2026-07-22T10:00:00Z",
        "snapshot_id": snapshot_id,
        "note_count": 1,
    }


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
            patch(_GET_BUNDLE, AsyncMock(return_value=_bundle(note))),
            patch(_GET_ACCOUNT, AsyncMock(return_value=_account())),
            _patch_executor() as mock_exec,
        ):
            r = client.post("/api/evaluation/note", json={"account_id": "acct1", "note_id": "n1"})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["account_id"] == "acct1"
        assert data["note_id"] == "n1"
        assert data["snapshot_id"] == "snapshot:test"
        assert data["source"]["snapshot_id"] == "snapshot:test"
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
            patch(_GET_BUNDLE, AsyncMock(return_value=_bundle(note))),
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
            patch(_GET_BUNDLE, AsyncMock(return_value=_bundle(note))),
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
            patch(
                _GET_BUNDLE,
                AsyncMock(
                    return_value={
                        "account_id": "acct1",
                        "account": None,
                        "notes": [],
                        "data_as_of": None,
                        "snapshot_id": None,
                        "note_count": 0,
                    }
                ),
            ),
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
            patch(_GET_BUNDLE, AsyncMock(return_value=_bundle(note))),
            patch(_GET_ACCOUNT, AsyncMock(return_value=_account())),
            _patch_executor() as mock_exec,
        ):
            client.post("/api/evaluation/note", json={"account_id": "acct1", "note_id": "n1"})
        # EvaluatorAgent.execute(state, store) — store is positional arg #2
        assert mock_exec.call_args.args[1] is store

    def test_latest_marks_run_stale_when_creator_stats_snapshot_changes(self, client):
        from backend.api.routes.evaluation import (
            HISTORICAL_ASSESSMENT_TYPE,
            HISTORICAL_SUBJECT_TYPE,
        )
        from backend.db import quality_evaluations

        note = _note(synced_at="2026-07-22T10:00:00Z")
        run = quality_evaluations.new_run(
            account_id="acct1",
            subject_type=HISTORICAL_SUBJECT_TYPE,
            subject_id="n1",
            assessment_type=HISTORICAL_ASSESSMENT_TYPE,
            source_content_hash="sha256:content",
            source_data_as_of=note.synced_at,
            context_hash="sha256:context",
            evaluator_fingerprint="rqgm:test",
        )
        run.status = "ready"
        run.result_json = {
            "status": "ready",
            "source": {"snapshot_id": "snapshot:old"},
            "overall_score": 80,
        }
        with (
            patch(
                "backend.db.quality_evaluations.get_latest_for_subject",
                AsyncMock(return_value=run),
            ),
            patch(
                _GET_BUNDLE,
                AsyncMock(
                    return_value={**_bundle(note, "snapshot:new"), "data_as_of": note.synced_at}
                ),
            ),
            patch(_GET_ACCOUNT, AsyncMock(return_value=_account())),
            patch(
                "backend.db.quality_evaluations.mark_subject_stale",
                AsyncMock(return_value=1),
            ) as mark_stale,
        ):
            response = client.get("/api/evaluation/note/acct1/n1/latest")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["stale"] is True
        assert data["snapshot_id"] == "snapshot:old"
        mark_stale.assert_awaited_once()
