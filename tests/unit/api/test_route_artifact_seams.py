"""Route-level artifact-seam regressions (P1a-S4-0).

Before this slice, several route writes bypassed refify_updates: on a ref'd
thread the bare inline write would be silently shadowed by the stale ref body
on the next resolve (user copy edits / uploaded image paths / saved versions
silently lost). These tests pin the seam contract:

- writes of refable fields on ref'd threads land in the Artifact Store and the
  aupdate_state payload carries the ref, not the inline body;
- reads (echo, evaluator input) resolve through the store and see the new body;
- with no store available the write degrades to inline + tombstone (best-effort
  contract: never point at a body that does not exist);
- _emit_status_transition gate payloads embed resolved bodies, not ref'd views.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes import _runner
from backend.api.routes.optimization import router as optimization_router
from backend.api.routes.review import router as review_router
from backend.api.routes.workflow import router as workflow_router
from backend.db.accounts import AccountRow
from backend.db.workflows import WorkflowRow
from backend.realtime.events import EventType
from backend.state.artifacts import make_ref, put_artifact

_EVAL_PATH = "backend.api.routes.review._evaluator"


def _snapshot(values: dict, *, next_nodes=()) -> MagicMock:
    snap = MagicMock()
    snap.values = values
    snap.next = tuple(next_nodes)
    snap.tasks = ()
    snap.interrupts = ()
    return snap


def _make_graph(
    values: dict,
    *,
    next_nodes=(),
    store: Any,
    snapshots: list[MagicMock] | None = None,
) -> MagicMock:
    """Fake compiled graph; ``snapshots`` turns aget_state into a side_effect queue."""
    graph = MagicMock()
    graph.store = store
    snaps = snapshots or [_snapshot(values, next_nodes=next_nodes)]
    graph.aget_state = AsyncMock(side_effect=snaps)
    graph.ainvoke = AsyncMock(return_value={"phase": "reviewing"})
    graph.aupdate_state = AsyncMock()
    return graph


def _seed_body(store: InMemoryStore, thread_id: str, state_key: str, body: Any) -> dict:
    """Store ``body`` under the seam namespace and return its ref for the state."""
    ref = asyncio.run(put_artifact(store, thread_id, state_key, body))
    assert ref is not None
    return dict(ref)


_OWNED = AccountRow(id="acc1", name="acc1", is_active=True, owner_user_id="user-test")


def _build_client(app: FastAPI, graph: MagicMock) -> TestClient:
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user():
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    patcher = patch.multiple(
        "backend.db.workflows",
        get_workflow=AsyncMock(return_value=WorkflowRow(thread_id="t1", account_id="acc1")),
    )
    scope_patcher = patch("backend.api.account_scope.get_account", AsyncMock(return_value=_OWNED))
    patcher.start()
    scope_patcher.start()
    return TestClient(app)


# ── update-copy on a ref'd thread ────────────────────────────────────────────


def test_update_copy_refd_thread_merges_into_stored_body():
    """THE data-loss regression: the merge base must be the stored body.

    A bare inline write would carry only {selected_title} merged into {} and be
    shadowed by the stale ref on the next resolve — the user's edit (and every
    field not in the request) would silently disappear.
    """
    store = InMemoryStore()
    ref = _seed_body(
        store,
        "t1",
        "copy_content",
        {"selected_title": "原标题", "body_text": "原正文", "tone": "治愈"},
    )
    values = {
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "reviewing",
        "artifacts": {"copy_content": ref},
        # copy_content intentionally ABSENT — it lives in the store
    }
    graph = _make_graph(values, next_nodes=("review_gate",), store=store)

    app = FastAPI()
    app.include_router(review_router, prefix="/api/review")
    client = _build_client(app, graph)

    with patch(_EVAL_PATH, new_callable=AsyncMock) as mock_eval:
        mock_eval.return_value = {"evaluation_result": {"overall_score": 90.0}}
        resp = client.post("/api/review/update-copy/t1", json={"title": "新标题"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "updated"

    # Write seam: payload carries the ref, not the inline body
    written = graph.aupdate_state.await_args_list[0].args[1]
    assert "copy_content" not in written
    assert written["artifacts"]["copy_content"]["ref"] == "artifact://copy_content/latest"

    # Stored body: new title merged INTO the previous stored body
    item = asyncio.run(store.aget(("artifacts", "t1", "copy_content"), "latest"))
    assert item is not None
    assert item.value["body"] == {
        "selected_title": "新标题",
        "body_text": "原正文",
        "tone": "治愈",
    }

    # Evaluator saw the resolved merge (bodies, not refs)
    eval_state = mock_eval.call_args.args[0]
    assert eval_state["copy_content"]["selected_title"] == "新标题"
    assert eval_state["copy_content"]["body_text"] == "原正文"


def test_update_copy_without_store_degrades_to_inline_tombstone():
    """Best-effort contract: no store → inline write kept + stale ref tombstoned."""
    graph = _make_graph(
        {
            "session_id": "s1",
            "account_id": "acc1",
            "phase": "reviewing",
            "copy_content": {"selected_title": "原标题", "tone": "治愈"},
        },
        next_nodes=("review_gate",),
        store=None,
    )

    app = FastAPI()
    app.include_router(review_router, prefix="/api/review")
    client = _build_client(app, graph)

    with patch(_EVAL_PATH, new_callable=AsyncMock) as mock_eval:
        mock_eval.return_value = {"evaluation_result": {"overall_score": 90.0}}
        resp = client.post("/api/review/update-copy/t1", json={"title": "新标题"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "updated"

    written = graph.aupdate_state.await_args_list[0].args[1]
    # Inline value wins, ref is tombstoned so resolve_state lets it through.
    assert written["copy_content"]["selected_title"] == "新标题"
    assert written["artifacts"] == {"copy_content": None}


# ── submit_draft on a ref'd thread ───────────────────────────────────────────


def test_submit_draft_refd_thread_writes_through_seam_and_echoes_store():
    store = InMemoryStore()
    ref = _seed_body(
        store, "t1", "draft_content", {"title": "旧稿", "text": "旧文", "source": "ai"}
    )
    values = {
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "awaiting_draft",
        "artifacts": {"draft_content": ref},
    }
    # aget_state is called twice: once before the write, once for the echo.
    graph = _make_graph(
        values,
        next_nodes=(),
        store=store,
        snapshots=[_snapshot(values), _snapshot(values)],
    )

    app = FastAPI()
    app.include_router(optimization_router, prefix="/api/optimization")
    client = _build_client(app, graph)

    resp = client.post(
        "/api/optimization/draft/t1",
        json={"title": "新稿", "text": "新文", "hashtags": ["tag"], "viral_links": ["l1"]},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "draft_submitted"

    # Echo reads through the store: the fresh body, not the stale ref'd view.
    echoed = data["draft_content"]
    assert echoed["title"] == "新稿"
    assert echoed["text"] == "新文"
    assert echoed["source"] == "user_submitted"

    # Write seam: both refable fields popped from the inline update
    written = graph.aupdate_state.await_args.args[1]
    assert "draft_content" not in written
    assert "user_viral_links" not in written
    assert written["artifacts"]["draft_content"]["ref"] == "artifact://draft_content/latest"
    assert written["artifacts"]["user_viral_links"]["ref"] == "artifact://user_viral_links/latest"

    # Stored bodies
    draft_item = asyncio.run(store.aget(("artifacts", "t1", "draft_content"), "latest"))
    assert draft_item is not None
    assert draft_item.value["body"]["title"] == "新稿"
    links_item = asyncio.run(store.aget(("artifacts", "t1", "user_viral_links"), "latest"))
    assert links_item is not None
    assert links_item.value["body"] == ["l1"]


# ── submit_review (needs_revision) version save on a ref'd thread ────────────


def test_submit_review_needs_revision_saves_version_through_seam():
    store = InMemoryStore()
    copy_ref = _seed_body(
        store, "t1", "copy_content", {"selected_title": "原标题", "body_text": "正文"}
    )
    visual_ref = _seed_body(
        store, "t1", "visual_plan", {"image_prompts": ["p1"], "layout_style": "极简"}
    )
    values = {
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "reviewing",
        "artifacts": {"copy_content": copy_ref, "visual_plan": visual_ref},
    }
    graph = _make_graph(values, next_nodes=("review_gate",), store=store)
    # submit_review + _run_graph_and_persist hit aget_state several times —
    # a one-shot side_effect queue would exhaust; return the same snapshot.
    graph.aget_state = AsyncMock(return_value=_snapshot(values, next_nodes=("review_gate",)))

    app = FastAPI()
    app.include_router(review_router, prefix="/api/review")
    client = _build_client(app, graph)

    resp = client.post(
        "/api/review/submit/t1",
        json={"decision": "needs_revision", "comments": "再改改"},
    )

    assert resp.status_code == 200, resp.text

    # Version save went through the write seam
    written = graph.aupdate_state.await_args_list[0].args[1]
    assert "content_versions" not in written
    assert written["artifacts"]["content_versions"]["ref"] == "artifact://content_versions/latest"
    # Meta summary kept in RuntimeState for routing predicates
    assert len(written["versions_meta"]) == 1
    assert written["versions_meta"][0]["title"] == "原标题"
    assert written["versions_meta"][0]["style_suggestion"] == "极简"

    # Stored version entry built from the RESOLVED copy/visual bodies
    item = asyncio.run(store.aget(("artifacts", "t1", "content_versions"), "latest"))
    assert item is not None
    entry = item.value["body"][0]
    assert entry["title"] == "原标题"
    assert entry["body"] == "正文"
    assert entry["image_prompts"] == ["p1"]
    assert entry["changes_summary"] == "AI 初稿"  # content_versions absent from checkpoint


# ── submit_ripple_decision retopic clear on a ref'd thread ───────────────────


def test_ripple_retopic_clears_trend_and_ripple_bodies_through_seam():
    """retopic must clear trend_data + the ripple vectors via the write seam.

    A bare inline ``{"trend_data": {}}`` write would be shadowed by the stale
    artifact ref on the next resolve — the old trend/ripple bodies would
    resurface and the router (meta-first) would keep routing on dead data.
    S4-2: the ripple vectors join the clear — tombstoned like trend_data
    (no routing meta needed; routers read only ripple_decision/ripple_pending).
    """
    store = InMemoryStore()
    trend_ref = _seed_body(
        store,
        "t1",
        "trend_data",
        {"hot_topics": [{"topic": "旧话题"}], "trending_keywords": ["kw"]},
    )
    pred_ref = _seed_body(store, "t1", "ripple_prediction", {"viral_probability": 0.42})
    pmf_ref = _seed_body(store, "t1", "ripple_pmf", {"pmf_score": 0.3})
    values = {
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "creating",
        "trend_summary": {"has_topics": True, "hot_topic_count": 1},
        "artifacts": {
            "trend_data": trend_ref,
            "ripple_prediction": pred_ref,
            "ripple_pmf": pmf_ref,
        },
    }
    graph = _make_graph(values, next_nodes=("ripple_gate",), store=store)
    # gate check + _run_graph_and_persist's post-run snapshot — same snapshot.
    graph.aget_state = AsyncMock(return_value=_snapshot(values, next_nodes=("ripple_gate",)))

    app = FastAPI()
    app.include_router(review_router, prefix="/api/review")
    client = _build_client(app, graph)

    with patch(
        "backend.api.routes._runner._run_graph_and_persist",
        new_callable=AsyncMock,
        return_value={"phase": "scouting"},
    ):
        resp = client.post("/api/review/ripple-decision/t1", json={"action": "retopic"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["action"] == "retopic"

    written = graph.aupdate_state.await_args_list[0].args[1]
    # Deliberate clears stay inline; the stale refs are tombstoned and the
    # routing meta is reset (should_plan reads has_topics=False → no reuse).
    assert written["trend_data"] == {}
    assert written["artifacts"]["trend_data"] is None
    assert written["trend_summary"] == {"has_topics": False, "hot_topic_count": 0}
    # S4-2: ripple vectors cleared through the same seam — inline {} kept,
    # stale refs tombstoned (no meta: routers never read these bodies).
    assert written["ripple_prediction"] == {}
    assert written["ripple_pmf"] == {}
    assert written["artifacts"]["ripple_prediction"] is None
    assert written["artifacts"]["ripple_pmf"] is None
    # Unrelated ripple clears untouched.
    assert written["ripple_progress"] == {}
    assert written["content_plan"] == {}


# ── ripple-retry read + write seams on a ref'd thread (S4-2) ─────────────────


def test_ripple_retry_writeback_goes_through_write_seam():
    """ripple-retry must resolve before reading and refify on writing.

    Read seam: the stale ripple_prediction lives in the Artifact Store — a raw
    read would see {} and misjudge ``is_fallback_prediction``, so the retry
    would silently "skip" on the very threads that need it. This test seeds
    the fallback-shaped body in the store (and nowhere inline), so the test
    only passes when the route resolves through the read seam.
    Write seam: the fresh prediction/pmf must be stored + ref'd — a bare
    inline write would be shadowed by the stale ref on the next resolve.
    """
    store = InMemoryStore()
    stale_ref = _seed_body(
        store,
        "t1",
        "ripple_prediction",
        {"viral_probability": 0, "confidence": 0, "estimated_reach": 0},
    )
    values = {
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "creating",
        # content_plan is not a refable field — it stays inline in the
        # checkpoint and supplies selected_topic for the retry.
        "content_plan": {"selected_topic": "旧话题", "hashtags": ["a"]},
        "artifacts": {"ripple_prediction": stale_ref},
    }
    graph = _make_graph(values, next_nodes=("ripple_gate",), store=store)
    # aget_state is hit twice: the route's eligibility read + _run_retry's
    # fresh read before the write-back.
    graph.aget_state = AsyncMock(return_value=_snapshot(values, next_nodes=("ripple_gate",)))

    app = FastAPI()
    app.include_router(workflow_router, prefix="/api/workflow")
    client = _build_client(app, graph)

    pred_body = {"viral_probability": 0.71, "confidence": 0.8, "estimated_reach": 5200}
    pmf_body = {"pmf_score": 0.66, "risk_factors": ["r1"]}
    captured: dict[str, Any] = {}
    real_create_task = asyncio.create_task

    def _fake_create_task(coro: Any, **kwargs: Any) -> Any:
        # Capture only the route's background body; delegate everything else
        # (TestClient/anyio internals) to the real create_task.
        if getattr(coro, "__name__", "") == "_run_retry":
            captured["coro"] = coro
            task = MagicMock()
            task.get_name = lambda: kwargs.get("name", "")
            return task
        return real_create_task(coro, **kwargs)

    with (
        patch("backend.services.ripple_service.RippleService") as mock_service,
        patch(
            "backend.api.routes.workflow.asyncio.create_task",
            side_effect=_fake_create_task,
        ),
    ):
        ripple = mock_service.get_instance.return_value
        ripple.submit_and_wait = AsyncMock(return_value={"raw": "payload"})
        ripple._parse_spread_result = MagicMock(return_value={"ripple_prediction": pred_body})
        ripple._parse_pmf_result = MagicMock(return_value={"ripple_pmf": pmf_body})

        resp = client.post("/api/workflow/ripple-retry/t1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "retrying"

        # Drive the captured background coroutine to completion in-scope.
        asyncio.run(captured["coro"])

    # The read seam mattered: the retry reached the service (it only gets past
    # the fallback check via the RESOLVED stale prediction), once per simulation.
    assert ripple.submit_and_wait.await_count == 2

    # Write seam: bodies stored, payload carries refs, not the inline bodies.
    written = graph.aupdate_state.await_args.args[1]
    assert "ripple_prediction" not in written
    assert "ripple_pmf" not in written
    assert written["artifacts"]["ripple_prediction"]["ref"] == (
        "artifact://ripple_prediction/latest"
    )
    assert written["artifacts"]["ripple_pmf"]["ref"] == "artifact://ripple_pmf/latest"
    # Both parses succeeded → fallback flags cleared inline.
    assert written["ripple_reason"] is None
    assert written["ripple_fallback"] is None

    # Stored bodies are the fresh simulation results.
    pred_item = asyncio.run(store.aget(("artifacts", "t1", "ripple_prediction"), "latest"))
    assert pred_item is not None
    assert pred_item.value["body"] == pred_body
    pmf_item = asyncio.run(store.aget(("artifacts", "t1", "ripple_pmf"), "latest"))
    assert pmf_item is not None
    assert pmf_item.value["body"] == pmf_body


# ── brief_content seams (S4-3) ───────────────────────────────────────────────


def test_brief_upload_writes_through_seam_on_refd_thread():
    """Re-uploading a brief on a ref'd thread must store the NEW text.

    A bare inline write of brief_content would be shadowed by the stale
    artifact ref on the next resolve — the user's corrected PDF text would
    silently revert to the previously stored body.
    """
    store = InMemoryStore()
    stale_ref = _seed_body(
        store, "t1", "brief_content", {"raw_text": "旧 brief", "source_type": "text"}
    )
    values = {
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "briefing",
        "artifacts": {"brief_content": stale_ref},
    }
    graph = _make_graph(values, next_nodes=(), store=store)
    # aget_state is hit twice: as_node resolution + the post-write resume check.
    graph.aget_state = AsyncMock(return_value=_snapshot(values, next_nodes=()))

    app = FastAPI()
    app.include_router(workflow_router, prefix="/api/workflow")
    client = _build_client(app, graph)

    resp = client.post(
        "/api/workflow/brief/upload/t1",
        files={"file": ("brief.txt", "修正后的 brief 正文".encode(), "text/plain")},
    )

    assert resp.status_code == 200, resp.text

    # Write seam: the fresh body is stored, the payload carries the ref.
    written = graph.aupdate_state.await_args.kwargs["values"]
    assert "brief_content" not in written
    assert written["artifacts"]["brief_content"]["ref"] == "artifact://brief_content/latest"

    item = asyncio.run(store.aget(("artifacts", "t1", "brief_content"), "latest"))
    assert item is not None
    assert item.value["body"] == {"raw_text": "修正后的 brief 正文", "source_type": "text"}


def test_status_label_and_history_save_resolve_refd_brief():
    """The /status DB label reads brief_content AFTER the hoisted resolve.

    On a ref'd thread a raw read would see no brief_content key and drop the
    brand label; the terminal-phase history dump would likewise persist a
    body-less state. Both consume the same up-front resolved values.
    """
    store = InMemoryStore()
    brief_ref = _seed_body(
        store,
        "t1",
        "brief_content",
        {"raw_text": "很长的原始 brief……", "brand_name": "RefBrand", "source_type": "text"},
    )
    values = {
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "completed",
        "artifacts": {"brief_content": brief_ref},
    }
    graph = _make_graph(values, next_nodes=(), store=store)
    graph.aget_state = AsyncMock(return_value=_snapshot(values, next_nodes=()))

    app = FastAPI()
    app.include_router(workflow_router, prefix="/api/workflow")
    client = _build_client(app, graph)

    with (
        patch("backend.api.routes.workflow._db_upsert", new_callable=AsyncMock, return_value=None),
        patch("backend.api.routes.workflow._save_history_file") as save_mock,
    ):
        resp = client.get("/api/workflow/status/t1")

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["label"] == "RefBrand"

    # The terminal-phase history dump received the RESOLVED values (full body).
    saved_values = save_mock.call_args.args[1]
    assert saved_values["brief_content"]["brand_name"] == "RefBrand"


def test_start_brief_mode_prestores_brief_body():
    """Brief-mode start seeds the raw_text into the store and carries the ref
    in the input state — the initial checkpoint never parks the body inline
    across the awaiting_brief pause."""
    store = InMemoryStore()
    graph = _make_graph({}, store=store)

    app = FastAPI()
    app.include_router(workflow_router, prefix="/api/workflow")
    client = _build_client(app, graph)

    with (
        patch(
            "backend.services.niche_resolver.resolve_account_niche",
            new_callable=AsyncMock,
        ) as niche_mock,
        patch("backend.api.routes.workflow.is_pool_ready", return_value=False),
        patch("backend.api.routes.workflow._db_upsert", new_callable=AsyncMock, return_value=None),
        patch(
            "backend.api.routes._runner._run_graph_and_persist",
            new_callable=AsyncMock,
        ) as run_mock,
    ):
        niche_res = MagicMock()
        niche_res.niche = "母婴"
        niche_res.to_dict = MagicMock(return_value={})
        niche_mock.return_value = niche_res
        resp = client.post(
            "/api/workflow/start",
            json={
                "account_id": "acc1",
                "workflow_mode": "brief",
                "brief_text": "这是 brief 原文",
                "async_mode": False,
            },
        )

    assert resp.status_code == 200, resp.text

    # The graph input carries the ref, not the body.
    initial_state = run_mock.await_args.args[3]
    assert "brief_content" not in initial_state
    assert initial_state["artifacts"]["brief_content"]["ref"] == "artifact://brief_content/latest"

    # The body was stored under the generated thread id.
    thread_id = run_mock.await_args.args[0]
    item = asyncio.run(store.aget(("artifacts", thread_id, "brief_content"), "latest"))
    assert item is not None
    assert item.value["body"] == {"raw_text": "这是 brief 原文", "source_type": "text"}


# ── _emit_status_transition gate payloads ────────────────────────────────────


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def emit(self, event_type: Any, *, thread_id: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type.value, thread_id, payload))


def test_emit_status_transition_resolves_refd_gate_payload(monkeypatch):
    """Gate events embed resolved bodies — a ref'd thread must not leak refs."""
    store = InMemoryStore()
    copy_ref = _seed_body(store, "t2", "copy_content", {"selected_title": "T", "body_text": "B"})
    versions_ref = _seed_body(store, "t2", "content_versions", [{"version_id": "v1", "title": "T"}])
    values = {
        "session_id": "s2",
        "phase": "reviewing",
        "artifacts": {"copy_content": copy_ref, "content_versions": versions_ref},
    }
    snap = _snapshot(values, next_nodes=("review_gate",))

    recorder = _EventRecorder()
    from backend.realtime import EventBusService

    monkeypatch.setattr(EventBusService, "get_instance", classmethod(lambda cls: recorder))

    asyncio.run(
        _runner._emit_status_transition(
            _runner.WorkflowStatus.AWAITING_REVIEW, "t2", snapshot=snap, store=store
        )
    )

    review_events = [e for e in recorder.events if e[0] == EventType.REVIEW_PENDING.value]
    assert len(review_events) == 1
    _, _, payload = review_events[0]
    assert payload["copy_content"] == {"selected_title": "T", "body_text": "B"}
    assert payload["version_history"] == [{"version_id": "v1", "title": "T"}]
    assert payload["visual_plan"] == {}


def test_emit_status_transition_legacy_thread_pays_no_store_trips(monkeypatch):
    """Legacy/inline snapshot: resolve short-circuits (no refs) — payload identical."""
    values = {
        "session_id": "s3",
        "phase": "reviewing",
        "copy_content": {"selected_title": "T"},
        "content_versions": [{"version_id": "v1"}],
    }
    snap = _snapshot(values, next_nodes=("review_gate",))

    recorder = _EventRecorder()
    from backend.realtime import EventBusService

    monkeypatch.setattr(EventBusService, "get_instance", classmethod(lambda cls: recorder))

    # store=None is fine for a legacy thread — resolve never touches it.
    asyncio.run(
        _runner._emit_status_transition(
            _runner.WorkflowStatus.AWAITING_REVIEW, "t3", snapshot=snap, store=None
        )
    )

    review_events = [e for e in recorder.events if e[0] == EventType.REVIEW_PENDING.value]
    assert len(review_events) == 1
    payload = review_events[0][2]
    assert payload["copy_content"] == {"selected_title": "T"}
    assert payload["version_history"] == [{"version_id": "v1"}]


# ── resolve seam sanity on the shapes used above ─────────────────────────────


def test_make_ref_shape_is_stable():
    """The ref filed under values["artifacts"] carries kind + id + hash."""
    ref = make_ref("copy_content", "latest", {"a": 1})
    assert ref["ref"] == "artifact://copy_content/latest"
    assert ref["kind"] == "copy_content"
    assert ref["id"] == "latest"
    assert len(ref["content_hash"]) == 64
