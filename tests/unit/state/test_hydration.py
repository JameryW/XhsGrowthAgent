"""P1a-S1 hydration unit tests.

S1 moved the ~30 hardcoded state-key enumerations of six read surfaces into
backend/state/hydration.py. These tests pin the consolidated enumerations
against the pre-S1 wire contracts (the main extraction risk is silently
dropping a key) and verify the legacy full-blob passthrough semantics.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from backend.api.routes.workflow import (
    CheckpointSnapshot,
    WorkflowStatusResponse,
    _snapshot_to_checkpoint,
)
from backend.state.artifacts import REFABLE_FIELDS
from backend.state.hydration import (
    CHECKPOINT_STAGE_KEYS,
    REALTIME_EVENT_KEYS,
    SHOWCASE_STAGE_KEYS,
    STAGE_VIEW_KEYS,
    hydrate_state_view,
    is_legacy_thread,
    pick,
    recover_view,
    ripple_payload,
    stage_view,
    status_view,
    timeline_entry,
)

# ── Dead-field phantom-reader guards ─────────────────────────────────────────

_DEAD_STATE_MODULES = (
    Path("backend/state/schema.py"),
    Path("backend/state/substates.py"),
    Path("backend/graph/routers.py"),
    Path("backend/graph/builder.py"),
    Path("backend/api/routes/workflow.py"),
    Path("backend/api/routes/_runner.py"),
    Path("backend/api/routes/public_showcase.py"),
    Path("backend/cli/main.py"),
)


def _string_keys_accessed(source: str) -> set[str]:
    """All ``x["key"]`` / ``x.get("key")`` string constants in a module."""
    tree = ast.parse(source)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                keys.add(node.slice.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "pop", "setdefault"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
    return keys


def test_dead_fields_have_no_readers_or_writers():
    """messages / state-level content_history had no consumers and were deleted
    from XHSGrowthState (P1a-S1). If a phantom reader existed (or reappeared)
    in any module the slice touched, its key access would fail this guard —
    proving the deletion left no dangling state access behind. The Store
    namespace content_history_ns and MemoryManager are deliberately different
    things and stay live."""
    root = Path(__file__).resolve().parents[3]
    for rel in _DEAD_STATE_MODULES:
        text = (root / rel).read_text(encoding="utf-8")
        keys = _string_keys_accessed(text)
        assert "content_history" not in keys, f"state-level content_history reader in {rel}"
        # "messages" is a legit local/langchain name elsewhere (chat history,
        # i18n); only dict-key *access* to it in graph-facing modules is banned.
        assert "messages" not in keys, f"state-level messages reader in {rel}"


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _full_blob() -> dict[str, Any]:
    """A legacy full-blob thread — every existing checkpoint is this today
    (decision D1): all big fields inline in state."""
    return {
        "session_id": "xhs_acct_deadbeef",
        "phase": "creating",
        "current_agent": "copywriter",
        "error": None,
        "pause_reason": None,
        "prev_phase": "planning",
        "trend_data": {"hot_topics": [{"topic": "t"}]},
        "content_plan": {"selected_topic": "t"},
        "copy_content": {"selected_title": "title", "body_text": "body"},
        "draft_content": {"body_text": "user draft"},
        "optimization_analysis": {"gaps": ["g"]},
        "content_versions": [{"version_id": "A", "title": "vA"}],
        "visual_plan": {"cover_prompt": "c"},
        "publish_result": {"status": "published"},
        "analytics": {"views": 10},
        "ripple_prediction": {"estimated_reach": 100},
        "ripple_pmf": {"pmf_score": 0.7},
        "ripple_comparison": {"actual_reach": 90},
        "workflow_mode": "brief",
        "brief_content": {"brand_name": "b"},
        "brief_clarification": {"questions": ["q"]},
        "shooting_plan": {"sections": ["s"]},
        "blogger_candidates": [{"user_id": "u1"}],
        "selected_blogger": {"user_id": "u1"},
        "blogger_notes": [{"title": "n"}],
        "blogger_candidate_limit": 7,
        "blogger_note_limit": 4,
        "reselect_count": 1,
        "ripple_reason": "timeout",
        "performance_log": [],
    }


# ── Key-coverage guards: the consolidated enumerations vs the response models ─


def test_status_view_covers_every_state_sourced_status_field():
    """The single highest-risk S1 failure mode is silently dropping one of the
    ~23 keys the pre-S1 /status builder enumerated. Pin the hydration view's
    keys against every WorkflowStatusResponse field whose value comes from the
    graph state (the rest — thread_id/status/progress/label/... — are derived
    from snapshot meta, DB rows or services, not from state)."""
    state_sourced_response_fields = set(WorkflowStatusResponse.model_fields) - {
        "thread_id",  # path param
        "status",  # derive_status / persisted
        "next_steps",  # snapshot.next
        "progress_percent",  # phase-derived
        "account_id",  # resolver (state + DB + thread_id)
        "agent_timeline",  # transformed performance_log (own guard below)
        "ripple_progress",  # live RippleService, not state
        "label",  # DB row / derived
        "checkpoint_lost",  # DB-derived
        "orphan",  # derived
        # Runtime scalars the builder reads straight from state with their own
        # expressions (hydration-owned via RUNTIME_SCALAR_KEYS, not stage view):
        "phase",
        "current_agent",
        "error",
        "created_at",
        "updated_at",
        "pause_reason",
    }
    assert state_sourced_response_fields == STAGE_VIEW_KEYS


def test_checkpoint_view_covers_every_checkpoint_stage_field():
    """Same guard for /history: hydration's checkpoint key set must equal the
    stage fields CheckpointSnapshot had before S1 (never a subset)."""
    checkpoint_state_fields = set(CheckpointSnapshot.model_fields) - {
        "checkpoint_id",
        "step",
        "source",
        "phase",
        "current_agent",
        "created_at",
        "next_nodes",
    }
    assert checkpoint_state_fields == CHECKPOINT_STAGE_KEYS


def test_realtime_event_keys_cover_every_emit_surface():
    """The realtime payload keys (per event) are owned by hydration; adding or
    dropping one here is a deliberate contract change, not an accident."""
    assert REALTIME_EVENT_KEYS["review_pending"] == (
        "content_plan",
        "copy_content",
        "visual_plan",
        "content_versions",
    )
    assert REALTIME_EVENT_KEYS["completed"] == (
        "publish_result",
        "copy_content",
        "trend_data",
        "content_plan",
        "visual_plan",
        "analytics",
        "ripple_prediction",
        "ripple_pmf",
        "ripple_comparison",
    )
    # Every realtime key must exist in the stage view (typos would KeyError).
    for keys in REALTIME_EVENT_KEYS.values():
        assert set(keys) <= (STAGE_VIEW_KEYS | {"phase", "current_agent", "error"})


def test_showcase_stage_keys_are_the_historical_public_projection():
    assert SHOWCASE_STAGE_KEYS == (
        "brief_content",
        "trend_data",
        "content_plan",
        "copy_content",
        "visual_plan",
        "publish_result",
        "analytics",
        "ripple_prediction",
        "ripple_pmf",
    )


# ── Legacy full-blob passthrough ─────────────────────────────────────────────


def test_legacy_full_blob_passes_through_unchanged():
    values = _full_blob()
    assert is_legacy_thread(values)
    view = hydrate_state_view(values)
    assert set(view) == STAGE_VIEW_KEYS
    for key in STAGE_VIEW_KEYS:
        assert view[key] == values[key], f"{key} drifted during extraction"


def test_missing_and_none_fields_derive_status_safe():
    """derive_status only consumes phase/status/error scalars, but the read
    surfaces must also tolerate a state with None or absent stage fields —
    empty checkpoints hydrate to model-equivalent defaults, never None/raise."""
    view = hydrate_state_view({})
    assert view["trend_data"] == {}
    assert view["content_versions"] == []
    assert view["blogger_candidates"] == []
    assert view["blogger_candidate_limit"] == 5
    assert view["blogger_note_limit"] == 3
    assert view["reselect_count"] == 0
    assert view["workflow_mode"] == "trend"
    assert view["ripple_reason"] == ""

    nulled = hydrate_state_view(
        {"copy_content": None, "content_versions": None, "workflow_mode": None}
    )
    assert nulled["copy_content"] == {}
    assert nulled["content_versions"] == []
    assert nulled["workflow_mode"] == "trend"


def test_ripple_payload_keeps_nested_checkpoint_fallback():
    """Pre-S1, /status and /history resolved ripple payloads nested under
    ``content_plan`` ONLY (``_extract_ripple``); that exact order is now owned
    here once. extra_data/analytics were never consulted before S1, so they must
    not leak into the payload either — otherwise a checkpoint that used to
    render empty would suddenly hydrate a value (a wire regression)."""
    assert ripple_payload(
        {"content_plan": {"ripple_prediction": {"v": 1}}}, "ripple_prediction"
    ) == {"v": 1}
    assert ripple_payload({}, "ripple_prediction") == {}
    # Regression guards for byte-identity: non-content_plan containers ignored.
    assert ripple_payload({"extra_data": {"ripple_pmf": {"pmf_score": 0.5}}}, "ripple_pmf") == {}
    assert ripple_payload({"analytics": {"ripple_prediction": {"v": 1}}}, "ripple_prediction") == {}
    # Top-level still wins over the nested fallback.
    assert ripple_payload(
        {"ripple_pmf": {"top": 1}, "content_plan": {"ripple_pmf": {"nested": 1}}}, "ripple_pmf"
    ) == {"top": 1}


def test_stage_view_subset_selection():
    values = _full_blob()
    subset = stage_view(values, ["copy_content", "content_versions"])
    assert subset == {
        "copy_content": values["copy_content"],
        "content_versions": values["content_versions"],
    }


def test_recover_view_exposes_strategy_scalars():
    rv = recover_view({"session_id": "s", "_last_node": "copywriter", "prev_phase": "creating"})
    assert rv == {"session_id": "s", "_last_node": "copywriter", "prev_phase": "creating"}
    assert set(recover_view({})) == {"session_id", "_last_node", "prev_phase"}


def test_pick_none_guard_semantics():
    assert pick({"k": None}, "k", {}) == {}
    assert pick({}, "k", 5) == 5
    assert pick({"k": 0}, "k", 5) == 0  # only None is guarded, falsy survives


# ── agent_timeline transform (S2 moved the source to the Event store; the
# transform itself is source-agnostic and stays here) ──


def test_timeline_entry_transform_and_filter():
    assert timeline_entry({"agent": "copywriter"}) == {
        "agent": "copywriter",
        "started_at": "",
        "completed_at": "",
        "duration_seconds": 0.0,
        "status": "success",
        "error": None,
    }
    assert timeline_entry({"agent": "x", "kind": "llm"}) is None
    assert timeline_entry("garbage") is None
    # kind=="node" (explicit or absent) is kept — pre-S1 predicate unchanged.
    assert timeline_entry({"agent": "y", "kind": "node"}) is not None


# ── Response-shape behavior neutrality ───────────────────────────────────────


def test_status_view_rounds_tripless_into_response():
    """Every state-sourced field the hydrated view feeds must satisfy the
    WorkflowStatusResponse types for both a full and an empty state."""
    full = WorkflowStatusResponse(
        thread_id="xhs_a_1",
        phase="creating",
        status="running",
        current_agent="copywriter",
        next_steps=[],
        **status_view(_full_blob()),
    ).model_dump()
    assert full["copy_content"] == {"selected_title": "title", "body_text": "body"}
    assert full["reselect_count"] == 1
    empty = WorkflowStatusResponse(
        thread_id="xhs_a_1",
        phase="idle",
        status="running",
        current_agent="orchestrator",
        next_steps=[],
        **status_view({}),
    ).model_dump()
    for key in STAGE_VIEW_KEYS:
        assert key in empty  # no field dropped from the response


async def test_snapshot_to_checkpoint_matches_model_enumeration():
    snapshot = _make_snapshot(_full_blob())
    cp = (await _snapshot_to_checkpoint(snapshot)).model_dump()
    for key in CHECKPOINT_STAGE_KEYS:
        assert cp[key] == _full_blob()[key]


async def test_snapshot_to_checkpoint_resolves_refd_state():
    """P1a-S3 equivalence: /history renders a ref'd checkpoint exactly like the
    same state stored inline (D4 — the payload contract does not change with
    the storage tier)."""
    from langgraph.store.memory import InMemoryStore

    from backend.state.artifacts import refify_updates

    blob = _full_blob()
    store = InMemoryStore()
    refified = await refify_updates(
        store, "t_hydration", {k: v for k, v in blob.items() if k in REFABLE_FIELDS}
    )
    assert not REFABLE_FIELDS & set(refified)  # every refable body went out-of-line

    ref_values = {**blob, **refified}
    ref_cp = (
        await _snapshot_to_checkpoint(_make_snapshot(ref_values), store, "t_hydration")
    ).model_dump()
    inline_cp = (await _snapshot_to_checkpoint(_make_snapshot(blob))).model_dump()
    for key in CHECKPOINT_STAGE_KEYS:
        assert ref_cp[key] == inline_cp[key], key


def _make_snapshot(values: dict[str, Any]):
    from unittest.mock import MagicMock

    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = ("copywriter",)
    snapshot.created_at = "2026-06-05T12:00:00Z"
    snapshot.metadata = {"step": 2, "source": "loop"}
    snapshot.config = {"configurable": {"thread_id": "t", "checkpoint_id": "cp_1"}}
    return snapshot


# ── Ref'd-thread stub (S3 hook) ───────────────────────────────────────────────


def test_refd_thread_marker_is_recognized_and_stays_stubbed():
    """Once S3 lands, a thread carrying artifacts refs is detected; until the
    ArtifactStore resolves them the inline path renders what state has — the
    stub must never crash on a refs-only state."""
    values = {**_full_blob(), "artifacts": {"copy": {"kind": "copy", "id": "c1"}}}
    assert not is_legacy_thread(values)
    # S1 stub: resolution falls through to the inline read (no store lookups),
    # so the view still equals the legacy passthrough.
    view = hydrate_state_view(values)
    assert view["copy_content"] == values["copy_content"]
    bare = hydrate_state_view({"artifacts": {"copy": {"kind": "copy", "id": "c1"}}})
    assert bare["copy_content"] == {}
