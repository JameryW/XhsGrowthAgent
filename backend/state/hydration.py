"""Single aggregation point for reading workflow state (P1a-S1 hydration).

Six read surfaces — ``/status`` (live snapshot + history-file fallback),
``/history`` (``_snapshot_to_checkpoint`` + history-file fallback), recover,
the public showcase checkpoint path, the realtime event payload builders in
``_runner._emit_status_transition`` and the ``agent_timeline`` transform —
previously each hardcoded overlapping ``values.get(...)`` enumerations of
~30 state keys independently. This module owns that enumeration: every state
key that leaves the API boundary is listed here exactly once.

Shape contract (design info.md D4): the read surfaces keep their full response
payloads byte-for-byte identical — hydration only deduplicates the key
extraction, it does not change any output.

Legacy vs new threads (decision D1): every checkpoint written before P1a-S3 is a
*legacy full-blob* thread — the big business fields (copy_content, visual_plan,
…) sit inline in the graph state. Since S3 landed, a post-S3 thread keeps only
``"artifacts": {<state key>: ArtifactRef}`` in RuntimeState and the bodies live
in the Artifact Store (``backend/state/artifacts.py``). Resolution does NOT
happen inside this module: callers pass state through
:func:`backend.state.artifacts.resolve_state` first (wired at the route read
seam and the ``artifact_seam`` node boundary), so every view below still sees a
fully-inline state and stays byte-identical to the pre-P1a payload.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final, TypedDict

from backend.state.modes import DEFAULT_WORKFLOW_MODE

__all__ = [
    "ARTIFACTS_KEY",
    "CHECKPOINT_STAGE_KEYS",
    "REALTIME_EVENT_KEYS",
    "RUNTIME_SCALAR_KEYS",
    "SHOWCASE_STAGE_KEYS",
    "STAGE_LIST_KEYS",
    "STAGE_SCALAR_KEYS",
    "STAGE_VIEW_KEYS",
    "STATE_LEVEL_DEAD_KEYS",
    "checkpoint_view",
    "hydrate_state_view",
    "is_legacy_thread",
    "pick",
    "realtime_view",
    "recover_view",
    "ripple_payload",
    "showcase_view",
    "stage_view",
    "status_view",
    "timeline_entry",
]

# Marker key future ref'd threads will use to point at out-of-line artifacts
# (design info.md §一 "refs: {"copy": "artifact://copy/<id>", …}"). Not a
# declared state field yet — its absence is what makes a thread "legacy".
ARTIFACTS_KEY: Final = "artifacts"

# Dead state keys removed by P1a (no writers, no readers). Declared here so the
# deletion guard tests and future refactors can see the canonical list: the real
# content history lives in the Store namespace ``content_history_ns``, and
# telemetry moved out of the checkpoint in S2 (``backend/state/events.py``).
STATE_LEVEL_DEAD_KEYS: Final = frozenset({"messages", "content_history", "performance_log"})

# Scalar runtime keys read straight out of state values by the read surfaces.
RUNTIME_SCALAR_KEYS: Final[frozenset[str]] = frozenset(
    {
        "session_id",
        "phase",
        "status",
        "current_agent",
        "error",
        "error_class",
        "pause_reason",
        "prev_phase",
        "_last_node",
        "created_at",
        "updated_at",
        "account_id",
        "workflow_mode",
    }
)

# Keys of :class:`StateView` that are lists rather than dicts (guards for
# surface-specific defaulting).
STAGE_LIST_KEYS: Final[frozenset[str]] = frozenset(
    {"content_versions", "blogger_candidates", "blogger_notes"}
)

# Keys of :class:`StateView` that are scalars (str/int) rather than containers.
STAGE_SCALAR_KEYS: Final[frozenset[str]] = frozenset(
    {"workflow_mode", "blogger_candidate_limit", "blogger_note_limit", "reselect_count"}
)


class StateView(TypedDict, total=False):
    """Normalized stage-data view over raw graph state values.

    ``total=False`` so callers may build partial views; :func:`hydrate_state_view`
    always fills every key below.
    """

    trend_data: dict[str, Any]
    content_plan: dict[str, Any]
    copy_content: dict[str, Any]
    draft_content: dict[str, Any]
    optimization_analysis: dict[str, Any]
    content_versions: list[dict[str, Any]]
    visual_plan: dict[str, Any]
    publish_result: dict[str, Any]
    analytics: dict[str, Any]
    ripple_prediction: dict[str, Any]
    ripple_pmf: dict[str, Any]
    ripple_comparison: dict[str, Any]
    workflow_mode: str
    brief_content: dict[str, Any]
    brief_clarification: dict[str, Any]
    shooting_plan: dict[str, Any]
    blogger_candidates: list[dict[str, Any]]
    selected_blogger: dict[str, Any]
    blogger_notes: list[dict[str, Any]]
    blogger_candidate_limit: int
    blogger_note_limit: int
    reselect_count: int
    ripple_reason: str


# Every stage key the hydration layer owns (exported so tests can pin the
# enumeration against the pre-S1 response shapes).
STAGE_VIEW_KEYS: Final[frozenset[str]] = frozenset(StateView.__annotations__.keys())

# Stage-data keys CheckpointSnapshot (/history) exposes.
CHECKPOINT_STAGE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "trend_data",
        "content_plan",
        "copy_content",
        "draft_content",
        "optimization_analysis",
        "content_versions",
        "visual_plan",
        "publish_result",
        "analytics",
        "ripple_prediction",
        "ripple_pmf",
        "ripple_comparison",
        "workflow_mode",
        "brief_content",
        "shooting_plan",
    }
)

# Stage keys the public showcase projects (``_public_result`` /
# ``_synthetic_final_checkpoint``). Deliberately WITHOUT the ripple nesting
# fallback — the public surface has always read flat keys only, and widening
# it would change public payloads.
SHOWCASE_STAGE_KEYS: Final[tuple[str, ...]] = (
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

# Keys the /status history-file fallback never hydrated from the dumped state
# (they came out of the response-model defaults). Kept excluded until a
# deliberate contract change so the history-file /status payload stays
# byte-for-byte identical.
_HISTORY_FILE_UNHYDRATED_KEYS: Final[frozenset[str]] = frozenset(
    {"workflow_mode", "brief_content", "brief_clarification", "shooting_plan", "pause_reason"}
)

# Keys _runner._emit_status_transition pulls out of snapshot.values, per
# realtime event shape, in the exact insertion order the payload dicts are
# built (payload byte-identity depends on this order). ``status`` and
# ``next_steps`` come from the derived workflow status and ``snapshot.next``
# respectively, not from the state.
REALTIME_EVENT_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "base": ("phase", "current_agent"),
    "review_pending": ("content_plan", "copy_content", "visual_plan", "content_versions"),
    "awaiting_choice": ("content_versions", "draft_content", "optimization_analysis"),
    "awaiting_draft": ("copy_content", "content_plan"),
    "awaiting_brief": ("brief_content",),
    "awaiting_ripple_decision": (
        "ripple_prediction",
        "ripple_pmf",
        "ripple_reason",
        "reselect_count",
    ),
    "awaiting_blogger_selection": (
        "blogger_candidates",
        "blogger_candidate_limit",
        "blogger_note_limit",
    ),
    "completed": (
        "publish_result",
        "copy_content",
        "trend_data",
        "content_plan",
        "visual_plan",
        "analytics",
        "ripple_prediction",
        "ripple_pmf",
        "ripple_comparison",
    ),
    "error": ("error",),
}

# Scalars recover reads out of the live checkpoint before deciding a strategy.
_RECOVER_KEYS: Final[tuple[str, ...]] = ("session_id", "_last_node", "prev_phase")


def pick(values: dict[str, Any], key: str, default: Any = None) -> Any:
    """``dict.get`` with a None guard — mirrors the ``values.get(k) or default``
    convention used by the read surfaces (a key explicitly set to ``None``
    hydrates to the default, so old checkpoints carrying null fields render
    exactly as before)."""
    value = values.get(key)
    return default if value is None else value


def ripple_payload(values: dict[str, Any], key: str) -> dict[str, Any]:
    """Pull a ripple payload, falling back to the ``content_plan`` nesting for
    older checkpoints — the exact pre-S1 ``_extract_ripple`` resolution order
    (top-level, then ``content_plan``, then empty), now owned here once across
    the /status and /history surfaces. Keeping this to ``content_plan`` only is
    load-bearing for byte-identity: no read surface ever consulted other
    containers before S1.
    """
    value = values.get(key)
    if value:
        return value  # type: ignore[no-any-return]
    container = values.get("content_plan")
    if isinstance(container, dict):
        nested = container.get(key)
        if nested:
            return nested  # type: ignore[no-any-return]
    return {}


def is_legacy_thread(values: dict[str, Any]) -> bool:
    """True when the state carries its stage data inline (no artifact refs).

    Every checkpoint written before P1a-S3 is a legacy full-blob thread. Ref'd
    threads (S3+) will set ``artifacts`` to a mapping of kind → ArtifactRef.
    """
    return not isinstance(values.get(ARTIFACTS_KEY), dict)


def hydrate_state_view(values: dict[str, Any]) -> StateView:
    """Aggregate the stage-data keys every read surface needs.

    The values handed in are expected to be *already resolved*: since S3 the
    callers run state through :func:`backend.state.artifacts.resolve_state`
    first, so a ref'd thread arrives with its bodies inline and this transform
    stays storage-agnostic — one code path renders both tiers identically.
    """
    return {
        "trend_data": pick(values, "trend_data") or {},
        "content_plan": pick(values, "content_plan") or {},
        "copy_content": pick(values, "copy_content") or {},
        "draft_content": pick(values, "draft_content") or {},
        "optimization_analysis": pick(values, "optimization_analysis") or {},
        "content_versions": pick(values, "content_versions") or [],
        "visual_plan": pick(values, "visual_plan") or {},
        "publish_result": pick(values, "publish_result") or {},
        "analytics": pick(values, "analytics") or {},
        "ripple_prediction": ripple_payload(values, "ripple_prediction"),
        "ripple_pmf": ripple_payload(values, "ripple_pmf"),
        "ripple_comparison": pick(values, "ripple_comparison") or {},
        "workflow_mode": pick(values, "workflow_mode") or DEFAULT_WORKFLOW_MODE.value,
        "brief_content": pick(values, "brief_content") or {},
        "brief_clarification": pick(values, "brief_clarification") or {},
        "shooting_plan": pick(values, "shooting_plan") or {},
        "blogger_candidates": pick(values, "blogger_candidates") or [],
        "selected_blogger": pick(values, "selected_blogger") or {},
        "blogger_notes": pick(values, "blogger_notes") or [],
        "blogger_candidate_limit": pick(values, "blogger_candidate_limit", 5),
        "blogger_note_limit": pick(values, "blogger_note_limit", 3),
        "reselect_count": pick(values, "reselect_count", 0),
        "ripple_reason": pick(values, "ripple_reason") or "",
    }


def stage_view(values: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """Subset of the hydrated view for a surface that only echoes some keys.

    Hydration runs over the full state first, so every surface reads through
    the same normalization — the key list it requests is the only choice it
    makes.
    """
    view = hydrate_state_view(values)
    return {key: view[key] for key in keys}  # type: ignore[literal-required]


def status_view(values: dict[str, Any]) -> StateView:
    """Full stage-data payload for the live-snapshot /status response (D4: the
    complete aggregation, not a slim ref view)."""
    return hydrate_state_view(values)


def history_file_view(values: dict[str, Any]) -> dict[str, Any]:
    """Stage-data payload for the /status history-file fallback.

    Same aggregation as :func:`status_view` minus the keys that branch has
    historically left to response-model defaults — kept here (rather than at
    the route) so the exception lives with the enumeration it trims.
    """
    view = dict(hydrate_state_view(values))
    for key in _HISTORY_FILE_UNHYDRATED_KEYS:
        view.pop(key, None)
    return view


def checkpoint_view(values: dict[str, Any]) -> dict[str, Any]:
    """Stage-data payload for one checkpoint in /history (CheckpointSnapshot),
    also used by the public showcase checkpoint cache via /history."""
    return stage_view(values, sorted(CHECKPOINT_STAGE_KEYS))


def realtime_view(values: dict[str, Any], event: str) -> dict[str, Any]:
    """Stage-data payload for a realtime event shape (see REALTIME_EVENT_KEYS),
    in the historical payload insertion order."""
    return stage_view(values, REALTIME_EVENT_KEYS[event])


def showcase_view(values: dict[str, Any]) -> dict[str, Any]:
    """Stage keys the public showcase projects, with flat-only reads (no
    ripple nesting fallback) to keep public payloads byte-identical."""
    return {key: (values.get(key) or {}) for key in SHOWCASE_STAGE_KEYS}


def recover_view(values: dict[str, Any]) -> dict[str, Any]:
    """Scalars /recover inspects on the live checkpoint (strategy routing).
    Routed through hydration so S2/S3 field moves land in one place; today
    these are RuntimeState scalars passed through unchanged."""
    return {key: values.get(key) for key in _RECOVER_KEYS}


def timeline_entry(entry: Any) -> dict[str, Any] | None:
    """One telemetry record normalized for ``agent_timeline``.

    Non-dict records and non-node kinds (llm/ripple/human_wait telemetry that
    shares the log but does not populate the timeline schema) return ``None``
    so callers filter them out. Returns plain dicts so the /status route can
    feed them into ``AgentTimelineEntry`` without importing the response model
    here. Only the READ transform lives here — the records themselves come from
    :func:`backend.state.events.load_perf_log` (P1a-S2: Event store, with the
    legacy inline checkpoint list still merged in).
    """
    if not isinstance(entry, dict):
        return None
    if entry.get("kind", "node") != "node":
        return None
    return {
        "agent": entry.get("agent", "unknown"),
        "started_at": entry.get("started_at", ""),
        "completed_at": entry.get("completed_at", ""),
        "duration_seconds": entry.get("duration_seconds", 0.0),
        "status": entry.get("status", "success"),
        "error": entry.get("error"),
    }
