"""Artifact Store façade — the read/write seam for out-of-line workflow content.

P1a splits the LangGraph state into three tiers (design ``info.md`` §一): the
RuntimeState checkpoint keeps only small, bounded routing data; large business
bodies (copy, visual plan, draft, shooting plan, ripple comparison, …) move to
the Artifact Store and are referenced from RuntimeState by a tiny
:class:`ArtifactRef`. Telemetry (S2) already lives in its own Event store.

Backend (decision D2): the Artifact Store *is* the LangGraph ``BaseStore`` — the
same store LangGraph already injects into every node — under the namespace
``("artifacts", thread_id, kind)``. This module is the thin façade
(``put`` / ``get`` / resolve) so a future backend swap stays in one file, exactly
like :mod:`backend.state.events` for telemetry.

RuntimeState side (decision D4): the state carries
``values["artifacts"] = {<state key>: ArtifactRef}``. Refs are keyed by *state
key* (not by a short alias) so :func:`resolve_state` needs no side table and the
write/read/test paths cannot drift apart. The ref string itself
(``artifact://<kind>/<id>``) carries the kind, which is what the namespace needs.

Read seam: :func:`resolve_state` returns a copy of the state values with every
ref'd field replaced by its stored body, so the hydration layer and every read
surface keep consuming a fully-inline view and stay byte-identical to the
pre-P1a payload (prd D4: the /status contract does not change). A legacy thread
(D1: no checkpoint rewrite) carries no ``artifacts`` mapping and is returned
unchanged — the read surfaces then never touch the store for it.

Best-effort by contract, mirroring the Event store: a node's real work must
never fail because an artifact could not be stored, so :func:`put_artifact`
returns ``None`` on failure and the writer keeps the body inline instead of
pointing at a body that does not exist.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, TypedDict

from langgraph.store.base import BaseStore

logger = logging.getLogger("xhs_growth.state.artifacts")

__all__ = [
    "ARTIFACTS_KEY",
    "DEFAULT_ARTIFACT_ID",
    "REF_SCHEME",
    "ArtifactRef",
    "artifact_namespace",
    "artifact_seam",
    "content_hash",
    "get_artifact_body",
    "is_refd_thread",
    "load_artifact_bodies",
    "make_ref",
    "parse_ref",
    "put_artifact",
    "REFABLE_FIELDS",
    "refify_updates",
    "refs_of",
    "resolve_state",
    "versions_meta_of",
    "blogger_notes_meta_of",
    "trend_summary_of",
]

# RuntimeState key holding the ``{state_key: ArtifactRef}`` mapping. Its absence
# is what makes a thread "legacy" (S1 hydration contract).
ARTIFACTS_KEY: Final = "artifacts"

# Namespace root for every artifact: ``("artifacts", thread_id, kind)``.
_NAMESPACE_ROOT: Final = "artifacts"

# Ref scheme and separator for ``artifact://<kind>/<id>``.
REF_SCHEME: Final = "artifact://"
_ID_SEPARATOR: Final = "/"

# Artifact id used by replace-semantics fields (one live body per thread+kind).
DEFAULT_ARTIFACT_ID: Final = "latest"


class ArtifactRef(TypedDict):
    """A pointer to a body stored in the Artifact Store.

    Mirrors the prd shape (``artifact://kind/id`` + content_hash + size +
    updated_at) and is what RuntimeState keeps in place of the body.
    """

    ref: str
    kind: str
    id: str
    content_hash: str
    size: int
    updated_at: str


def _canonical_json(body: Any) -> str:
    """Deterministic JSON for a body, so equal bodies hash equally.

    ``sort_keys`` + tight separators make the hash independent of dict
    insertion order and incidental whitespace; ``ensure_ascii=False`` keeps
    Chinese copy compact (the payload is UTF-8 on the wire either way).
    """
    return json.dumps(
        body,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def content_hash(body: Any) -> str:
    """Stable sha256 over a canonical JSON rendering of ``body``.

    This is the identity used to prove artifact-backed content equals the old
    inline content (S4 publish ``content_hash`` equivalence), so it must depend
    only on the body's value, never on when or where it was stored.
    """
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def artifact_namespace(thread_id: str, kind: str) -> tuple[str, str, str]:
    """The BaseStore namespace for one kind of artifact of one thread."""
    return (_NAMESPACE_ROOT, thread_id, kind)


def make_ref(
    kind: str,
    artifact_id: str,
    body: Any,
    *,
    updated_at: str | None = None,
) -> ArtifactRef:
    """Build the ref for ``body`` (hash/size computed from the body itself)."""
    encoded = _canonical_json(body).encode("utf-8")
    return ArtifactRef(
        ref=f"{REF_SCHEME}{kind}{_ID_SEPARATOR}{artifact_id}",
        kind=kind,
        id=artifact_id,
        content_hash=hashlib.sha256(encoded).hexdigest(),
        size=len(encoded),
        updated_at=updated_at or datetime.now(UTC).isoformat(),
    )


def parse_ref(ref: str) -> tuple[str, str] | None:
    """Split ``artifact://<kind>/<id>`` into ``(kind, id)``; ``None`` if malformed."""
    if not isinstance(ref, str) or not ref.startswith(REF_SCHEME):
        return None
    kind, sep, artifact_id = ref[len(REF_SCHEME) :].partition(_ID_SEPARATOR)
    if not sep or not kind or not artifact_id:
        return None
    return kind, artifact_id


def refs_of(values: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The ``{state_key: ArtifactRef}`` mapping of a state, or ``{}``.

    Legacy threads and non-dict values both yield ``{}`` so callers can treat
    "no refs" and "legacy" identically.
    """
    if not values:
        return {}
    raw = values.get(ARTIFACTS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(key): ref for key, ref in raw.items() if isinstance(ref, dict)}


def is_refd_thread(values: Mapping[str, Any] | None) -> bool:
    """True when the state carries at least one artifact reference."""
    return bool(refs_of(values))


async def put_artifact(
    store: BaseStore | None,
    thread_id: str,
    state_key: str,
    body: Any,
    *,
    kind: str | None = None,
    artifact_id: str = DEFAULT_ARTIFACT_ID,
) -> ArtifactRef | None:
    """Store ``body`` and return its ref, or ``None`` when it could not be stored.

    ``state_key`` is the RuntimeState key the ref will be filed under; ``kind``
    (defaulting to ``state_key``) is the namespace/ref kind. Best-effort: a
    storage failure is logged and reported as ``None`` so the caller can keep
    the body inline rather than dangling a ref at a missing body.
    """
    resolved_kind = kind or state_key
    ref = make_ref(resolved_kind, artifact_id, body)
    if store is None or not thread_id:
        return None
    try:
        await store.aput(
            artifact_namespace(thread_id, resolved_kind),
            artifact_id,
            {"body": body, "ref": dict(ref)},
        )
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        logger.warning("artifact put failed (%s/%s): %s", thread_id, resolved_kind, exc)
        return None
    return ref


async def get_artifact_body(
    store: BaseStore | None,
    thread_id: str,
    ref: str,
) -> Any | None:
    """Fetch the body a ref points at, or ``None`` when unavailable."""
    parsed = parse_ref(ref)
    if store is None or not thread_id or parsed is None:
        return None
    kind, artifact_id = parsed
    try:
        item = await store.aget(artifact_namespace(thread_id, kind), artifact_id)
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        logger.warning("artifact get failed (%s/%s): %s", thread_id, kind, exc)
        return None
    if item is None:
        return None
    value = item.value
    if isinstance(value, dict) and "body" in value:
        return value["body"]
    return None


async def load_artifact_bodies(
    store: BaseStore | None,
    thread_id: str,
    values: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve every ref in ``values`` to its body, keyed by state key.

    Missing/undecodable bodies are simply omitted from the result; the caller
    then leaves that field's inline value (or the surface default) in place.
    """
    refs = refs_of(values)
    if not refs or store is None or not thread_id:
        return {}
    bodies: dict[str, Any] = {}
    for state_key, ref in refs.items():
        ref_str = ref.get("ref")
        if not isinstance(ref_str, str):
            continue
        body = await get_artifact_body(store, thread_id, ref_str)
        if body is not None:
            bodies[state_key] = body
    return bodies


# ── S3 field registry ────────────────────────────────────────────────────────
#
# The write seam (refify_updates, applied once at the graph node boundary in
# builder.py) moves these RuntimeState fields into the Artifact Store:
#
# - single-body fields (replace/merge dicts): the body goes out-of-line, the
#   state key is simply absent from the checkpoint while a ref files it.
# - ``viral_posts`` (append_list reducer): appends must concatenate onto the
#   stored body, so the seam loads the current artifact first.
# - ``user_viral_links`` (plain replace list).
# - ``content_versions`` / ``blogger_notes`` additionally get a small meta
#   summary kept in RuntimeState (versions_meta / blogger_notes_meta) because
#   routing predicates read their length/truthiness (info.md §一 摘要化).
# - ``trend_data`` (P1a-S4-1) likewise gets a dict meta (``trend_summary``):
#   the should_plan router reads actionable-topic truthiness off RuntimeState
#   only — routers never see the Artifact Store.
SINGLE_BODY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "copy_content",
        "visual_plan",
        "draft_content",
        "shooting_plan",
        "optimization_analysis",
        "analytics",
        "ripple_comparison",
        "trend_data",
        # P1a-S4-2: the remaining ripple vectors. Routers never read these
        # bodies (they read the small ripple_decision/ripple_pending fields),
        # so unlike trend_data no routing meta is needed — nodes re-read them
        # through the seam's resolve on the way in.
        "ripple_prediction",
        "ripple_pmf",
        # P1a-S4-3: brief_content (the raw_text payload dominates its size).
        # No routing meta: no router reads it — the /status DB label reads the
        # small brand/product fields, but only after an up-front resolve_state
        # (see routes/workflow.py), and every agent consumer hydrates through
        # the node seam on the way in.
        "brief_content",
    }
)
APPEND_LIST_FIELDS: Final[frozenset[str]] = frozenset({"viral_posts"})
REPLACE_LIST_FIELDS: Final[frozenset[str]] = frozenset({"user_viral_links"})
# Meta-backed fields: body out-of-line, {state_key: meta} kept in RuntimeState.
# Meta derivation lives in versions_meta_of / blogger_notes_meta_of /
# trend_summary_of and is pinned by ordering tests (free-draft lesson: any
# list surfaced to routers/UI must keep its full order and stable ids).
META_LIST_FIELDS: Final[frozenset[str]] = frozenset({"content_versions", "blogger_notes"})

REFABLE_FIELDS: Final[frozenset[str]] = (
    SINGLE_BODY_FIELDS | APPEND_LIST_FIELDS | REPLACE_LIST_FIELDS | META_LIST_FIELDS
)

# RuntimeState meta key per meta-backed field (the META_LIST_FIELDS members
# plus trend_data; declared in schema.py with a replace reducer so a new
# write fully supersedes the old summary).
META_KEY_OF: Final[dict[str, str]] = {
    "content_versions": "versions_meta",
    "blogger_notes": "blogger_notes_meta",
    "trend_data": "trend_summary",
}


def versions_meta_of(versions: list[Any]) -> list[dict[str, Any]]:
    """Small full-order summary of one content_versions write.

    Order is the write order of the body list — the same order the inline list
    used to have — and ``version_id`` is copied verbatim from each version, so
    routers reading length and any future id-based routing behave exactly as
    they did on the inline list (prd: 保全序与 id 稳定).
    """
    meta: list[dict[str, Any]] = []
    for version in versions:
        if not isinstance(version, dict):
            continue
        meta.append(
            {
                "version_id": version.get("version_id", ""),
                "title": version.get("title", ""),
                "style_suggestion": version.get("style_suggestion", ""),
                "predicted_score": version.get("predicted_score", 0.0),
            }
        )
    return meta


def blogger_notes_meta_of(notes: list[Any]) -> dict[str, Any]:
    """``{"count": N, "ids": [...]}`` summary of one blogger_notes write."""
    return {
        "count": len(notes),
        "ids": [note.get("note_id", "") for note in notes if isinstance(note, dict)],
    }


def trend_summary_of(trend_data: Any) -> dict[str, Any]:
    """Routing summary of one trend_data write (P1a-S4-1).

    ``has_topics`` mirrors the exact alias chain the should_plan router reads
    inline — ``hot_topics or trending_topics or topics`` — so a ref'd thread
    (router reads this meta) and a legacy thread (router reads inline) can
    never diverge on the same data. ``hot_topic_count`` is diagnostic only;
    the routers consume ``has_topics`` alone. The meta is derived from the
    update value itself (store-independent), so it stays correct on both the
    ref'd path and the inline best-effort fallback.
    """
    if not isinstance(trend_data, dict):
        return {"has_topics": False, "hot_topic_count": 0}
    topics = (
        trend_data.get("hot_topics")
        or trend_data.get("trending_topics")
        or trend_data.get("topics")
    )
    return {
        "has_topics": bool(topics),
        "hot_topic_count": len(topics) if isinstance(topics, (list, tuple)) else 0,
    }


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (dict, list, tuple, str)):
        return len(value) == 0
    return False


async def refify_updates(
    store: BaseStore | None,
    thread_id: str,
    updates: Mapping[str, Any],
    prev_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Move every refable field of a node's update dict into the Artifact Store.

    This is the write seam applied at the node boundary (builder.py): the node
    keeps producing plain inline updates, and this function rewrites them so
    the checkpoint only carries refs (``values["artifacts"]``) plus meta
    summaries, never the bodies.

    Semantics per refable key present in ``updates``:

    - non-empty value → body stored under ``artifact://<key>/latest``, the key
      removed from the update, and ``updates["artifacts"][key] = ref`` merged
      in. Append-list fields (``viral_posts``) first concatenate the currently
      stored body, preserving the append_list reducer semantics.
    - empty value (a deliberate clear, e.g. choice_gate resetting
      ``content_versions``) → written inline as-is, any previous ref is
      tombstoned with ``None`` (so :func:`resolve_state` stops injecting the
      stale body) and the meta summary is cleared too.
    - store failure → the field keeps its inline value (best-effort contract:
      never point at a body that does not exist) and the ref is tombstoned so
      the inline value wins everywhere. For append fields the stored body is
      folded into the inline value first, so a failed append loses nothing.
    - clearing a refable key that is not itself being written is NOT this
      function's job — only keys present in ``updates`` are touched.

    ``prev_values`` is the (already resolved) state the node ran against, used
    only for logging context; the authoritative previous body for appends is
    the stored artifact itself.
    """
    result = dict(updates)
    touched_refs: dict[str, Any] = {}
    for key in sorted(REFABLE_FIELDS):
        if key not in result:
            continue
        value = result[key]
        if _is_empty(value):
            # Deliberate clear: inline value wins, stale ref must not inject
            # the old body back on resolve.
            touched_refs[key] = None
            meta_key = META_KEY_OF.get(key)
            if meta_key:
                if key == "content_versions":
                    result[meta_key] = []
                elif key == "trend_data":
                    # A valid summary of the empty write — routers reading
                    # has_topics stay on the meta path and see False.
                    result[meta_key] = trend_summary_of({})
                else:
                    result[meta_key] = {"count": 0, "ids": []}
            continue

        body: Any = value
        if key in APPEND_LIST_FIELDS:
            # append_list semantics survive out-of-line: concatenate the
            # current stored body before storing the new full list.
            prev_ref = refs_of(prev_values).get(key, {}).get("ref")
            existing = await get_artifact_body(store, thread_id, prev_ref) if prev_ref else None
            if existing and isinstance(existing, list):
                body = list(existing) + list(value)

        ref = await put_artifact(store, thread_id, key, body, artifact_id=DEFAULT_ARTIFACT_ID)
        if ref is not None:
            result.pop(key)
            touched_refs[key] = dict(ref)
        else:
            # Keep the body inline; tombstone any stale ref so resolve_state
            # lets the inline value through.
            touched_refs[key] = None
        # Meta is derived from the update value itself (store-independent), so
        # routing predicates stay correct on both the ref'd and the
        # inline-fallback path.
        meta_key = META_KEY_OF.get(key)
        if meta_key:
            if key == "content_versions":
                result[meta_key] = versions_meta_of(list(value))
            elif key == "trend_data":
                result[meta_key] = trend_summary_of(value)
            else:
                result[meta_key] = blogger_notes_meta_of(list(value))

    if touched_refs:
        merged = dict(result.get(ARTIFACTS_KEY) or {})
        if not isinstance(merged, dict):
            merged = {}
        merged.update(touched_refs)
        result[ARTIFACTS_KEY] = merged
    return result


def artifact_seam(fn: Any) -> Any:
    """Wrap one graph node: resolve refs on the way in, refs-ify on the way out.

    Applied to every node callable in ``build_graph`` so the seam is uniform
    (agents and bare gates alike) and no node ever sees a ref'd field:

    - incoming state: refs resolved to bodies (legacy threads return the state
      unchanged, so pre-P1a runs behave exactly as before);
    - outgoing updates: refable fields moved into the Artifact Store via
      :func:`refify_updates` — the checkpoint keeps refs + meta, not bodies.

    ``store`` keeps its parameter name so LangGraph's config injection still
    recognizes the node signature; ``__name__``/``__qualname__``/``__doc__`` are
    copied so registry/tracing behavior is unchanged.
    """

    async def _seam(state: Mapping[str, Any], *, store: BaseStore) -> Any:
        from backend.state.events import resolve_thread_id

        thread_id = resolve_thread_id(state)
        resolved = await resolve_state(store, thread_id, state)
        result = await fn(resolved, store=store)
        if not isinstance(result, Mapping):
            return result
        return await refify_updates(store, thread_id, result, prev_values=resolved)

    name = getattr(fn, "__name__", None)
    if isinstance(name, str):
        _seam.__name__ = name
        qualname = getattr(fn, "__qualname__", None)
        if isinstance(qualname, str):
            _seam.__qualname__ = qualname
        doc = getattr(fn, "__doc__", None)
        if isinstance(doc, str):
            _seam.__doc__ = doc
    return _seam


async def resolve_state(
    store: BaseStore | None,
    thread_id: str,
    values: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """``values`` with every ref'd field replaced by its stored body.

    This is the single read seam that keeps the API contract unchanged (prd D4):
    the hydration layer and the routes still see a fully-inline state, so their
    payloads are identical whether or not the underlying thread is ref'd.

    Legacy/inline threads (the overwhelmingly common case today) get a shallow
    copy back with **no store round trip**, so the hot /status poll path pays
    nothing until a thread actually carries refs. Always returns a plain dict —
    callers may ``.get`` it and feed it straight to the hydration layer.
    """
    if values is None:
        return {}
    refs = refs_of(values)
    if not refs:
        return dict(values)
    bodies = await load_artifact_bodies(store, thread_id, values)
    resolved = dict(values)
    resolved.update(bodies)
    return resolved
