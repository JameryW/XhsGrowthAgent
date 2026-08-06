"""Free creation API routes — thread-less standalone creation/evaluation/publish.

The free creation mode (`/tui?mode=free`) lets the omp agent drive creation
conversationally without a LangGraph workflow thread. These routes back the
`xhs_free_draft_create` / `xhs_free_evaluate` / `xhs_free_publish` omp host
tools (see backend/services/omp_bridge.py).

Persistence: free drafts live in the BaseStore under
`("accounts", account_id, "free_drafts")`, keyed by draft_id (uuid). They do
NOT enter the LangGraph checkpoint and never participate in workflow
resume/retry — free mode is fully isolated from the fixed workflow.

Reuse: evaluation delegates to `EvaluatorAgent.execute` (fed a synthesized
minimal state), publish delegates to `run_publish` (the same real-publish path
the PublisherAgent uses). Neither primitive is thread-bound; only the
checkpoint storage was.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    # Annotation-only; deferring state.schema keeps langgraph.graph.message
    # (~0.3s) off the app cold-start import chain.
    from backend.state.schema import XHSGrowthState

from backend.agents.evaluator import EvaluatorAgent
from backend.agents.publisher import run_publish
from backend.api.account_scope import (  # noqa: F401
    require_owned_account,  # tests patch this name here
    resolve_required_account_id,
)
from backend.api.deps import get_current_user
from backend.api.errors import ValidationError
from backend.api.responses import ApiResponse, success

logger = logging.getLogger("xhs_growth.api.free")

router = APIRouter()

_evaluator = EvaluatorAgent()


class FreeDraft(BaseModel):
    """A free-mode content draft — title/body/hashtags/images, no workflow."""

    account_id: str = Field(default="", description="账号 ID（必填，禁止 default）")
    title: str = Field(default="", description="标题")
    body: str = Field(default="", description="正文")
    hashtags: list[str] = Field(default_factory=list, description="话题标签")
    image_paths: list[str] = Field(default_factory=list, description="图片路径")
    niche: str = Field(
        default="",
        description="垂类赛道；空/省略=根据历史笔记自动推断，非空=手动指定",
    )
    content_angle: str = Field(default="", description="内容角度（评估用）")
    target_audience: str = Field(default="", description="目标受众（评估用）")

    @field_validator("niche", mode="before")
    @classmethod
    def _niche_normalize(cls, v: Any) -> str:
        """Empty/None/whitespace niche → "" (auto-infer), never silent 母婴.

        Auto-infer runs in create_draft via resolve_account_niche. Cold-start
        default 母婴 is applied only after resolve when no history/manual.
        """
        if v is None:
            return ""
        if isinstance(v, str):
            return v.strip()
        return str(v).strip()


class FreeDraftRef(BaseModel):
    """Reference to a stored free draft."""

    account_id: str = Field(default="", description="账号 ID（必填）")
    draft_id: str = Field(description="草稿 ID")


class FreeDraftUpdate(BaseModel):
    """Partial update for a free draft — all fields optional (PATCH semantics)."""

    title: str | None = None
    body: str | None = None
    hashtags: list[str] | None = None
    image_paths: list[str] | None = None
    niche: str | None = None
    content_angle: str | None = None
    target_audience: str | None = None

    @field_validator("niche", mode="before")
    @classmethod
    def _niche_normalize(cls, v: Any) -> str:
        """PATCH niche: None/empty/whitespace → "" (re-resolve auto on update).

        Omitted field (exclude_unset) leaves existing niche unchanged.
        """
        if v is None:
            return ""
        if isinstance(v, str):
            return v.strip()
        return str(v).strip()


def _draft_ns(account_id: str) -> tuple[str, str, str]:
    """BaseStore namespace for a free draft."""
    return ("accounts", account_id, "free_drafts")


def _now_iso() -> str:
    """Current UTC time as an ISO 8601 string (for draft timestamps)."""
    return datetime.now(UTC).isoformat()


# Publish status values that count as a successful publish. Real publishes
# return "published" (services/xhs_publisher.py), mock dry-runs return
# "mock_published" (agents/publisher.py); anything else is a failure.
_PUBLISH_SUCCESS_STATUSES = frozenset({"published", "mock_published"})


def _to_copy_content(draft: dict[str, Any]) -> dict[str, Any]:
    """Map a free draft to the copy_content shape EvaluatorAgent/publisher read."""
    return {
        "selected_title": draft.get("title", ""),
        "body_text": draft.get("body", ""),
        "hashtags": draft.get("hashtags", []),
    }


def _build_eval_state(draft: dict[str, Any]) -> XHSGrowthState:
    """Synthesize a minimal XHSGrowthState for EvaluatorAgent.execute.

    EvaluatorAgent reads copy_content / content_plan / niche / account_id —
    only the content fields matter; the rest default. No thread involved.
    """
    state: XHSGrowthState = cast(
        "XHSGrowthState",
        {
            "account_id": draft.get("account_id", "default"),
            "niche": draft.get("niche", "母婴"),
            "copy_content": _to_copy_content(draft),
            "content_plan": {
                "selected_topic": draft.get("title", ""),
                "content_angle": draft.get("content_angle", ""),
                "target_audience": draft.get("target_audience", ""),
            },
        },
    )
    return state


def _build_publish_state(draft: dict[str, Any]) -> XHSGrowthState:
    """Synthesize a minimal XHSGrowthState for run_publish.

    run_publish reads copy_content / content_plan / visual_plan / account_id /
    publish_options.account_id. We thread account_id through publish_options so
    run_publish's per-account CDP resolution kicks in.
    """
    account_id = draft.get("account_id", "default")
    state: XHSGrowthState = cast(
        "XHSGrowthState",
        {
            "account_id": account_id,
            "copy_content": _to_copy_content(draft),
            "content_plan": {
                "selected_topic": draft.get("title", ""),
                "content_angle": draft.get("content_angle", ""),
            },
            "visual_plan": {
                "image_paths": draft.get("image_paths", []),
            },
            "publish_options": {"account_id": account_id},
        },
    )
    return state


async def _load_draft(request: Request, account_id: str, draft_id: str) -> dict[str, Any]:
    """Fetch a free draft from BaseStore; raise ValidationError if missing."""
    if not draft_id or not draft_id.strip():
        raise ValidationError("draft_id", "draft_id cannot be empty")
    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot load draft")
    item = await store.aget(_draft_ns(account_id), key=draft_id)
    if item is None:
        raise ValidationError(
            "draft_id", f"Free draft {draft_id} not found for account {account_id}"
        )
    value = item.value
    if not isinstance(value, dict):
        raise ValidationError("draft_id", f"Free draft {draft_id} is corrupt")
    return value


@router.post("/draft")
async def create_draft(
    draft: FreeDraft,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Create (or overwrite) a free-mode draft. Returns the draft_id.

    The agent calls this with conversational content it produced, then feeds
    the draft_id to /evaluate and /publish.
    """
    account_id = await resolve_required_account_id(str(user["id"]), draft.account_id)
    draft.account_id = account_id
    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot save draft")

    draft_id = str(uuid.uuid4())
    record = draft.model_dump()
    # Niche resolve: only treat client-provided *non-empty* niche as manual.
    # Omitted / "" / null → auto-infer from imported notes (not default 母婴).
    from backend.services.niche_resolver import resolve_account_niche

    client_set_niche = "niche" in draft.model_fields_set
    raw_niche = (draft.niche or "").strip()
    manual_niche = raw_niche if client_set_niche and raw_niche else ""
    niche_res = await resolve_account_niche(
        account_id,
        manual_niche=manual_niche,
        cold_start_default="母婴",
        # Never persist cold_start default as "manual". Only bind when the
        # client deliberately set niche or we inferred from history.
        persist=False,
    )
    if niche_res.source in ("manual", "inferred") and niche_res.niche:
        try:
            from backend.db.accounts import update_account as db_update_account

            await db_update_account(
                account_id,
                niche=niche_res.niche,
                niche_source=niche_res.source,
            )
        except Exception as e:
            logger.debug("persist free-draft niche skipped: %s", e)
    record["niche"] = niche_res.niche or "母婴"
    record["niche_resolution"] = niche_res.to_dict()
    record["draft_id"] = draft_id
    now = _now_iso()
    record["created_at"] = now
    record["updated_at"] = now
    record["last_evaluation"] = None
    record["published"] = False
    await store.aput(_draft_ns(account_id), key=draft_id, value=record)
    logger.info("free draft created: account=%s draft=%s", account_id, draft_id)

    # Attach free-mode creative suggestions + durable style DNA context
    # (shared recall surface with trend/brief). Never fail draft create on this.
    creative_suggestions: list[dict[str, Any]] = []
    creative_context = ""
    try:
        from backend.services.creator_stats.suggestions import get_suggestions_for_mode

        sugs = await get_suggestions_for_mode(account_id, "free", store=store)
        creative_suggestions = [s.to_dict() for s in sugs]
    except Exception as e:
        logger.debug("free draft creative suggestions skipped: %s", e)
    try:
        from backend.memory.creative import CreativeMemory

        cm = CreativeMemory(account_id, store=store)
        niche = str(record.get("niche") or "")
        styles, plays, materials = await asyncio.gather(
            cm.recall_style(query=f"free draft {niche}".strip()),
            cm.recall_plays(condition="free creation", niche=niche),
            cm.recall_materials(category="文案片段", tags=["高转化", "爆款标题", "开头"]),
        )
        creative_context = cm.build_creative_context(styles, plays, materials)
    except Exception as e:
        logger.debug("free draft creative_context skipped: %s", e)

    return success(
        data={
            "draft_id": draft_id,
            "draft": record,
            "niche_resolution": niche_res.to_dict(),
            "creative_suggestions": creative_suggestions,
            "creative_suggestions_count": len(creative_suggestions),
            "creative_context": creative_context,
        }
    )


@router.post("/evaluate")
async def evaluate_draft(
    ref: FreeDraftRef,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Evaluate a free draft via the RQGM agent-as-a-judge panel (thread-less).

    Loads the draft from BaseStore, synthesizes a minimal state, and calls
    EvaluatorAgent.execute. The result is NOT written to a checkpoint (free
    mode has no thread); it is returned to the agent directly.
    """
    account_id = await resolve_required_account_id(str(user["id"]), ref.account_id)
    draft = await _load_draft(request, account_id, ref.draft_id)

    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    eval_state = _build_eval_state(draft)
    # store may be None on compiled graphs without a store attached; EvaluatorAgent
    # tolerates None (skips memory recall), same as evaluation.py:run_evaluation.
    result = await _evaluator(eval_state, store=store)  # type: ignore[arg-type]
    evaluation = result.get("evaluation_result") or {}

    # Persist the last evaluation summary back onto the draft so list_drafts can
    # surface the score + decision. The full evaluation_result is still returned
    # to the agent; the {overall_score, decision, revision_hints} triple + the
    # degradation marker are written back. `degraded` (truthy) marks a
    # pass-through fallback (LLM timeout) — the 100/approved is fake, not a real
    # score; `summary` carries the cause so /draft + /drafts + the agent render
    # can surface it instead of presenting a misleading "100 approved".
    if store is not None:
        draft["last_evaluation"] = {
            "overall_score": evaluation.get("overall_score"),
            "decision": evaluation.get("decision"),
            "revision_hints": evaluation.get("revision_hints") or [],
            "degraded": evaluation.get("degraded", False),
            "summary": evaluation.get("summary"),
        }
        draft["updated_at"] = _now_iso()
        await store.aput(_draft_ns(account_id), key=ref.draft_id, value=draft)

    logger.info("free draft evaluated: account=%s draft=%s", account_id, ref.draft_id)
    return success(
        data={
            "draft_id": ref.draft_id,
            "account_id": account_id,
            "evaluation_result": evaluation,
        }
    )


@router.post("/publish")
async def publish_draft(
    ref: FreeDraftRef,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Publish a free draft to Xiaohongshu (thread-less).

    Loads the draft, synthesizes a minimal state, and calls run_publish — the
    same real-publish path PublisherAgent uses (CDP resolution, account
    validation, XHSClient.publish_post, ContentHistory recording). Publish
    results are recorded to account memory by run_publish itself.
    """
    account_id = await resolve_required_account_id(str(user["id"]), ref.account_id)
    draft = await _load_draft(request, account_id, ref.draft_id)

    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot publish")
    pub_state = _build_publish_state(draft)
    result = await run_publish(pub_state, store)
    publish_result = result.get("publish_result") or {}
    pub_status = publish_result.get("status", "unknown")

    # Persist the latest publish outcome on every attempt (success + failure)
    # so /draft <id> and the agent list render can surface a failed publish's
    # cause after the turn ends (#239 only surfaces it for the single tool call).
    draft["last_publish"] = {
        "status": pub_status,
        "error": publish_result.get("error"),
        "error_type": publish_result.get("error_type"),
        "at": _now_iso(),
    }
    # On a successful publish, mark the draft as published, persist the post_id
    # + post_url (so /analytics can fetch engagement later). Failures (failed /
    # auth_expired / unknown) do NOT flip published — they only record the
    # attempt via last_publish above. A publish attempt always refreshes
    # updated_at (it is a meaningful update to the record).
    if pub_status in _PUBLISH_SUCCESS_STATUSES:
        draft["published"] = True
        draft["post_id"] = publish_result.get("post_id", "")
        draft["post_url"] = publish_result.get("post_url", "")
    draft["updated_at"] = _now_iso()
    await store.aput(_draft_ns(account_id), key=ref.draft_id, value=draft)

    logger.info(
        "free draft published: account=%s draft=%s status=%s",
        account_id,
        ref.draft_id,
        pub_status,
    )
    return success(
        data={
            "draft_id": ref.draft_id,
            "account_id": account_id,
            "publish_result": publish_result,
        }
    )


_DRAFT_STATUS_FILTERS = {
    "all",
    "published",
    "unpublished",
    "publish_failed",
    "evaluated",
    "unevaluated",
}


def _draft_matches_status(draft: dict[str, Any], status: str) -> bool:
    """Post-filter predicate for the `status` query param.

    Runs over the capped asearch page (no extra store call). `evaluated` is
    "has a last_evaluation record", not a field-value match — so we can't
    push it into asearch's `filter=` dict; post-filter is the portable call.
    `publish_failed` matches drafts whose last publish attempt failed
    (`last_publish.status` present and not a success status).
    """
    if status == "all":
        return True
    if status == "published":
        return bool(draft.get("published"))
    if status == "unpublished":
        return not draft.get("published", False)
    if status == "publish_failed":
        lp = draft.get("last_publish") or {}
        lp_status = lp.get("status") or ""
        return bool(lp_status) and lp_status not in _PUBLISH_SUCCESS_STATUSES
    if status == "evaluated":
        return draft.get("last_evaluation") is not None
    if status == "unevaluated":
        return draft.get("last_evaluation") is None
    return True  # unreachable — status is whitelisted upstream


@router.get("/drafts/{account_id}")
async def list_drafts(
    account_id: str,
    request: Request,
    status: str = Query(
        default="all",
        description="过滤草稿: all|published|unpublished|publish_failed|evaluated|unevaluated",
    ),
    q: str = Query(default="", description="标题子串 (case-insensitive contains)"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """List free-mode drafts for an owned account (thread-less).

    Returns a summary list (draft_id + title + hashtags) — no full body, to
    keep payloads small. Uses BaseStore.asearch with an empty query (returns
    all items in the namespace). asearch is on BaseStore; alist is NOT (only
    on some concrete stores), so asearch is the correct portable call.
    Wrapped in try/except — degrades to empty list if the store lacks a
    semantic index.

    Optional `status` (publish/eval state) and `q` (title substring) are
    post-filtered over the capped asearch page — no extra store call, no
    dependency on BaseStore's `filter=` exact-match semantics (which can't
    express "has last_evaluation" or substring match). `count` reflects the
    filtered set; `truncated` reflects the pre-filter 100-cap (whether the
    store likely holds more than 100 drafts total), independent of filter.
    """
    account_id = await resolve_required_account_id(str(user["id"]), account_id)
    if status not in _DRAFT_STATUS_FILTERS:
        raise ValidationError(
            "status",
            f"invalid status filter: {status!r} — expected one of {sorted(_DRAFT_STATUS_FILTERS)}",
        )
    q_norm = q.strip().lower()

    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot list drafts")

    drafts: list[dict[str, Any]] = []
    hit_limit = False
    try:
        items = await store.asearch(_draft_ns(account_id), query="", limit=100)
        # asearch limit is page size, not total — if it returns exactly limit
        # items, more likely exist (heuristic; no portable total-count on
        # BaseStore). Surfaced as `truncated` so the list isn't silently capped.
        hit_limit = len(items) >= 100
        for item in items:
            value = item.value
            if not isinstance(value, dict):
                continue
            last_eval = value.get("last_evaluation")
            title = value.get("title", "")
            # post-filter: status (publish/eval state) + q (title substring)
            if status != "all" and not _draft_matches_status(value, status):
                continue
            if q_norm and q_norm not in str(title).lower():
                continue
            drafts.append(
                {
                    "draft_id": item.key,
                    "title": title,
                    "hashtags": value.get("hashtags", []),
                    "created_at": value.get("created_at"),
                    "updated_at": value.get("updated_at"),
                    "last_evaluation": last_eval,
                    "published": value.get("published", False),
                }
            )
    except Exception:
        logger.warning("store.alist failed for account %s; returning empty list", account_id)
    # Sort newest-first by updated_at (ISO strings sort lexicographically =
    # chronologically). Drafts without updated_at (old records) sort last.
    drafts.sort(key=lambda d: d.get("updated_at") or "", reverse=True)
    if hit_limit:
        logger.info(
            "free drafts list hit 100-cap for account %s — older drafts hidden "
            "(status filter applied: %s, q: %r)",
            account_id,
            status,
            q_norm,
        )
    return success(
        data={
            "account_id": account_id,
            "drafts": drafts,
            "count": len(drafts),
            "truncated": hit_limit,
            "status": status,
            "q": q_norm,
        }
    )


@router.get("/draft/{draft_id}")
async def get_draft(
    draft_id: str,
    request: Request,
    account_id: str = Query(default="", description="账号 ID"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Fetch a single free draft's full record (thread-less).

    Thin wrapper over `_load_draft` — returns the complete draft record
    (title, body, hashtags, image_paths, niche/angle/audience + any
    server-set metadata like created_at/updated_at/last_evaluation/published).
    Raises ValidationError → 400 if the draft is missing or corrupt.
    """
    account_id = await resolve_required_account_id(str(user["id"]), account_id)
    draft = await _load_draft(request, account_id, draft_id)
    return success(data={"draft_id": draft_id, "draft": draft})


@router.patch("/draft/{draft_id}")
async def update_draft(
    draft_id: str,
    update: FreeDraftUpdate,
    request: Request,
    account_id: str = Query(..., description="账号 ID"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Update a free-mode draft (thread-less). Overwrites specified fields,
    keeps the draft_id unchanged.
    """
    account_id = await resolve_required_account_id(str(user["id"]), account_id)
    existing = await _load_draft(request, account_id, draft_id)
    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot update draft")

    merged = dict(existing)
    # exclude_unset=True: only fields the client explicitly provided in the
    # PATCH body. Omitted niche preserves existing; empty/null niche re-infers.
    provided = update.model_dump(exclude_unset=True)
    for field, val in provided.items():
        merged[field] = val
    if "niche" in provided:
        from backend.services.niche_resolver import resolve_account_niche

        raw = (provided.get("niche") or "").strip()
        manual = raw  # non-empty = manual; empty = auto
        niche_res = await resolve_account_niche(
            account_id,
            manual_niche=manual,
            cold_start_default="母婴",
            persist=False,
        )
        if niche_res.source in ("manual", "inferred") and niche_res.niche:
            try:
                from backend.db.accounts import update_account as db_update_account

                await db_update_account(
                    account_id,
                    niche=niche_res.niche,
                    niche_source=niche_res.source,
                )
            except Exception as e:
                logger.debug("persist free-draft niche on patch skipped: %s", e)
        merged["niche"] = niche_res.niche or "母婴"
        merged["niche_resolution"] = niche_res.to_dict()
    merged["draft_id"] = draft_id
    merged["updated_at"] = _now_iso()
    await store.aput(_draft_ns(account_id), key=draft_id, value=merged)
    logger.info("free draft updated: account=%s draft=%s", account_id, draft_id)
    return success(data={"draft_id": draft_id, "draft": merged})


@router.delete("/draft/{draft_id}")
async def delete_draft(
    draft_id: str,
    request: Request,
    account_id: str = Query(..., description="账号 ID"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Delete a free-mode draft (thread-less). Idempotent — deleting a
    non-existent draft returns success.
    """
    account_id = await resolve_required_account_id(str(user["id"]), account_id)
    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot delete draft")

    await store.adelete(_draft_ns(account_id), key=draft_id)
    logger.info("free draft deleted: account=%s draft=%s", account_id, draft_id)
    return success(data={"draft_id": draft_id, "deleted": True})


async def _resolve_free_cdp_endpoint(account_id: str) -> str:
    """Resolve the CDP endpoint for a free-mode account (thread-less).

    Mirrors run_publish's per-account CDP resolution: start from the global
    _resolve_cdp_endpoint(settings), then override with the per-account
    endpoint if one is bound. Returns "" when no endpoint is available.
    """
    from backend.agents.publisher import _resolve_cdp_endpoint
    from backend.config.settings import Settings
    from backend.db.accounts import get_account_cdp_endpoint

    settings = Settings()
    cdp_endpoint = _resolve_cdp_endpoint(settings)
    per_account = await get_account_cdp_endpoint(account_id)
    if per_account:
        cdp_endpoint = per_account
    return cdp_endpoint


@router.get("/analytics/{draft_id}")
async def get_analytics(
    draft_id: str,
    request: Request,
    account_id: str = Query(default="default", description="账号 ID"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Fetch post-publish engagement analytics for a free draft (thread-less).

    Loads the draft, reads its persisted post_id, and calls
    XHSClient.get_post_analytics(post_id) — the same thread-agnostic method
    the fixed workflow's analyst uses. Returns views/likes/collects/comments/
    shares/engagement_rate. Raises ValidationError → 400 if the draft hasn't
    been published (no post_id) or no CDP endpoint is available.
    """
    account_id = await resolve_required_account_id(str(user["id"]), account_id)
    draft = await _load_draft(request, account_id, draft_id)
    post_id = draft.get("post_id", "")
    if not post_id:
        raise ValidationError(
            "post_id",
            "draft not published / no post_id — publish the draft first",
        )
    # Mock-published (dry-run) drafts carry a "mock_*" post_id — no real XHS
    # note exists, so analytics can't be fetched. Fail fast with a clear error
    # rather than returning a zero-engagement snapshot.
    if post_id.startswith("mock_"):
        raise ValidationError(
            "post_id",
            "draft was mock-published (dry-run) — no real post_id, "
            "analytics unavailable. Re-publish without dry-run for real data.",
        )

    cdp_endpoint = await _resolve_free_cdp_endpoint(account_id)
    if not cdp_endpoint:
        raise ValidationError(
            "cdp_endpoint",
            "no CDP endpoint available for this account — "
            "start the account browser and scan-login first",
        )

    from backend.services.xhs_client import XHSClient

    client = XHSClient(
        cookie="",
        user_id="",
        use_browser=True,
        headless=False,
        cdp_endpoint=cdp_endpoint,
    )
    try:
        analytics_obj = await client.get_post_analytics(post_id)
        # XHSAnalytics is a dataclass — convert to a plain dict for the API
        # response (JSON-serializable, no dataclass schema on the wire).
        from dataclasses import asdict

        analytics = asdict(analytics_obj)
    except Exception as e:
        logger.warning(
            "free analytics fetch failed: account=%s draft=%s err=%s", account_id, draft_id, e
        )
        raise ValidationError("analytics", f"failed to fetch analytics: {e}") from e
    finally:
        await client.close()

    logger.info(
        "free analytics fetched: account=%s draft=%s post=%s", account_id, draft_id, post_id
    )
    return success(
        data={
            "draft_id": draft_id,
            "post_id": post_id,
            "analytics": analytics,
        }
    )


@router.get("/suggestions/{account_id}")
async def free_mode_suggestions(
    account_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Free-mode creative suggestions from imported creator-center stats.

    Shares the same recall/advice surface as trend/brief modes.
    """
    from backend.services.creator_stats.suggestions import get_suggestions_for_mode

    account_id = await resolve_required_account_id(str(user["id"]), account_id)
    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None) if graph is not None else None
    suggestions = await get_suggestions_for_mode(account_id, "free", store=store)
    return success(
        data={
            "account_id": account_id,
            "mode": "free",
            "suggestions": [s.to_dict() for s in suggestions],
            "count": len(suggestions),
            "cold_start": bool(suggestions)
            and all(s.category == "cold_start" for s in suggestions),
        }
    )
