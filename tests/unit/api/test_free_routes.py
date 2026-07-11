"""Unit tests for the free creation API routes (thread-less standalone)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.services.xhs_client import XHSAnalytics


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

    async def _asearch(ns, query="", limit=100):
        # asearch(namespace, query, limit) — empty query returns all items.
        # Mirrors AsyncPostgresStore/InMemoryStore asearch semantics.
        items = []
        for key, value in store._records.items():
            item = MagicMock()
            item.key = key
            item.value = value
            item.namespace = ns
            items.append(item)
        return items[:limit]

    async def _adelete(ns, *, key=None):
        # adelete(namespace, key) — key may be positional or kw; tolerate both.
        k = key if key is not None else ns
        store._records.pop(k, None)

    store.aput = AsyncMock(side_effect=_aput)
    store.aget = AsyncMock(side_effect=_aget)
    store.asearch = AsyncMock(side_effect=_asearch)
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

    def test_create_sets_timestamps_and_default_metadata(self, client, mock_store):
        r = client.post("/api/free/draft", json=DRAFT_BODY)
        assert r.status_code == 200, r.text
        draft = r.json()["data"]["draft"]
        assert "created_at" in draft and draft["created_at"]
        assert "updated_at" in draft and draft["updated_at"]
        assert draft["created_at"] == draft["updated_at"]
        assert draft["last_evaluation"] is None
        assert draft["published"] is False

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

    def test_evaluate_writes_last_evaluation_back_to_draft(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        eval_result = {
            "overall_score": 72.0,
            "decision": "needs_revision",
            "revision_hints": ["标题需更有吸引力", "正文缺开头钩子"],
        }
        with patch(
            "backend.api.routes.free._evaluator.execute",
            AsyncMock(return_value={"evaluation_result": eval_result}),
        ):
            client.post("/api/free/evaluate", json={"account_id": "acct1", "draft_id": draft_id})
        # draft in store now has last_evaluation persisted with the triple
        stored = mock_store._records[draft_id]
        assert stored["last_evaluation"] == {
            "overall_score": 72.0,
            "decision": "needs_revision",
            "revision_hints": ["标题需更有吸引力", "正文缺开头钩子"],
        }
        assert "updated_at" in stored and stored["updated_at"]
        # full evaluation_result not stored on draft — only the triple
        assert "evaluation_result" not in stored

    def test_evaluate_approved_writes_empty_revision_hints(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        eval_result = {"overall_score": 92.0, "decision": "approved", "revision_hints": []}
        with patch(
            "backend.api.routes.free._evaluator.execute",
            AsyncMock(return_value={"evaluation_result": eval_result}),
        ):
            client.post("/api/free/evaluate", json={"account_id": "acct1", "draft_id": draft_id})
        stored = mock_store._records[draft_id]
        # approved drafts persist revision_hints as [] (not None)
        assert stored["last_evaluation"]["revision_hints"] == []

    def test_evaluate_missing_revision_hints_defaults_to_empty(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        # evaluator result omits revision_hints entirely (e.g. older code path)
        eval_result = {"overall_score": 80.0, "decision": "approved"}
        with patch(
            "backend.api.routes.free._evaluator.execute",
            AsyncMock(return_value={"evaluation_result": eval_result}),
        ):
            client.post("/api/free/evaluate", json={"account_id": "acct1", "draft_id": draft_id})
        stored = mock_store._records[draft_id]
        # absent revision_hints degrades to [] (the `or []` guard)
        assert stored["last_evaluation"]["revision_hints"] == []

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

    def test_publish_success_marks_draft_published(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        pub_result = {"post_id": "x123", "status": "published"}
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": pub_result}),
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        stored = mock_store._records[draft_id]
        assert stored["published"] is True
        assert "updated_at" in stored and stored["updated_at"]

    def test_publish_persists_post_id_and_post_url(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        pub_result = {
            "post_id": "note_abc",
            "post_url": "https://www.xiaohongshu.com/explore/note_abc",
            "status": "published",
        }
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": pub_result}),
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        stored = mock_store._records[draft_id]
        assert stored["published"] is True
        assert stored["post_id"] == "note_abc"
        assert stored["post_url"] == "https://www.xiaohongshu.com/explore/note_abc"

    def test_publish_failure_does_not_persist_post_id(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        pub_result = {"status": "failed", "error": "auth_expired"}
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": pub_result}),
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        stored = mock_store._records[draft_id]
        assert stored["published"] is False
        assert "post_id" not in stored
        assert "post_url" not in stored

    def test_publish_failure_does_not_mark_published(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        pub_result = {"status": "failed", "error": "auth_expired"}
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": pub_result}),
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        stored = mock_store._records[draft_id]
        assert stored["published"] is False

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


class TestGetDraft:
    def test_get_returns_full_record(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        r = client.get(f"/api/free/draft/{draft_id}?account_id=acct1")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["draft_id"] == draft_id
        # full record — every FreeDraft field present
        draft = data["draft"]
        assert draft["title"] == "夏日穿搭"
        assert draft["body"] == "三套夏日 OOTD"
        assert draft["hashtags"] == ["穿搭", "OOTD"]
        assert draft["image_paths"] == ["/tmp/a.png"]
        assert draft["niche"] == "fashion"

    def test_get_missing_draft_returns_400(self, client):
        r = client.get("/api/free/draft/nope?account_id=acct1")
        assert r.status_code == 400

    def test_get_no_store_returns_400(self, client):
        app.state.graph.store = None
        r = client.get("/api/free/draft/any?account_id=acct1")
        assert r.status_code == 400

    def test_get_defaults_account_id(self, client):
        # create under the default account (no account_id in body → "default")
        body = {**DRAFT_BODY}
        del body["account_id"]
        create = client.post("/api/free/draft", json=body)
        draft_id = create.json()["data"]["draft_id"]

        # GET without account_id query → defaults to "default"
        r = client.get(f"/api/free/draft/{draft_id}")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["draft_id"] == draft_id


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

    def test_list_includes_status_metadata(self, client, mock_store):
        client.post("/api/free/draft", json=DRAFT_BODY)
        r = client.get("/api/free/drafts/acct1")
        assert r.status_code == 200
        d = r.json()["data"]["drafts"][0]
        assert "created_at" in d and d["created_at"]
        assert "updated_at" in d and d["updated_at"]
        assert d["last_evaluation"] is None
        assert d["published"] is False

    def test_list_sorted_newest_first_by_updated_at(self, client, mock_store):
        # seed two drafts; second is newer (created after, so updated_at >= first)
        client.post("/api/free/draft", json={**DRAFT_BODY, "title": "old"})
        client.post("/api/free/draft", json={**DRAFT_BODY, "title": "new"})
        r = client.get("/api/free/drafts/acct1")
        drafts = r.json()["data"]["drafts"]
        # newest-first: "new" should come before "old"
        assert drafts[0]["title"] == "new"
        assert drafts[1]["title"] == "old"
        # updated_at descending
        assert drafts[0]["updated_at"] >= drafts[1]["updated_at"]

    def test_list_old_drafts_without_metadata_degrade_gracefully(self, client, mock_store):
        # seed a draft the old way (no metadata fields) directly into the store
        mock_store._records["legacy-1"] = {
            "draft_id": "legacy-1",
            "title": "legacy draft",
            "hashtags": [],
            "body": "old shape",
            # no created_at / updated_at / last_evaluation / published
        }
        r = client.get("/api/free/drafts/acct1")
        assert r.status_code == 200, r.text
        drafts = r.json()["data"]["drafts"]
        assert len(drafts) == 1
        d = drafts[0]
        assert d["draft_id"] == "legacy-1"
        assert d["title"] == "legacy draft"
        # missing fields degrade to defaults
        assert d["created_at"] is None
        assert d["updated_at"] is None
        assert d["last_evaluation"] is None
        assert d["published"] is False

    def test_list_empty_when_no_drafts(self, client):
        r = client.get("/api/free/drafts/acct1")
        assert r.status_code == 200
        assert r.json()["data"]["drafts"] == []

    def test_list_returns_count_and_not_truncated(self, client, mock_store):
        client.post("/api/free/draft", json=DRAFT_BODY)
        client.post("/api/free/draft", json={**DRAFT_BODY, "title": "第二篇"})
        r = client.get("/api/free/drafts/acct1")
        data = r.json()["data"]
        assert data["count"] == 2
        assert data["truncated"] is False

    def test_list_truncated_when_at_limit(self, client, mock_store):
        # Seed >100 drafts → asearch caps at 100 → truncated=True (heuristic:
        # returned items hit the limit, so more likely exist). count reflects
        # the returned (capped) list, not the true total.
        for i in range(101):
            mock_store._records[f"draft-{i}"] = {
                "draft_id": f"draft-{i}",
                "title": f"草稿 {i}",
                "hashtags": [],
                "body": "x",
                "updated_at": f"2026-07-11T00:00:{i:02d}",
            }
        r = client.get("/api/free/drafts/acct1")
        data = r.json()["data"]
        assert data["count"] == 100
        assert data["truncated"] is True

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

    def test_update_refreshes_updated_at(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]
        original_updated = create.json()["data"]["draft"]["updated_at"]

        r = client.patch(
            f"/api/free/draft/{draft_id}?account_id=acct1",
            json={"title": "改过的标题"},
        )
        assert r.status_code == 200
        new_updated = r.json()["data"]["draft"]["updated_at"]
        assert new_updated >= original_updated
        # created_at should NOT change on update
        created_at = create.json()["data"]["draft"]["created_at"]
        assert r.json()["data"]["draft"]["created_at"] == created_at

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


class TestGetAnalytics:
    """GET /free/analytics/{draft_id} — post-publish engagement (thread-less)."""

    def _seed_published_draft(self, client, mock_store, post_id="real_note_1"):
        """Create + 'publish' a draft via mocked run_publish, returning the draft_id."""
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]
        pub_result = {
            "post_id": post_id,
            "post_url": f"https://xhs/explore/{post_id}",
            "status": "published",
        }
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": pub_result}),
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        return draft_id

    def test_analytics_returns_engagement(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        analytics_obj = XHSAnalytics(
            post_id="real_note_1",
            views=1500,
            likes=320,
            collects=80,
            comments=45,
            shares=12,
            engagement_rate=0.0305,
            fetched_at="2026-07-10 12:00:00",
        )
        with (
            patch(
                "backend.db.accounts.get_account_cdp_endpoint",
                AsyncMock(return_value="http://localhost:9222"),
            ),
            patch("backend.services.xhs_client.XHSClient") as mock_client_cls,
            patch("backend.api.routes.free.Settings") as mock_settings,
        ):
            mock_settings.return_value.platform.headless = True
            instance = mock_client_cls.return_value
            instance.get_post_analytics = AsyncMock(return_value=analytics_obj)
            instance.close = AsyncMock()
            r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["draft_id"] == draft_id
        assert data["post_id"] == "real_note_1"
        a = data["analytics"]
        assert a["views"] == 1500
        assert a["likes"] == 320
        assert a["collects"] == 80
        assert a["comments"] == 45
        assert a["shares"] == 12
        assert a["engagement_rate"] == 0.0305
        assert a["fetched_at"] == "2026-07-10 12:00:00"
        # client was closed
        instance.close.assert_awaited_once()

    def test_analytics_requires_published_returns_400(self, client, mock_store):
        # create a draft but never publish it → no post_id
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]
        r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 400
        assert "post_id" in r.text

    def test_analytics_mock_published_returns_400(self, client, mock_store):
        # mock-published (dry-run) draft carries a "mock_*" post_id — analytics
        # must fail fast with a clear error, not return zero-engagement.
        draft_id = self._seed_published_draft(client, mock_store, post_id="mock_session_0")
        r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 400
        assert "mock" in r.text.lower()

    def test_analytics_missing_draft_returns_400(self, client):
        r = client.get("/api/free/analytics/nope?account_id=acct1")
        assert r.status_code == 400

    def test_analytics_no_store_returns_400(self, client):
        app.state.graph.store = None
        r = client.get("/api/free/analytics/any?account_id=acct1")
        assert r.status_code == 400

    def test_analytics_no_cdp_endpoint_returns_400(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        with (
            patch(
                "backend.db.accounts.get_account_cdp_endpoint",
                AsyncMock(return_value=""),
            ),
            patch("backend.api.routes.free.Settings") as mock_settings,
        ):
            # No per-account CDP override + no global cdp_endpoint on settings →
            # _resolve_cdp_endpoint falls through to the socket check, which
            # fails in the test env → "". Route must raise ValidationError 400.
            mock_settings.return_value.platform.cdp_endpoint = ""
            mock_settings.return_value.platform.headless = True
            r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 400
        assert "cdp" in r.text.lower()

    def test_analytics_fetch_failure_returns_400(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        with (
            patch(
                "backend.db.accounts.get_account_cdp_endpoint",
                AsyncMock(return_value="http://localhost:9222"),
            ),
            patch("backend.services.xhs_client.XHSClient") as mock_client_cls,
            patch("backend.api.routes.free.Settings") as mock_settings,
        ):
            mock_settings.return_value.platform.headless = True
            instance = mock_client_cls.return_value
            instance.get_post_analytics = AsyncMock(side_effect=RuntimeError("post deleted"))
            instance.close = AsyncMock()
            r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 400
        assert "analytics" in r.text.lower()
