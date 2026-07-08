"""Unit tests for the free creation API routes (thread-less standalone)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app


@pytest.fixture
def mock_store():
    """In-memory BaseStore double — records aput calls, serves them via aget."""
    store = MagicMock()
    store._records: dict[str, dict] = {}

    async def _aput(ns, *, key, value):
        store._records[key] = value

    async def _aget(ns, *, key):
        rec = store._records.get(key)
        if rec is None:
            return None
        item = MagicMock()
        item.value = rec
        return item

    store.aput = AsyncMock(side_effect=_aput)
    store.aget = AsyncMock(side_effect=_aget)
    return store


@pytest.fixture
def client(mock_store):
    graph = MagicMock()
    graph.store = mock_store
    app.state.graph = graph
    yield TestClient(app)
    if hasattr(app.state, "graph"):
        delattr(app.state, "graph")


DRAFT_BODY = {
    "account_id": "acct1",
    "title": "夏日穿搭",
    "body": "三套夏日 OOTD",
    "hashtags": ["穿搭", "OOTD"],
    "image_paths": ["/tmp/a.png"],
    "niche": "fashion",
}


class TestCreateDraft:
    def test_create_returns_draft_id_and_persists(self, client, mock_store):
        r = client.post("/api/free/draft", json=DRAFT_BODY)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert "draft_id" in data
        assert data["draft"]["title"] == "夏日穿搭"
        # persisted to store
        assert mock_store.aput.await_count == 1
        ns_arg = mock_store.aput.call_args.args[0]
        assert ns_arg == ("accounts", "acct1", "free_drafts")

    def test_create_defaults_account_id(self, client):
        body = {**DRAFT_BODY}
        del body["account_id"]
        r = client.post("/api/free/draft", json=body)
        assert r.status_code == 200
        assert r.json()["data"]["draft"]["account_id"] == "default"


class TestEvaluateDraft:
    def test_evaluate_loads_draft_and_runs_evaluator(self, client, mock_store):
        # seed a draft
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        eval_result = {"overall_score": 88.0, "decision": "approved"}
        with patch(
            "backend.api.routes.free._evaluator.execute",
            AsyncMock(return_value={"evaluation_result": eval_result}),
        ):
            r = client.post(
                "/api/free/evaluate", json={"account_id": "acct1", "draft_id": draft_id}
            )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["draft_id"] == draft_id
        assert data["evaluation_result"]["decision"] == "approved"

    def test_evaluate_missing_draft_returns_400(self, client):
        r = client.post(
            "/api/free/evaluate",
            json={"account_id": "acct1", "draft_id": "nope"},
        )
        assert r.status_code == 400

    def test_evaluate_empty_draft_id_returns_400(self, client):
        r = client.post("/api/free/evaluate", json={"account_id": "acct1", "draft_id": ""})
        assert r.status_code == 400


class TestPublishDraft:
    def test_publish_loads_draft_and_runs_run_publish(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        pub_result = {
            "post_id": "x123",
            "post_url": "https://xhs/explore/x123",
            "status": "published",
        }
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": pub_result}),
        ) as rp:
            r = client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["publish_result"]["post_id"] == "x123"
        # run_publish was called with a synthesized state carrying the draft content
        state_arg = rp.call_args.args[0]
        assert state_arg["copy_content"]["selected_title"] == "夏日穿搭"
        assert state_arg["publish_options"]["account_id"] == "acct1"

    def test_publish_missing_draft_returns_400(self, client):
        r = client.post(
            "/api/free/publish",
            json={"account_id": "acct1", "draft_id": "nope"},
        )
        assert r.status_code == 400

    def test_publish_no_store_returns_400(self, client):
        # graph.store = None → cannot publish
        app.state.graph.store = None
        r = client.post(
            "/api/free/publish",
            json={"account_id": "acct1", "draft_id": "any"},
        )
        assert r.status_code == 400
