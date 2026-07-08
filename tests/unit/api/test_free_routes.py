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
        item.key = key
        item.namespace = ns
        return item

    async def _alist(*, namespace_prefix, limit=100):
        # Return Item-like objects for every record under this namespace prefix.
        items = []
        for key, value in store._records.items():
            item = MagicMock()
            item.key = key
            item.value = value
            item.namespace = namespace_prefix
            items.append(item)
        return items[:limit]

    async def _adelete(ns, *, key=None):
        # adelete(namespace, key) — key may be positional or kw; tolerate both.
        k = key if key is not None else ns
        store._records.pop(k, None)

    store.aput = AsyncMock(side_effect=_aput)
    store.aget = AsyncMock(side_effect=_aget)
    store.alist = AsyncMock(side_effect=_alist)
    store.adelete = AsyncMock(side_effect=_adelete)
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


class TestListDrafts:
    def test_list_returns_seeded_drafts(self, client, mock_store):
        client.post("/api/free/draft", json=DRAFT_BODY)
        client.post(
            "/api/free/draft",
            json={**DRAFT_BODY, "title": "第二篇"},
        )
        r = client.get("/api/free/drafts/acct1")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["account_id"] == "acct1"
        assert len(data["drafts"]) == 2
        titles = {d["title"] for d in data["drafts"]}
        assert "夏日穿搭" in titles and "第二篇" in titles
        # summary only — no full body in list payload
        assert "body" not in data["drafts"][0]

    def test_list_empty_when_no_drafts(self, client):
        r = client.get("/api/free/drafts/acct1")
        assert r.status_code == 200
        assert r.json()["data"]["drafts"] == []

    def test_list_no_store_returns_400(self, client):
        app.state.graph.store = None
        r = client.get("/api/free/drafts/acct1")
        assert r.status_code == 400


class TestUpdateDraft:
    def test_update_overwrites_fields_keeps_draft_id(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        r = client.patch(
            f"/api/free/draft/{draft_id}?account_id=acct1",
            json={"title": "改过的标题", "hashtags": ["新标签"]},
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["draft_id"] == draft_id  # draft_id unchanged
        assert data["draft"]["title"] == "改过的标题"
        assert data["draft"]["hashtags"] == ["新标签"]
        # untouched fields preserved
        assert data["draft"]["body"] == DRAFT_BODY["body"]

    def test_update_missing_draft_returns_400(self, client):
        r = client.patch(
            "/api/free/draft/nope?account_id=acct1",
            json={"title": "x"},
        )
        assert r.status_code == 400

    def test_update_no_store_returns_400(self, client):
        app.state.graph.store = None
        r = client.patch(
            "/api/free/draft/any?account_id=acct1",
            json={"title": "x"},
        )
        assert r.status_code == 400


class TestDeleteDraft:
    def test_delete_removes_draft(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        r = client.delete(f"/api/free/draft/{draft_id}?account_id=acct1")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["deleted"] is True
        # gone from store
        assert mock_store._records.get(draft_id) is None

    def test_delete_idempotent_for_missing(self, client, mock_store):
        r = client.delete("/api/free/draft/never-existed?account_id=acct1")
        assert r.status_code == 200
        assert r.json()["data"]["deleted"] is True

    def test_delete_no_store_returns_400(self, client):
        app.state.graph.store = None
        r = client.delete("/api/free/draft/any?account_id=acct1")
        assert r.status_code == 400
