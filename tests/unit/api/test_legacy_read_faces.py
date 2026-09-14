"""Legacy-thread read-face regressions (P1a-S4-5).

One pre-P1a checkpoint — every big field inline, no ``artifacts`` marker key,
the pre-S1 ripple payloads nested in ``content_plan``, pre-S2 telemetry
inline (including a pre-kind entry) and the P1-dead keys (``messages`` /
``content_history``) still present — driven through the four API read faces:
/status (live snapshot + history-file fallback), /history, recover and the
public showcase. Each face must render the same full inline view it rendered
before P1a (prd line "legacy 线程 fixture … 透传渲染不劣化"): legacy threads
pay zero Artifact Store round trips (D1 absence detection → shallow copy) and
no stage key is dropped or defaulted differently.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes import public_showcase as showcase_module
from backend.api.routes.public_showcase import router as public_router
from backend.api.routes.workflow import router as workflow_router
from backend.db.workflows import WorkflowRow
from backend.state.hydration import CHECKPOINT_STAGE_KEYS

_BODY_TEXT = "三块钱的便利店咖啡，凭什么赢过三十块的生椰拿铁？"


def _legacy_checkpoint(**overrides: Any) -> dict[str, Any]:
    """A pre-P1a full-blob checkpoint in the old schema.

    Old-schema traits exercised on purpose:
    - every big field inline; the P1a marker key ``artifacts`` is ABSENT;
    - ripple payloads only nested in ``content_plan`` (pre-S1 shape);
    - telemetry entries inline (pre-S2 shape: one pre-kind entry, one node
      entry, one llm entry that must not leak into agent_timeline);
    - the dead keys ``messages``/``content_history`` still present (P1a
      deleted them from the schema, old checkpoints still carry them);
    - post-brief-era keys absent (workflow_mode/brief_*/blogger_*) so the
      hydration defaults get pinned.
    """
    values: dict[str, Any] = {
        "session_id": "xhs_acct_deadbeef",
        "account_id": "acc1",
        "phase": "reviewing",
        "current_agent": "copywriter",
        "created_at": "2026-09-01T08:00:00",
        "updated_at": "2026-09-01T08:30:00",
        "error": None,
        "pause_reason": None,
        "prev_phase": "planning",
        "_last_node": "copywriter",
        "messages": [{"role": "user", "content": "legacy blob"}],
        "content_history": [{"version": 1}],
        "performance_log": [
            {
                "agent": "trend_scout",
                "started_at": "2026-09-01T08:00:05",
                "completed_at": "2026-09-01T08:00:08",
                "duration_seconds": 3.0,
                "status": "success",
            },
            {
                "kind": "node",
                "agent": "content_strategist",
                "started_at": "2026-09-01T08:00:10",
                "completed_at": "2026-09-01T08:00:20",
                "duration_seconds": 10.0,
                "status": "success",
            },
            {
                "kind": "llm",
                "agent": "copywriter",
                "started_at": "2026-09-01T08:01:00",
                "completed_at": "2026-09-01T08:01:05",
                "duration_seconds": 5.0,
                "status": "success",
            },
        ],
        "trend_data": {"hot_topics": [{"topic": "早八人咖啡", "heat": 88}]},
        "content_plan": {
            "selected_topic": "早八人咖啡指南",
            "key_points": ["提神", "平价"],
            "target_audience": "通勤白领",
            "content_angle": "便利店平价咖啡横评",
            # pre-S1 ripple nesting — the only ripple location in old schema
            "ripple_prediction": {"estimated_reach": 120, "verdict": "值得一试"},
            "ripple_pmf": {"pmf_score": 0.72},
        },
        "copy_content": {
            "selected_title": "早八人的咖啡自救指南",
            "body_text": _BODY_TEXT,
            "hashtags": ["#咖啡", "#早八人", "#平价好物"],
        },
        "draft_content": {"body_text": "用户微调后的正文"},
        "optimization_analysis": {"gaps": ["缺少场景感"]},
        "content_versions": [{"version_id": "A", "title": "早八人的咖啡自救指南"}],
        "visual_plan": {
            "layout_style": "clean",
            "image_count": 4,
            "color_palette": ["#FFFFFF", "#8B5A2B"],
        },
        "publish_result": {
            "status": "published",
            "post_url": "https://www.xiaohongshu.com/explore/legacy1",
            "published_at": "2026-09-01T09:00:00",
        },
        "analytics": {"views": 100, "likes": 12},
        "ripple_comparison": {"actual_reach": 96},
        # Deliberately ABSENT: workflow_mode, brief_content, brief_clarification,
        # shooting_plan, blogger_*, selected_blogger, reselect_count,
        # ripple_reason, top-level ripple_prediction/ripple_pmf, artifacts.
    }
    values.update(overrides)
    return values


def _no_trip_store() -> MagicMock:
    """A store that fails the test if any resolve ever touches it — legacy
    threads must pay zero Artifact Store round trips."""
    store = MagicMock(name="store")
    store.aget = AsyncMock(side_effect=AssertionError("legacy thread hit the artifact store"))
    return store


def _snapshot(values: dict, *, next_nodes: tuple[str, ...] = ()) -> MagicMock:
    snap = MagicMock()
    snap.values = values
    snap.next = tuple(next_nodes)
    snap.tasks = ()
    snap.interrupts = ()
    return snap


def _graph(snapshot: MagicMock, store: Any) -> MagicMock:
    graph = MagicMock()
    graph.store = store
    graph.aget_state = AsyncMock(return_value=snapshot)
    return graph


def _workflow_client(graph: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(workflow_router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


# ── /status ──────────────────────────────────────────────────────────────────


def test_status_live_renders_legacy_checkpoint_inline():
    store = _no_trip_store()
    fixture = _legacy_checkpoint()
    graph = _graph(_snapshot(fixture, next_nodes=("review_gate",)), store)

    with (
        patch("backend.api.routes.workflow.assert_thread_owned", new_callable=AsyncMock),
        patch("backend.api.routes.workflow.is_pool_ready", return_value=False),
        patch(
            "backend.api.routes.workflow._db_upsert", new_callable=AsyncMock, return_value=None
        ) as upsert_mock,
        patch("backend.api.routes.workflow.db_get", new_callable=AsyncMock) as db_get_mock,
    ):
        resp = _workflow_client(graph).get("/api/workflow/status/t-legacy-status")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # Status derivation reads the legacy snapshot like any other
    assert data["phase"] == "reviewing"
    assert data["status"] == "awaiting_review"
    assert data["account_id"] == "acc1"
    assert data["pause_reason"] is None

    # Every big field rides through inline, byte-for-byte
    for key in (
        "trend_data",
        "content_plan",
        "copy_content",
        "draft_content",
        "optimization_analysis",
        "content_versions",
        "visual_plan",
        "publish_result",
        "analytics",
        "ripple_comparison",
    ):
        assert data[key] == fixture[key], key

    # Pre-S1 ripple nesting fallback still resolves through content_plan
    assert data["ripple_prediction"] == fixture["content_plan"]["ripple_prediction"]
    assert data["ripple_pmf"] == fixture["content_plan"]["ripple_pmf"]

    # Post-era keys the old schema never carried → hydration defaults
    assert data["workflow_mode"] == "trend"
    assert data["brief_content"] == {}
    assert data["brief_clarification"] == {}
    assert data["shooting_plan"] == {}
    assert data["blogger_candidates"] == []
    assert data["selected_blogger"] == {}
    assert data["blogger_notes"] == []
    assert data["blogger_candidate_limit"] == 5
    assert data["blogger_note_limit"] == 3
    assert data["reselect_count"] == 0
    assert data["ripple_reason"] == ""

    # Pre-S2 inline telemetry renders the agent timeline (llm entry filtered)
    timeline = data["agent_timeline"]
    assert [entry["agent"] for entry in timeline] == ["trend_scout", "content_strategist"]
    assert timeline[0]["duration_seconds"] == 3.0

    # Label comes from the inline content_plan (S4-3 hoisted resolve)
    upsert_mock.assert_awaited_once()
    assert upsert_mock.await_args.kwargs["label"] == "早八人咖啡指南"
    assert data["label"] == "早八人咖啡指南"
    db_get_mock.assert_not_awaited()

    # Legacy = zero store round trips
    store.aget.assert_not_awaited()


def test_status_history_file_fallback_keeps_pre_p1a_unhydrated_keys():
    """The dump of a completed legacy run must render through the fallback
    exactly as pre-P1a: keys that branch never hydrated (workflow_mode,
    brief_content, brief_clarification, shooting_plan, pause_reason) stay at
    their response-model defaults even though the dump carries them."""
    store = _no_trip_store()
    dump = _legacy_checkpoint(
        phase="completed",
        current_agent="analyst",
        workflow_mode="brief",
        brief_content={"brand_name": "悦己咖啡"},
        brief_clarification={"questions": ["q"]},
        shooting_plan={"sections": ["s"]},
    )
    graph = _graph(_snapshot({}), store)  # no live checkpoint

    with (
        patch("backend.api.routes.workflow.assert_thread_owned", new_callable=AsyncMock),
        patch("backend.api.routes.workflow._load_history_file", return_value=dump),
    ):
        resp = _workflow_client(graph).get("/api/workflow/status/t-legacy-dump")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["phase"] == "completed"
    assert data["status"] == "completed"
    assert data["progress_percent"] == 100
    assert data["label"] == ""

    # Hydrated stage keys keep their dump bodies; ripple nesting still resolves
    assert data["copy_content"] == dump["copy_content"]
    assert data["trend_data"] == dump["trend_data"]
    assert data["analytics"] == dump["analytics"]
    assert data["ripple_prediction"] == dump["content_plan"]["ripple_prediction"]

    # Keys the history-file branch never hydrated → model defaults, not dump
    assert data["workflow_mode"] == "trend"
    assert data["brief_content"] == {}
    assert data["brief_clarification"] == {}
    assert data["shooting_plan"] == {}

    # Inline telemetry → timeline; zero store trips for the legacy dump
    assert [e["agent"] for e in data["agent_timeline"]] == ["trend_scout", "content_strategist"]
    store.aget.assert_not_awaited()


# ── /history ─────────────────────────────────────────────────────────────────


async def _history_snapshots(*snaps: MagicMock):
    for snap in snaps:
        yield snap


def test_history_route_renders_legacy_checkpoints_inline():
    store = _no_trip_store()
    early = {
        "session_id": "xhs_acct_deadbeef",
        "phase": "planning",
        "current_agent": "content_strategist",
        "trend_data": {"hot_topics": [{"topic": "早八人咖啡", "heat": 88}]},
        "content_plan": {"selected_topic": "早八人咖啡指南"},
    }
    full = _legacy_checkpoint()
    s1 = MagicMock(
        values=early,
        metadata={"step": 2, "source": "loop"},
        config={"configurable": {"thread_id": "t-legacy-hist", "checkpoint_id": "ck-2"}},
        created_at="2026-09-01T08:10:00",
        next=("content_strategist",),
    )
    s2 = MagicMock(
        values=full,
        metadata={"step": 3, "source": "loop"},
        config={"configurable": {"thread_id": "t-legacy-hist", "checkpoint_id": "ck-3"}},
        created_at="2026-09-01T08:30:00",
        next=("review_gate",),
    )
    graph = _graph(_snapshot(full), store)
    graph.aget_state_history = lambda *args, **kwargs: _history_snapshots(s1, s2)

    with (
        patch("backend.api.routes.workflow.assert_thread_owned", new_callable=AsyncMock),
        patch("backend.api.routes.workflow.is_pool_ready", return_value=False),
    ):
        resp = _workflow_client(graph).get("/api/workflow/history/t-legacy-hist")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["thread_id"] == "t-legacy-hist"
    assert data["has_more"] is False
    cps = data["checkpoints"]
    assert [c["checkpoint_id"] for c in cps] == ["ck-2", "ck-3"]

    # Early checkpoint: absent stage keys → defaults, present ones byte-equal
    assert cps[0]["phase"] == "planning"
    assert cps[0]["trend_data"] == early["trend_data"]
    assert cps[0]["copy_content"] == {}
    assert cps[0]["next_nodes"] == ["content_strategist"]

    # Full checkpoint: every CheckpointSnapshot stage key present, bodies intact
    for key in CHECKPOINT_STAGE_KEYS:
        assert key in cps[1], key
    assert cps[1]["step"] == 3
    assert cps[1]["copy_content"] == full["copy_content"]
    assert cps[1]["content_versions"] == full["content_versions"]
    # pre-S1 ripple nesting fallback works on the /history surface too
    assert cps[1]["ripple_prediction"] == full["content_plan"]["ripple_prediction"]
    assert cps[1]["ripple_pmf"] == full["content_plan"]["ripple_pmf"]
    # post-era keys → hydration defaults
    assert cps[1]["workflow_mode"] == "trend"
    assert cps[1]["brief_content"] == {}
    store.aget.assert_not_awaited()


# ── recover ──────────────────────────────────────────────────────────────────


def test_recover_retry_failed_routes_off_legacy_scalars():
    """recover_view reads only the runtime scalars; a legacy error checkpoint
    routes retry_failed off _last_node/prev_phase exactly as before P1a."""
    store = _no_trip_store()
    fixture = _legacy_checkpoint(phase="error", error="LLM timeout")
    graph = _graph(_snapshot(fixture), store)

    with (
        patch("backend.api.routes.workflow.assert_thread_owned", new_callable=AsyncMock),
        patch(
            "backend.api.routes.workflow._start_resume_task", new_callable=AsyncMock
        ) as resume_mock,
    ):
        resp = _workflow_client(graph).post(
            "/api/workflow/recover/t-legacy-recover", json={"strategy": "retry_failed"}
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["recovered"] is True
    assert data["status"] == "running"
    assert data["strategy"] == "retry_failed"
    # _last_node "copywriter" → target node, mapped phase CREATING
    assert data["target_node"] == "copywriter"
    assert data["phase"] == "creating"
    resume_mock.assert_awaited_once()
    assert resume_mock.await_args.args[0] == "t-legacy-recover"
    assert resume_mock.await_args.args[3] == "creating"
    assert resume_mock.await_args.kwargs["input_data"] is None  # native resume


def test_recover_refuses_midflight_legacy_checkpoint():
    """A legacy checkpoint mid-flight (no error, no next) derives completed and
    recover must refuse it with the /resume guidance, unchanged."""
    graph = _graph(_snapshot(_legacy_checkpoint()), _no_trip_store())

    with patch("backend.api.routes.workflow.assert_thread_owned", new_callable=AsyncMock):
        resp = _workflow_client(graph).post(
            "/api/workflow/recover/t-legacy-refuse", json={"strategy": "skip_to_next"}
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["recovered"] is False
    assert data["status"] == "completed"
    assert "不可 recover" in data["message"]


# ── showcase ─────────────────────────────────────────────────────────────────


def test_showcase_public_case_renders_legacy_state_unchanged():
    store = _no_trip_store()
    fixture = _legacy_checkpoint(phase="completed")
    graph = _graph(_snapshot(fixture), store)
    row = WorkflowRow(
        thread_id="t-legacy-show",
        account_id="acc1",
        status="completed",
        phase="completed",
        label="早八人咖啡",
        showcase_visibility="public",
        public_id="case-legacy-show",
        created_at="2026-09-01T08:00:00",
        updated_at="2026-09-01T09:30:00",
    )

    app = FastAPI()
    app.include_router(public_router, prefix="/api/public")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    # Module-level TTL caches are process-global — clear this thread's entry.
    showcase_module._state_cache.pop("t-legacy-show", None)
    showcase_module._state_inflight.pop("t-legacy-show", None)

    with (
        patch.object(showcase_module, "is_pool_ready", return_value=True),
        patch.object(
            showcase_module, "db_get_by_public_id", new_callable=AsyncMock, return_value=row
        ),
        patch.object(
            showcase_module,
            "_existing_account_ids",
            new_callable=AsyncMock,
            return_value={"acc1"},
        ),
    ):
        resp = TestClient(app).get("/api/public/showcase/cases/case-legacy-show")

    assert resp.status_code == 200, resp.text
    payload = resp.json()["data"]
    assert payload["status"] == "completed"
    assert payload["phase"] == "completed"
    assert payload["workflow_mode"] == "trend"
    assert payload["has_final_summary"] is True

    # Public result projection over the inline bodies
    result = payload["result"]
    assert result["title"] == "早八人的咖啡自救指南"
    assert result["topic"] == "早八人咖啡指南"
    assert result["summary"] == _BODY_TEXT
    assert result["hashtags"] == ["#咖啡", "#早八人", "#平价好物"]
    assert result["key_points"] == ["提神", "平价"]
    assert result["target_audience"] == "通勤白领"
    assert result["visual"] == {
        "layout": "clean",
        "image_count": 4,
        "palette": ["#FFFFFF", "#8B5A2B"],
    }
    assert result["publish"] == {
        "status": "published",
        "published_at": "2026-09-01T09:00:00",
        "post_url": "https://www.xiaohongshu.com/explore/legacy1",
    }
    assert result["metrics"] == {"views": 100, "likes": 12}
    # pre-S1 public contract: the nested ripple payloads never leak into the
    # public projection (showcase reads flat keys only)
    assert "prediction" not in result

    # Legacy = zero store round trips through the showcase read seam
    store.aget.assert_not_awaited()
