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

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from backend.agents.evaluator import EvaluatorAgent
from backend.agents.publisher import run_publish
from backend.api.errors import ValidationError
from backend.api.responses import ApiResponse, success
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.api.free")

router = APIRouter()

_evaluator = EvaluatorAgent()


class FreeDraft(BaseModel):
    """A free-mode content draft — title/body/hashtags/images, no workflow."""

    account_id: str = Field(default="default", description="账号 ID")
    title: str = Field(default="", description="标题")
    body: str = Field(default="", description="正文")
    hashtags: list[str] = Field(default_factory=list, description="话题标签")
    image_paths: list[str] = Field(default_factory=list, description="图片路径")
    niche: str = Field(default="母婴", description="账号 niche（评估用）")
    content_angle: str = Field(default="", description="内容角度（评估用）")
    target_audience: str = Field(default="", description="目标受众（评估用）")


class FreeDraftRef(BaseModel):
    """Reference to a stored free draft."""

    account_id: str = Field(default="default", description="账号 ID")
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
async def create_draft(draft: FreeDraft, request: Request) -> ApiResponse[Any]:
    """Create (or overwrite) a free-mode draft. Returns the draft_id.

    The agent calls this with conversational content it produced, then feeds
    the draft_id to /evaluate and /publish.
    """
    account_id = draft.account_id or "default"
    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot save draft")

    draft_id = str(uuid.uuid4())
    record = draft.model_dump()
    record["draft_id"] = draft_id
    now = _now_iso()
    record["created_at"] = now
    record["updated_at"] = now
    record["last_evaluation"] = None
    record["published"] = False
    await store.aput(_draft_ns(account_id), key=draft_id, value=record)
    logger.info("free draft created: account=%s draft=%s", account_id, draft_id)
    return success(data={"draft_id": draft_id, "draft": record})


@router.post("/evaluate")
async def evaluate_draft(ref: FreeDraftRef, request: Request) -> ApiResponse[Any]:
    """Evaluate a free draft via the RQGM agent-as-a-judge panel (thread-less).

    Loads the draft from BaseStore, synthesizes a minimal state, and calls
    EvaluatorAgent.execute. The result is NOT written to a checkpoint (free
    mode has no thread); it is returned to the agent directly.
    """
    account_id = ref.account_id or "default"
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
    # to the agent; only the {overall_score, decision} pair is written back.
    if store is not None:
        draft["last_evaluation"] = {
            "overall_score": evaluation.get("overall_score"),
            "decision": evaluation.get("decision"),
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
async def publish_draft(ref: FreeDraftRef, request: Request) -> ApiResponse[Any]:
    """Publish a free draft to Xiaohongshu (thread-less).

    Loads the draft, synthesizes a minimal state, and calls run_publish — the
    same real-publish path PublisherAgent uses (CDP resolution, account
    validation, XHSClient.publish_post, ContentHistory recording). Publish
    results are recorded to account memory by run_publish itself.
    """
    account_id = ref.account_id or "default"
    draft = await _load_draft(request, account_id, ref.draft_id)

    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot publish")
    pub_state = _build_publish_state(draft)
    result = await run_publish(pub_state, store)
    publish_result = result.get("publish_result") or {}
    pub_status = publish_result.get("status", "unknown")

    # On a successful publish, mark the draft as published + refresh updated_at.
    if pub_status in _PUBLISH_SUCCESS_STATUSES:
        draft["published"] = True
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


@router.get("/drafts/{account_id}")
async def list_drafts(account_id: str, request: Request) -> ApiResponse[Any]:
    """List free-mode drafts for an account (thread-less).

    Returns a summary list (draft_id + title + hashtags) — no full body, to
    keep payloads small. Uses BaseStore.asearch with an empty query (returns
    all items in the namespace). asearch is on BaseStore; alist is NOT (only
    on some concrete stores), so asearch is the correct portable call.
    Wrapped in try/except — degrades to empty list if the store lacks a
    semantic index.
    """
    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot list drafts")

    drafts: list[dict[str, Any]] = []
    try:
        items = await store.asearch(_draft_ns(account_id), query="", limit=100)
        for item in items:
            value = item.value
            if not isinstance(value, dict):
                continue
            last_eval = value.get("last_evaluation")
            drafts.append(
                {
                    "draft_id": item.key,
                    "title": value.get("title", ""),
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
    return success(data={"account_id": account_id, "drafts": drafts})


@router.patch("/draft/{draft_id}")
async def update_draft(
    draft_id: str,
    update: FreeDraftUpdate,
    request: Request,
    account_id: str = Query(..., description="账号 ID"),
) -> ApiResponse[Any]:
    """Update a free-mode draft (thread-less). Overwrites specified fields,
    keeps the draft_id unchanged.
    """
    existing = await _load_draft(request, account_id, draft_id)
    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot update draft")

    merged = dict(existing)
    for field in (
        "title",
        "body",
        "hashtags",
        "image_paths",
        "niche",
        "content_angle",
        "target_audience",
    ):
        val = getattr(update, field)
        if val is not None:
            merged[field] = val
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
) -> ApiResponse[Any]:
    """Delete a free-mode draft (thread-less). Idempotent — deleting a
    non-existent draft returns success.
    """
    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    if store is None:
        raise ValidationError("store", "Memory store unavailable; cannot delete draft")

    await store.adelete(_draft_ns(account_id), key=draft_id)
    logger.info("free draft deleted: account=%s draft=%s", account_id, draft_id)
    return success(data={"draft_id": draft_id, "deleted": True})
