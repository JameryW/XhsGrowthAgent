"""Unit tests for the free creation API routes (thread-less standalone)."""

from __future__ import annotations

import asyncio
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
    from backend.api.deps import get_current_user
    from backend.db.accounts import AccountRow

    graph = MagicMock()
    graph.store = mock_store
    app.state.graph = graph

    async def _user():
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user

    owned = AccountRow(
        id="acct1",
        name="acct1",
        is_active=True,
        owner_user_id="user-test",
    )

    async def _owned(user_id: str, account_id: str | None = None, **kwargs):
        # resolve_required_account_id / require_owned_account signatures vary
        if isinstance(kwargs.get("default_to_active"), bool) or account_id is not None:
            # resolve_required_account_id(user_id, account_id)
            raw = (account_id or "acct1").strip() or "acct1"
            if raw in {"default", ""}:
                return "acct1"
            return raw
        return owned

    with (
        patch(
            "backend.api.account_scope.get_account",
            new_callable=AsyncMock,
            return_value=owned,
        ),
        patch(
            "backend.api.account_scope.resolve_required_account_id",
            new_callable=AsyncMock,
            side_effect=lambda uid, aid=None, **kw: (aid or "acct1").strip() or "acct1",
        ),
        patch(
            "backend.api.account_scope.require_owned_account",
            new_callable=AsyncMock,
            return_value=owned,
        ),
        # free routes import helpers at call sites from account_scope
        patch(
            "backend.api.routes.free.resolve_required_account_id",
            new_callable=AsyncMock,
            side_effect=lambda uid, aid=None, **kw: (aid or "acct1").strip() or "acct1",
        ),
        patch(
            "backend.api.routes.free.require_owned_account",
            new_callable=AsyncMock,
            return_value=owned,
        ),
    ):
        yield TestClient(app)

    app.dependency_overrides.pop(get_current_user, None)
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
        """Missing account_id resolves to the caller's active/owned account."""
        body = {**DRAFT_BODY}
        del body["account_id"]
        r = client.post("/api/free/draft", json=body)
        assert r.status_code == 200
        assert r.json()["data"]["draft"]["account_id"] == "acct1"

    def test_create_empty_niche_auto_resolves_cold_start(self, client):
        """Empty niche → auto-infer; no notes → cold_start default 母婴 (not source=manual)."""
        body = {**DRAFT_BODY, "niche": ""}
        r = client.post("/api/free/draft", json=body)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["draft"]["niche"] == "母婴"
        res = data.get("niche_resolution") or data["draft"].get("niche_resolution")
        assert res is not None
        assert res["source"] == "cold_start"
        assert res.get("cold_start") is True

    def test_create_whitespace_niche_auto_resolves(self, client):
        """Whitespace niche treated as empty → auto-infer path."""
        body = {**DRAFT_BODY, "niche": "   "}
        r = client.post("/api/free/draft", json=body)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["draft"]["niche"] == "母婴"
        res = data["niche_resolution"]
        assert res["source"] != "manual"

    def test_create_null_niche_auto_resolves_not_422(self, client):
        """null niche must not 422; auto-infer then cold_start default."""
        body = {**DRAFT_BODY, "niche": None}
        r = client.post("/api/free/draft", json=body)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["draft"]["niche"] == "母婴"
        assert data["niche_resolution"]["source"] == "cold_start"

    def test_create_absent_niche_auto_resolves(self, client):
        """Omitted niche → auto-infer, not Field default 母婴-as-manual."""
        body = {**DRAFT_BODY}
        del body["niche"]
        r = client.post("/api/free/draft", json=body)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["draft"]["niche"] == "母婴"
        assert data["niche_resolution"]["source"] == "cold_start"

    def test_create_nonempty_niche_preserved_as_manual(self, client):
        """FreeDraft(niche="fashion") → manual override preserved."""
        body = {**DRAFT_BODY, "niche": "fashion"}
        r = client.post("/api/free/draft", json=body)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["draft"]["niche"] == "fashion"
        assert data["niche_resolution"]["source"] == "manual"

    def test_create_gathers_creative_recalls_concurrently(self, client):
        """recall_style + recall_plays + recall_materials run via asyncio.gather.

        Discriminator: among all gather calls in the call tree, exactly one has
        3 awaitables whose coroutines are CreativeMemory.recall_style /
        recall_plays / recall_materials. (Other gather calls in nested services
        e.g. niche_resolver.resolve_account_niche have a different awaitable
        count, so filtering by the creative-recall signature is robust.)
        Serial creative-recall implementation → 0 matching gathers → test fails.
        """
        captured: list[tuple] = []
        real_gather = asyncio.gather

        async def _fake_gather(*awaitables, **kwargs):
            captured.append(awaitables)
            return await real_gather(*awaitables, **kwargs)

        with patch("backend.api.routes.free.asyncio.gather", side_effect=_fake_gather):
            r = client.post("/api/free/draft", json=DRAFT_BODY)
        assert r.status_code == 200, r.text

        # Find the gather with the 3 creative-recall coroutines.
        creative_gathers = [aws for aws in captured if len(aws) == 3]
        assert len(creative_gathers) == 1, (
            f"expected 1 creative-recall gather (3 awaitables), "
            f"got {len(creative_gathers)} among {len(captured)} total gathers"
        )
        awaitables = creative_gathers[0]

        # Each awaitable is a coroutine; verify sources via __qualname__.
        qualnames = sorted(getattr(aw, "__qualname__", "") for aw in awaitables)
        assert qualnames == [
            "CreativeMemory.recall_materials",
            "CreativeMemory.recall_plays",
            "CreativeMemory.recall_style",
        ], f"coroutine sources mismatch: {qualnames}"


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
        # draft in store now has last_evaluation persisted with the triple +
        # degraded/summary (non-degraded → degraded=False, summary=None since
        # the eval_result omitted it)
        stored = mock_store._records[draft_id]
        assert stored["last_evaluation"] == {
            "overall_score": 72.0,
            "decision": "needs_revision",
            "revision_hints": ["标题需更有吸引力", "正文缺开头钩子"],
            "degraded": False,
            "summary": None,
        }
        assert "updated_at" in stored and stored["updated_at"]
        # full evaluation_result not stored on draft — only the persisted fields
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

    def test_evaluate_degraded_persists_flag_and_summary(self, client, mock_store):
        # LLM timeout fallback: evaluator returns degraded=True + summary cause.
        # evaluate_draft persists the flag + summary so /draft + /drafts + the
        # agent render can surface the degradation instead of a fake "100 approved".
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        eval_result = {
            "overall_score": 100.0,
            "decision": "approved",
            "revision_hints": [],
            "degraded": True,
            "summary": "评估器 LLM 超时，降级放行: llm slow",
        }
        with patch(
            "backend.api.routes.free._evaluator.execute",
            AsyncMock(return_value={"evaluation_result": eval_result}),
        ):
            client.post("/api/free/evaluate", json={"account_id": "acct1", "draft_id": draft_id})
        stored = mock_store._records[draft_id]
        assert stored["last_evaluation"]["degraded"] is True
        assert stored["last_evaluation"]["summary"] == "评估器 LLM 超时，降级放行: llm slow"

    def test_evaluate_non_degraded_omits_flag(self, client, mock_store):
        # A real (non-degraded) evaluation persists degraded=False (explicit),
        # so renderers can gate on the flag without distinguishing absence.
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        eval_result = {"overall_score": 88.0, "decision": "approved", "revision_hints": []}
        with patch(
            "backend.api.routes.free._evaluator.execute",
            AsyncMock(return_value={"evaluation_result": eval_result}),
        ):
            client.post("/api/free/evaluate", json={"account_id": "acct1", "draft_id": draft_id})
        stored = mock_store._records[draft_id]
        assert stored["last_evaluation"]["degraded"] is False

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

    def test_publish_failure_persists_last_publish(self, client, mock_store):
        # Failures record the attempt via last_publish (status/error/error_type/at)
        # so /draft <id> + the agent list can surface the cause after the turn.
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        pub_result = {
            "status": "failed",
            "error": "账号 acct1 已停用，无法发布",
            "error_type": "account_inactive",
        }
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": pub_result}),
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        stored = mock_store._records[draft_id]
        assert stored["last_publish"]["status"] == "failed"
        assert stored["last_publish"]["error"] == "账号 acct1 已停用，无法发布"
        assert stored["last_publish"]["error_type"] == "account_inactive"
        assert stored["last_publish"]["at"]
        # failure does NOT flip published / persist post_id
        assert stored["published"] is False
        assert "post_id" not in stored

    def test_publish_success_persists_last_publish(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        pub_result = {"post_id": "x123", "post_url": "u", "status": "published"}
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": pub_result}),
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        stored = mock_store._records[draft_id]
        assert stored["last_publish"]["status"] == "published"
        assert stored["last_publish"]["error"] is None
        assert stored["last_publish"]["at"]

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

    def test_list_includes_last_analytics_summary(self, client, mock_store):
        mock_store._records["snap-1"] = {
            "draft_id": "snap-1",
            "title": "有快照",
            "hashtags": [],
            "body": "x",
            "published": True,
            "last_analytics": {
                "post_id": "p1",
                "views": 900,
                "likes": 30,
                "collects": 10,
                "comments": 5,
                "shares": 2,
                "engagement_rate": 5.22,
                "fetched_at": "2026-07-12T00:00:00",
            },
            "updated_at": "2026-07-12T00:00:01",
        }
        r = client.get("/api/free/drafts/acct1")
        drafts = {d["draft_id"]: d for d in r.json()["data"]["drafts"]}
        assert drafts["snap-1"]["last_analytics"]["views"] == 900
        # legacy draft without snapshot degrades to None
        client.post("/api/free/draft", json=DRAFT_BODY)
        r = client.get("/api/free/drafts/acct1")
        for d in r.json()["data"]["drafts"]:
            if d["draft_id"] != "snap-1":
                assert d["last_analytics"] is None

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

    def test_list_status_filter_published(self, client, mock_store):
        # seed 3: one published, two not
        mock_store._records["pub-1"] = {
            "draft_id": "pub-1",
            "title": "已发布",
            "hashtags": [],
            "body": "x",
            "published": True,
            "updated_at": "2026-07-11T00:00:01",
        }
        mock_store._records["unpub-1"] = {
            "draft_id": "unpub-1",
            "title": "未发布",
            "hashtags": [],
            "body": "x",
            "published": False,
            "updated_at": "2026-07-11T00:00:02",
        }
        mock_store._records["unpub-2"] = {
            "draft_id": "unpub-2",
            "title": "草稿",
            "hashtags": [],
            "body": "x",
            "updated_at": "2026-07-11T00:00:03",  # published absent → False
        }
        r = client.get("/api/free/drafts/acct1?status=published")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        ids = {d["draft_id"] for d in data["drafts"]}
        assert ids == {"pub-1"}
        assert data["count"] == 1
        assert data["status"] == "published"

    def test_list_status_filter_unpublished(self, client, mock_store):
        mock_store._records["pub-1"] = {
            "draft_id": "pub-1",
            "title": "已发布",
            "hashtags": [],
            "body": "x",
            "published": True,
            "updated_at": "2026-07-11T00:00:01",
        }
        mock_store._records["unpub-1"] = {
            "draft_id": "unpub-1",
            "title": "未发布",
            "hashtags": [],
            "body": "x",
            "published": False,
            "updated_at": "2026-07-11T00:00:02",
        }
        mock_store._records["unpub-2"] = {
            "draft_id": "unpub-2",
            "title": "草稿",
            "hashtags": [],
            "body": "x",
            "updated_at": "2026-07-11T00:00:03",
        }
        r = client.get("/api/free/drafts/acct1?status=unpublished")
        data = r.json()["data"]
        ids = {d["draft_id"] for d in data["drafts"]}
        assert ids == {"unpub-1", "unpub-2"}

    def test_list_status_filter_publish_failed(self, client, mock_store):
        # publish_failed matches drafts whose last_publish.status is a non-success
        # (failed / auth_expired / ...). Published success + no-publish + mock
        # are excluded.
        mock_store._records["fail-1"] = {
            "draft_id": "fail-1",
            "title": "发布失败",
            "hashtags": [],
            "body": "x",
            "published": False,
            "last_publish": {
                "status": "failed",
                "error": "停用",
                "error_type": "account_inactive",
                "at": "2026-07-12T00:00:01",
            },
            "updated_at": "2026-07-12T00:00:01",
        }
        mock_store._records["pub-1"] = {
            "draft_id": "pub-1",
            "title": "已发布",
            "hashtags": [],
            "body": "x",
            "published": True,
            "last_publish": {"status": "published", "error": None, "at": "2026-07-12T00:00:02"},
            "updated_at": "2026-07-12T00:00:02",
        }
        mock_store._records["never-1"] = {
            "draft_id": "never-1",
            "title": "没发过",
            "hashtags": [],
            "body": "x",
            "updated_at": "2026-07-12T00:00:03",  # last_publish absent
        }
        r = client.get("/api/free/drafts/acct1?status=publish_failed")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        ids = {d["draft_id"] for d in data["drafts"]}
        assert ids == {"fail-1"}
        assert data["count"] == 1
        assert data["status"] == "publish_failed"

    def test_list_status_filter_evaluated(self, client, mock_store):
        mock_store._records["eval-1"] = {
            "draft_id": "eval-1",
            "title": "评估过",
            "hashtags": [],
            "body": "x",
            "last_evaluation": {"overall_score": 80.0, "decision": "approved"},
            "updated_at": "2026-07-11T00:00:01",
        }
        mock_store._records["uneval-1"] = {
            "draft_id": "uneval-1",
            "title": "没评估",
            "hashtags": [],
            "body": "x",
            "updated_at": "2026-07-11T00:00:02",  # last_evaluation absent → None
        }
        r = client.get("/api/free/drafts/acct1?status=evaluated")
        data = r.json()["data"]
        ids = {d["draft_id"] for d in data["drafts"]}
        assert ids == {"eval-1"}

    def test_list_status_filter_unevaluated(self, client, mock_store):
        mock_store._records["eval-1"] = {
            "draft_id": "eval-1",
            "title": "评估过",
            "hashtags": [],
            "body": "x",
            "last_evaluation": {"overall_score": 80.0, "decision": "approved"},
            "updated_at": "2026-07-11T00:00:01",
        }
        mock_store._records["uneval-1"] = {
            "draft_id": "uneval-1",
            "title": "没评估",
            "hashtags": [],
            "body": "x",
            "updated_at": "2026-07-11T00:00:02",
        }
        r = client.get("/api/free/drafts/acct1?status=unevaluated")
        data = r.json()["data"]
        ids = {d["draft_id"] for d in data["drafts"]}
        assert ids == {"uneval-1"}

    def test_list_title_search_case_insensitive(self, client, mock_store):
        mock_store._records["d1"] = {
            "draft_id": "d1",
            "title": "夏日穿搭",
            "hashtags": [],
            "body": "x",
            "updated_at": "2026-07-11T00:00:01",
        }
        mock_store._records["d2"] = {
            "draft_id": "d2",
            "title": "冬季护肤",
            "hashtags": [],
            "body": "x",
            "updated_at": "2026-07-11T00:00:02",
        }
        r = client.get("/api/free/drafts/acct1?q=夏日")
        data = r.json()["data"]
        titles = {d["title"] for d in data["drafts"]}
        assert titles == {"夏日穿搭"}
        assert data["q"] == "夏日"

    def test_list_status_and_q_combined(self, client, mock_store):
        # two published drafts, only one matches title substring
        mock_store._records["pub-1"] = {
            "draft_id": "pub-1",
            "title": "夏日穿搭",
            "hashtags": [],
            "body": "x",
            "published": True,
            "updated_at": "2026-07-11T00:00:01",
        }
        mock_store._records["pub-2"] = {
            "draft_id": "pub-2",
            "title": "冬季护肤",
            "hashtags": [],
            "body": "x",
            "published": True,
            "updated_at": "2026-07-11T00:00:02",
        }
        r = client.get("/api/free/drafts/acct1?status=published&q=夏日")
        data = r.json()["data"]
        ids = {d["draft_id"] for d in data["drafts"]}
        assert ids == {"pub-1"}

    def test_list_invalid_status_returns_400(self, client):
        r = client.get("/api/free/drafts/acct1?status=bogus")
        assert r.status_code == 400
        assert "status" in r.json()["error"]["message"]

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

    def test_update_empty_niche_re_resolves_auto(self, client, mock_store):
        """PATCH niche="" → auto-infer; no notes → cold_start 母婴 (not manual)."""
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        r = client.patch(
            f"/api/free/draft/{draft_id}?account_id=acct1",
            json={"niche": ""},
        )
        assert r.status_code == 200, r.text
        draft = r.json()["data"]["draft"]
        assert draft["niche"] == "母婴"
        assert draft.get("niche_resolution", {}).get("source") in (
            "cold_start",
            "inferred",
            "account_bound",
        )

    def test_update_null_niche_re_resolves_not_422(self, client, mock_store):
        """PATCH niche=null → auto path, not 422."""
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        r = client.patch(
            f"/api/free/draft/{draft_id}?account_id=acct1",
            json={"niche": None},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["draft"]["niche"] == "母婴"

    def test_update_niche_omitted_preserves_existing(self, client, mock_store):
        """PATCH without niche field → existing niche preserved (None = don't change)."""
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]
        original_niche = create.json()["data"]["draft"]["niche"]

        r = client.patch(
            f"/api/free/draft/{draft_id}?account_id=acct1",
            json={"title": "新标题"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["draft"]["niche"] == original_niche

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
            patch("backend.config.settings.Settings") as mock_settings,
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
            patch("backend.config.settings.Settings") as mock_settings,
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
            patch("backend.config.settings.Settings") as mock_settings,
        ):
            mock_settings.return_value.platform.headless = True
            instance = mock_client_cls.return_value
            instance.get_post_analytics = AsyncMock(side_effect=RuntimeError("post deleted"))
            instance.close = AsyncMock()
            r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 400
        assert "analytics" in r.text.lower()


class TestAnalyticsFeedbackLoop:
    """Post-publish feedback loop: /analytics persists a snapshot onto the
    draft, backfills ContentHistory with raw counts (fraction rate), and
    writes one deterministic insight — task 08-24-free-post-feedback-loop."""

    def _seed_published_draft(self, client, mock_store, post_id="real_note_1"):
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

    def _fetch(self, client, draft_id, views=1500, likes=320, collects=80, comments=45, shares=12):
        analytics_obj = XHSAnalytics(
            post_id="real_note_1",
            views=views,
            likes=likes,
            collects=collects,
            comments=comments,
            shares=shares,
            engagement_rate=3.05,
            fetched_at="2026-07-10 12:00:00",
        )
        with (
            patch(
                "backend.db.accounts.get_account_cdp_endpoint",
                AsyncMock(return_value="http://localhost:9222"),
            ),
            patch("backend.services.xhs_client.XHSClient") as mock_client_cls,
            patch("backend.config.settings.Settings") as mock_settings,
        ):
            mock_settings.return_value.platform.headless = True
            instance = mock_client_cls.return_value
            instance.get_post_analytics = AsyncMock(return_value=analytics_obj)
            instance.close = AsyncMock()
            r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 200, r.text
        return r

    def test_analytics_persists_last_analytics_snapshot(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        self._fetch(client, draft_id)
        stored = mock_store._records[draft_id]
        snap = stored["last_analytics"]
        assert snap["post_id"] == "real_note_1"
        assert snap["views"] == 1500
        assert snap["likes"] == 320
        assert snap["collects"] == 80
        assert snap["comments"] == 45
        assert snap["shares"] == 12
        # display-scale value preserved as returned (NOT recomputed here)
        assert snap["engagement_rate"] == 3.05
        assert snap["fetched_at"]  # ISO timestamp set server-side
        # snapshot write refreshes updated_at
        assert stored["updated_at"] >= snap["fetched_at"]

    def test_analytics_second_call_overwrites_snapshot(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        self._fetch(client, draft_id)
        self._fetch(client, draft_id, views=3000, likes=100)
        stored = mock_store._records[draft_id]
        assert stored["last_analytics"]["views"] == 3000
        assert stored["last_analytics"]["likes"] == 100

    def test_analytics_unpublished_does_not_write_snapshot(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]
        r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 400
        assert "last_analytics" not in mock_store._records[draft_id]

    def test_analytics_mock_post_id_does_not_write_snapshot(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store, post_id="mock_s0")
        r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 400
        assert "last_analytics" not in mock_store._records[draft_id]

    def test_analytics_backfills_content_history_with_fraction_rate(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        # seed the ContentHistory record run_publish would have written
        mock_store._records["real_note_1"] = {
            "title": "夏日穿搭",
            "topic": "OOTD",
            "hashtags": ["穿搭"],
            "status": "published",
        }
        self._fetch(client, draft_id)
        record = mock_store._records["real_note_1"]
        assert record["views"] == 1500
        assert record["likes"] == 320
        assert record["collects"] == 80
        assert record["comments"] == 45
        assert record["shares"] == 12
        # FRACTION from counts: (320+80+45+12)/1500 = 0.3047 — not the 3.05 display value
        assert record["engagement_rate"] == round((320 + 80 + 45 + 12) / 1500, 4)

    def test_analytics_backfill_skips_when_no_history_record(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        aputs_before = mock_store.aput.await_count
        self._fetch(client, draft_id)  # must not raise despite missing CH record
        new_aputs = mock_store.aput.await_args_list[aputs_before:]
        # only the draft-snapshot + (maybe) insight writes — no content_history write
        ch_ns = ("accounts", "acct1", "content_history")
        assert all(call.args[0] != ch_ns for call in new_aputs)

    def test_analytics_writes_insight_above_threshold(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        aputs_before = mock_store.aput.await_count
        self._fetch(client, draft_id)  # rate 30.47% ≥ 3%
        new_aputs = mock_store.aput.await_args_list[aputs_before:]
        insights_ns = ("accounts", "acct1", "performance_insights")
        insight_calls = [call for call in new_aputs if call.args[0] == insights_ns]
        assert len(insight_calls) == 1
        value = insight_calls[0].kwargs["value"]
        assert value["source"] == "free_analytics"
        assert value["post_id"] == "real_note_1"
        assert value["draft_id"] == draft_id
        assert "夏日穿搭" in value["insight"]
        assert "30.5%" in value["insight"]
        assert "值得复用" in value["insight"]

    def test_analytics_writes_below_threshold_insight(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        # total=13/1500 ≈ 0.87% < 3%
        self._fetch(client, draft_id, views=1500, likes=5, collects=4, comments=3, shares=1)
        insights_ns = ("accounts", "acct1", "performance_insights")
        insight_calls = [
            call for call in mock_store.aput.await_args_list if call.args[0] == insights_ns
        ]
        assert len(insight_calls) == 1
        assert "低于 3% 基准" in insight_calls[0].kwargs["value"]["insight"]

    def test_analytics_no_insight_when_zero_views(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        aputs_before = mock_store.aput.await_count
        self._fetch(client, draft_id, views=0, likes=0, collects=0, comments=0, shares=0)
        new_aputs = mock_store.aput.await_args_list[aputs_before:]
        insights_ns = ("accounts", "acct1", "performance_insights")
        assert all(call.args[0] != insights_ns for call in new_aputs)
        # snapshot still persisted (a zero-engagement observation is valid)
        assert mock_store._records[draft_id]["last_analytics"]["views"] == 0


class TestEvaluatorSampleChain:
    """Free-mode RQGM evaluations feed the evaluator training pool under the
    synthetic thread key `free:{draft_id}`; /analytics backfills the weak
    engagement label onto that sample (task 08-25-free-evaluator-samples)."""

    def _eval_result(self, **overrides):
        result = {
            "overall_score": 88.0,
            "decision": "approved",
            "revision_hints": [],
            "dimensions": [{"dimension": "copywriting", "score": 90.0}],
        }
        result.update(overrides)
        return result

    def _evaluate(self, client, draft_id, eval_result):
        with (
            patch(
                "backend.api.routes.free._evaluator.execute",
                AsyncMock(return_value={"evaluation_result": eval_result}),
            ),
            patch(
                "backend.db.evaluator_config.insert_sample",
                new_callable=AsyncMock,
            ) as mock_insert,
            patch(
                "backend.db.pool.is_pool_ready",
                return_value=True,
            ),
        ):
            r = client.post(
                "/api/free/evaluate", json={"account_id": "acct1", "draft_id": draft_id}
            )
        assert r.status_code == 200, r.text
        return mock_insert

    def test_evaluate_inserts_sample_under_synthetic_thread_key(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        mock_insert = self._evaluate(client, draft_id, self._eval_result())
        mock_insert.assert_awaited_once()
        sample = mock_insert.await_args.args[0]
        assert sample.thread_id == f"free:{draft_id}"
        assert sample.account_id == "acct1"
        assert sample.label_source == "evaluator"
        assert sample.overall_score == 88.0
        assert sample.decision == "approved"
        assert sample.dimensions == [{"dimension": "copywriting", "score": 90.0}]
        # free-shaped content snapshot carries the evaluation context
        assert sample.content_snapshot["title"] == "夏日穿搭"
        assert sample.content_snapshot["body"] == "三套夏日 OOTD"
        assert sample.content_snapshot["hashtags"] == ["穿搭", "OOTD"]
        assert sample.content_snapshot["niche"] == "fashion"

    def test_evaluate_degraded_never_enters_sample_pool(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        # degraded flag (LLM timeout fake-approved) — must NOT be recorded
        mock_insert = self._evaluate(
            client, draft_id, self._eval_result(degraded=True, summary="timeout")
        )
        mock_insert.assert_not_awaited()

    def test_evaluate_non_consumable_status_skips_sample(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        mock_insert = self._evaluate(client, draft_id, self._eval_result(status="unavailable"))
        mock_insert.assert_not_awaited()

    def test_evaluate_scoreless_skips_sample(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        mock_insert = self._evaluate(client, draft_id, self._eval_result(overall_score=None))
        mock_insert.assert_not_awaited()

    def test_evaluate_without_db_pool_skips_sample_silently(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]

        with (
            patch(
                "backend.api.routes.free._evaluator.execute",
                AsyncMock(return_value={"evaluation_result": self._eval_result()}),
            ),
            patch(
                "backend.db.evaluator_config.insert_sample",
                new_callable=AsyncMock,
            ) as mock_insert,
            patch(
                "backend.db.pool.is_pool_ready",
                return_value=False,
            ),
        ):
            r = client.post(
                "/api/free/evaluate", json={"account_id": "acct1", "draft_id": draft_id}
            )
        assert r.status_code == 200
        mock_insert.assert_not_awaited()

    def _seed_published_draft(self, client, mock_store, post_id="real_note_1"):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]
        pub_result = {"post_id": post_id, "status": "published"}
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": pub_result}),
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        return draft_id

    def _fetch_analytics(self, client, draft_id):
        analytics_obj = XHSAnalytics(
            post_id="real_note_1",
            views=1500,
            likes=320,
            collects=80,
            comments=45,
            shares=12,
            engagement_rate=30.47,
            fetched_at="2026-08-25 09:00:00",
        )
        with (
            patch(
                "backend.db.accounts.get_account_cdp_endpoint",
                AsyncMock(return_value="http://localhost:9222"),
            ),
            patch("backend.services.xhs_client.XHSClient") as mock_client_cls,
            patch("backend.config.settings.Settings") as mock_settings,
        ):
            mock_settings.return_value.platform.headless = True
            instance = mock_client_cls.return_value
            instance.get_post_analytics = AsyncMock(return_value=analytics_obj)
            instance.close = AsyncMock()
            r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 200, r.text
        return r

    def test_analytics_backfills_engagement_onto_free_thread(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        with (
            patch(
                "backend.db.evaluator_config.backfill_engagement",
                new_callable=AsyncMock,
            ) as mock_backfill,
            patch("backend.db.pool.is_pool_ready", return_value=True),
        ):
            r = self._fetch_analytics(client, draft_id)
        assert r.status_code == 200
        mock_backfill.assert_awaited_once()
        args = mock_backfill.await_args.args
        assert args[0] == f"free:{draft_id}"
        # raw counts only — the fraction is computed inside backfill_engagement
        assert args[1] == {
            "views": 1500,
            "likes": 320,
            "collects": 80,
            "comments": 45,
            "shares": 12,
        }

    def test_analytics_backfill_skipped_without_db_pool(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        with (
            patch(
                "backend.db.evaluator_config.backfill_engagement",
                new_callable=AsyncMock,
            ) as mock_backfill,
            patch("backend.db.pool.is_pool_ready", return_value=False),
        ):
            self._fetch_analytics(client, draft_id)
        mock_backfill.assert_not_awaited()

    def test_analytics_backfill_failure_does_not_break_response(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        with (
            patch(
                "backend.db.evaluator_config.backfill_engagement",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db down"),
            ),
            patch("backend.db.pool.is_pool_ready", return_value=True),
        ):
            r = self._fetch_analytics(client, draft_id)
        assert r.status_code == 200
        assert r.json()["data"]["analytics"]["views"] == 1500

    def test_analytics_schedules_evolve_after_backfill(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        with (
            patch("backend.api.routes.free._schedule_free_evolve") as mock_sched,
            patch(
                "backend.db.evaluator_config.backfill_engagement",
                new_callable=AsyncMock,
            ),
            patch("backend.db.pool.is_pool_ready", return_value=True),
        ):
            self._fetch_analytics(client, draft_id)
        mock_sched.assert_called_once_with("acct1")

    def test_analytics_skips_evolve_without_db_pool(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        with (
            patch("backend.api.routes.free._schedule_free_evolve") as mock_sched,
            patch("backend.db.pool.is_pool_ready", return_value=False),
        ):
            self._fetch_analytics(client, draft_id)
        mock_sched.assert_not_called()

    def test_analytics_skips_evolve_when_backfill_fails(self, client, mock_store):
        draft_id = self._seed_published_draft(client, mock_store)
        with (
            patch("backend.api.routes.free._schedule_free_evolve") as mock_sched,
            patch(
                "backend.db.evaluator_config.backfill_engagement",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db down"),
            ),
            patch("backend.db.pool.is_pool_ready", return_value=True),
        ):
            self._fetch_analytics(client, draft_id)
        mock_sched.assert_not_called()


class TestStyleAnchors:
    """Creative-memory anchoring (task 08-25-free-style-anchors): drafts may
    carry style_id/play_id; publish threads them into the ContentHistory
    chain via the synthesized state, and analytics triggers calibration."""

    def test_create_persists_style_and_play_anchors(self, client, mock_store):
        body = {**DRAFT_BODY, "style_id": "style_治愈", "play_id": "p_9"}
        r = client.post("/api/free/draft", json=body)
        assert r.status_code == 200, r.text
        draft_id = r.json()["data"]["draft_id"]
        assert mock_store._records[draft_id]["style_id"] == "style_治愈"
        assert mock_store._records[draft_id]["play_id"] == "p_9"

    def test_create_defaults_to_empty_anchors(self, client, mock_store):
        r = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = r.json()["data"]["draft_id"]
        assert mock_store._records[draft_id]["style_id"] == ""
        assert mock_store._records[draft_id]["play_id"] == ""

    def test_patch_updates_anchors(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]
        r = client.patch(
            f"/api/free/draft/{draft_id}?account_id=acct1",
            json={"style_id": "s_late", "play_id": "p_late"},
        )
        assert r.status_code == 200, r.text
        assert mock_store._records[draft_id]["style_id"] == "s_late"
        assert mock_store._records[draft_id]["play_id"] == "p_late"

    def test_publish_threads_anchors_into_run_publish_state(self, client, mock_store):
        body = {**DRAFT_BODY, "style_id": "style_治愈", "play_id": "p_9"}
        create = client.post("/api/free/draft", json=body)
        draft_id = create.json()["data"]["draft_id"]
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": {"post_id": "n1", "status": "published"}}),
        ) as mock_pub:
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        state = mock_pub.await_args.args[0]
        assert state["visual_plan"]["style_id"] == "style_治愈"
        assert state["content_plan"]["play_id"] == "p_9"

    def _anchored_draft(self, client, mock_store) -> str:
        body = {**DRAFT_BODY, "style_id": "style_治愈", "play_id": "p_9"}
        create = client.post("/api/free/draft", json=body)
        return create.json()["data"]["draft_id"]

    def _fetch_analytics(self, client, draft_id, **metric_overrides):
        metrics = {"views": 1500, "likes": 320, "collects": 80, "comments": 45, "shares": 12}
        metrics.update(metric_overrides)
        with (
            patch(
                "backend.api.routes.free.run_publish",
                AsyncMock(
                    return_value={
                        "publish_result": {"post_id": "real_note_1", "status": "published"}
                    }
                ),
            ),
            patch(
                "backend.db.accounts.get_account_cdp_endpoint",
                AsyncMock(return_value="http://localhost:9222"),
            ),
            patch("backend.services.xhs_client.XHSClient") as mock_client_cls,
            patch("backend.config.settings.Settings") as mock_settings,
            patch(
                "backend.memory.calibrator.schedule_calibration",
                new_callable=AsyncMock,
            ) as mock_sched,
        ):
            mock_settings.return_value.platform.headless = True
            instance = mock_client_cls.return_value
            instance.get_post_analytics = AsyncMock(
                return_value=XHSAnalytics(post_id="real_note_1", engagement_rate=30.47, **metrics)
            )
            instance.close = AsyncMock()
            r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 200, r.text
        return mock_sched

    def _publish(self, client, draft_id):
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(
                return_value={"publish_result": {"post_id": "real_note_1", "status": "published"}}
            ),
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})

    def test_analytics_triggers_calibration_when_anchored(self, client, mock_store):
        draft_id = self._anchored_draft(client, mock_store)
        self._publish(client, draft_id)
        mock_sched = self._fetch_analytics(client, draft_id)
        mock_sched.assert_awaited_once()
        payload = mock_sched.await_args.args[1]
        assert payload["account_id"] == "acct1"
        assert payload["style_id"] == "style_治愈"
        assert payload["play_id"] == "p_9"
        assert payload["post_id"] == "real_note_1"
        # fraction from counts: 457/1500 = 0.3047 → play_success inside builder
        assert payload["actual_engagement_rate"] == round(457 / 1500, 4)
        assert payload["actual_save_rate"] == round(80 / 1500, 4)
        assert payload["play_success"] is True

    def test_analytics_skips_calibration_without_anchors(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]
        self._publish(client, draft_id)
        mock_sched = self._fetch_analytics(client, draft_id)
        mock_sched.assert_not_awaited()

    def test_analytics_skips_calibration_on_zero_views(self, client, mock_store):
        draft_id = self._anchored_draft(client, mock_store)
        self._publish(client, draft_id)
        mock_sched = self._fetch_analytics(
            client, draft_id, views=0, likes=0, collects=0, comments=0, shares=0
        )
        mock_sched.assert_not_awaited()


class TestSnapshotTrend:
    """Trend series persistence + list trend computation
    (task 08-26-free-snapshot-trend): repeated /analytics fetches keep the
    last 10 captures; list summaries expose a server-computed views delta."""

    def _published(self, client) -> str:
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(
                return_value={"publish_result": {"post_id": "note_t1", "status": "published"}}
            ),
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        return draft_id

    def _fetch(self, client, draft_id: str, views: int) -> None:
        with (
            patch(
                "backend.db.accounts.get_account_cdp_endpoint",
                AsyncMock(return_value="http://localhost:9222"),
            ),
            patch("backend.services.xhs_client.XHSClient") as mock_client_cls,
            patch("backend.config.settings.Settings") as mock_settings,
        ):
            mock_settings.return_value.platform.headless = True
            instance = mock_client_cls.return_value
            instance.get_post_analytics = AsyncMock(
                return_value=XHSAnalytics(
                    post_id="note_t1",
                    engagement_rate=12.0,
                    views=views,
                    likes=max(views // 5, 0),
                    collects=max(views // 20, 0),
                    comments=max(views // 30, 0),
                    shares=0,
                )
            )
            instance.close = AsyncMock()
            r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 200, r.text

    def test_series_appends_and_last_stays_latest(self, client, mock_store):
        draft_id = self._published(client)
        self._fetch(client, draft_id, views=100)
        self._fetch(client, draft_id, views=300)
        record = mock_store._records[draft_id]
        snaps = record["analytics_snapshots"]
        assert [s["views"] for s in snaps] == [100, 300]
        assert snaps[-1]["views"] == record["last_analytics"]["views"]

    def test_series_capped_at_ten(self, client, mock_store):
        draft_id = self._published(client)
        for v in range(1, 12):  # 11 captures → cap keeps the newest 10
            self._fetch(client, draft_id, views=v * 10)
        snaps = mock_store._records[draft_id]["analytics_snapshots"]
        assert len(snaps) == 10
        assert snaps[0]["views"] == 20  # oldest capture (views=10) fell off
        assert snaps[-1]["views"] == 110

    def test_list_engagement_trend_computed_after_two_captures(self, client, mock_store):
        draft_id = self._published(client)
        self._fetch(client, draft_id, views=100)
        r = client.get("/api/free/drafts/acct1")
        assert r.json()["data"]["drafts"][0]["engagement_trend"] is None
        self._fetch(client, draft_id, views=350)
        r = client.get("/api/free/drafts/acct1")
        trend = r.json()["data"]["drafts"][0]["engagement_trend"]
        assert trend["views"] == 350
        assert trend["delta_views"] == 250

    def test_list_engagement_trend_none_without_snapshots(self, client, mock_store):
        self._published(client)
        r = client.get("/api/free/drafts/acct1")
        assert r.json()["data"]["drafts"][0]["engagement_trend"] is None


class TestMaterialAnchors:
    """Material-vault anchoring (task 08-26-free-material-anchors): drafts may
    reference vault entries; publish threads them into copy_content.used_material_ids
    so the calibration payload can carry synthesized effectiveness."""

    def test_create_persists_material_ids(self, client, mock_store):
        body = {**DRAFT_BODY, "material_ids": ["m1", "m2"]}
        r = client.post("/api/free/draft", json=body)
        draft_id = r.json()["data"]["draft_id"]
        assert mock_store._records[draft_id]["material_ids"] == ["m1", "m2"]

    def test_create_defaults_to_empty_material_ids(self, client, mock_store):
        r = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = r.json()["data"]["draft_id"]
        assert mock_store._records[draft_id]["material_ids"] == []

    def test_patch_updates_material_ids(self, client, mock_store):
        create = client.post("/api/free/draft", json=DRAFT_BODY)
        draft_id = create.json()["data"]["draft_id"]
        r = client.patch(
            f"/api/free/draft/{draft_id}?account_id=acct1",
            json={"material_ids": ["m_late"]},
        )
        assert r.status_code == 200, r.text
        assert mock_store._records[draft_id]["material_ids"] == ["m_late"]

    def test_publish_threads_used_material_ids_into_copy_content(self, client, mock_store):
        body = {**DRAFT_BODY, "material_ids": ["m1"]}
        create = client.post("/api/free/draft", json=body)
        draft_id = create.json()["data"]["draft_id"]
        with patch(
            "backend.api.routes.free.run_publish",
            AsyncMock(return_value={"publish_result": {"post_id": "n1", "status": "published"}}),
        ) as mock_pub:
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
        state = mock_pub.await_args.args[0]
        assert state["copy_content"]["used_material_ids"] == ["m1"]

    def test_analytics_calibration_payload_carries_material_effectiveness(self, client, mock_store):
        body = {
            **DRAFT_BODY,
            "style_id": "s1",
            "play_id": "p_9",
            "material_ids": ["m1", "m2"],
        }
        create = client.post("/api/free/draft", json=body)
        draft_id = create.json()["data"]["draft_id"]
        with (
            patch(
                "backend.api.routes.free.run_publish",
                AsyncMock(
                    return_value={
                        "publish_result": {"post_id": "real_note_2", "status": "published"}
                    }
                ),
            ),
            patch(
                "backend.db.accounts.get_account_cdp_endpoint",
                AsyncMock(return_value="http://localhost:9222"),
            ),
            patch("backend.services.xhs_client.XHSClient") as mock_client_cls,
            patch("backend.config.settings.Settings") as mock_settings,
            patch(
                "backend.memory.calibrator.schedule_calibration", new_callable=AsyncMock
            ) as mock_sched,
        ):
            client.post("/api/free/publish", json={"account_id": "acct1", "draft_id": draft_id})
            mock_settings.return_value.platform.headless = True
            instance = mock_client_cls.return_value
            instance.get_post_analytics = AsyncMock(
                return_value=XHSAnalytics(
                    post_id="real_note_2",
                    engagement_rate=30.0,
                    views=1500,
                    likes=320,
                    collects=80,
                    comments=45,
                    shares=12,
                )
            )
            instance.close = AsyncMock()
            r = client.get(f"/api/free/analytics/{draft_id}?account_id=acct1")
        assert r.status_code == 200, r.text
        mock_sched.assert_awaited_once()
        payload = mock_sched.await_args.args[1]
        assert payload["material_ids"] == ["m1", "m2"]
        # 457/1500 ≈ 30% ≥ 3% → reinforcing score for both entries
        assert payload["material_effectiveness"] == {"m1": 0.9, "m2": 0.9}

    def test_list_summary_carries_anchors(self, client, mock_store):
        anchored = client.post(
            "/api/free/draft",
            json={**DRAFT_BODY, "style_id": "s1", "play_id": "p_9", "material_ids": ["m1"]},
        ).json()["data"]["draft_id"]
        plain = client.post("/api/free/draft", json=DRAFT_BODY).json()["data"]["draft_id"]
        r = client.get("/api/free/drafts/acct1")
        by_id = {d["draft_id"]: d for d in r.json()["data"]["drafts"]}
        assert by_id[anchored]["style_id"] == "s1"
        assert by_id[anchored]["play_id"] == "p_9"
        assert by_id[anchored]["material_ids"] == ["m1"]
        # unanchored drafts surface empty defaults, never missing keys
        assert by_id[plain]["style_id"] == ""
        assert by_id[plain]["play_id"] == ""
        assert by_id[plain]["material_ids"] == []


class TestGetSuggestions:
    """GET /free/suggestions/{account_id} — thread-less creative suggestions.

    Atomic data fetch only (delegates to get_suggestions_for_mode); the route
    carries no orchestration — the omp agent decides what to do with the advice.
    """

    def test_suggestions_returns_list(self, client, mock_store):
        from backend.services.creator_stats.types import CreativeSuggestion

        suggestions = [
            CreativeSuggestion(
                mode="free",
                category="topic",
                title="高互动选题",
                advice="辅食记录互动率高于均值 1.4 倍",
                priority=2,
                evidence="note_analytics",
            ),
            CreativeSuggestion(
                mode="free",
                category="style",
                title="暖色调封面",
                advice="前 3 篇高收藏为暖光近景",
                priority=1,
            ),
        ]
        with patch(
            "backend.services.creator_stats.suggestions.get_suggestions_for_mode",
            AsyncMock(return_value=suggestions),
        ):
            r = client.get("/api/free/suggestions/acct1")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["account_id"] == "acct1"
        assert data["mode"] == "free"
        assert data["count"] == 2
        assert data["cold_start"] is False
        assert len(data["suggestions"]) == 2
        assert data["suggestions"][0]["category"] == "topic"
        assert data["suggestions"][0]["evidence"] == "note_analytics"
        assert data["suggestions"][1]["evidence"] == ""

    def test_suggestions_cold_start_flag(self, client, mock_store):
        from backend.services.creator_stats.types import CreativeSuggestion

        suggestions = [
            CreativeSuggestion(
                mode="free",
                category="cold_start",
                title="暂无创作中心数据",
                advice="尚未导入统计数据。",
                priority=0,
                evidence="no_imported_stats",
            )
        ]
        with patch(
            "backend.services.creator_stats.suggestions.get_suggestions_for_mode",
            AsyncMock(return_value=suggestions),
        ):
            r = client.get("/api/free/suggestions/acct1")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        # cold_start is True only when ALL suggestions are cold_start category
        assert data["cold_start"] is True

    def test_suggestions_defaults_account_id(self, client, mock_store):
        """Empty/whitespace path account_id falls back to owned active account."""
        with patch(
            "backend.services.creator_stats.suggestions.get_suggestions_for_mode",
            AsyncMock(return_value=[]),
        ) as mock_fn:
            r = client.get("/api/free/suggestions/%20")  # whitespace → owned active
        assert r.status_code == 200, r.text
        assert r.json()["data"]["account_id"] == "acct1"
        assert mock_fn.await_args.args[0] == "acct1"

    def test_suggestions_empty_returns_count_zero(self, client, mock_store):
        with patch(
            "backend.services.creator_stats.suggestions.get_suggestions_for_mode",
            AsyncMock(return_value=[]),
        ):
            r = client.get("/api/free/suggestions/acct1")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["count"] == 0
        # cold_start=False when there are no suggestions (all() over empty = False)
        assert data["cold_start"] is False
