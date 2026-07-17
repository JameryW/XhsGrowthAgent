"""Public UX telemetry receiver and authenticated aggregate endpoint."""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.api.deps import get_current_user
from backend.api.responses import success
from backend.db.pool import is_pool_ready
from backend.db.public_telemetry import record_event, summarize_events

logger = logging.getLogger("xhs_growth.api.public_telemetry")
router = APIRouter()

_EVENT_NAMES = {
    "showcase_view",
    "showcase_cases_loaded",
    "showcase_first_case_visible",
    "showcase_cases_error",
    "showcase_filters_clear",
    "showcase_case_open",
    "showcase_filter_change",
    "showcase_workflow_open",
    "showcase_detail_retry",
    "showcase_primary_cta_click",
    "replay_view",
    "replay_first_result_visible",
    "replay_select_to_render",
    "replay_step_select",
    "replay_view_mode_change",
    "replay_step_link_copy",
    "replay_case_link_copy",
    "replay_share_error",
    "replay_checkpoint_select",
    "replay_phase_select",
    "replay_checkpoint_link_copy",
    "replay_back",
    "replay_primary_cta_click",
    "replay_load_error",
    "replay_load_more_error",
    # PR-1: public-page conversion funnel additions (showcase/replay).
    "showcase_case_impression",
    "showcase_featured_open",
    "showcase_cta_click",
    "replay_step_navigate",
    "replay_result_expand",
    "replay_result_copy",
    "replay_share",
    "replay_cta_click",
}

_CATEGORY_ALLOWLISTS = {
    "source": {"showcase", "replay", "direct"},
    "status": {"all", "completed", "in_progress", "attention"},
    "mode": {"all", "trend", "brief", "key"},
    "phase": {
        "scouting",
        "planning",
        "briefing",
        "creating",
        "reviewing",
        "publishing",
        "analyzing",
        "completed",
    },
    "error_type": {
        "public_cases",
        "manifest",
        "not_found",
        "detail",
        "share",
    },
    "view": {"key", "all"},
    "auth_state": {"authenticated", "guest"},
    "position": {"nav", "hero", "empty", "aside", "detail", "footer"},
    "method": {"click", "keys", "prev", "next"},
}

_RATE_LIMIT = 120
_RATE_WINDOW_SECONDS = 60.0
_rate_lock = threading.Lock()
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


class PublicTelemetryEvent(BaseModel):
    """Bounded categorical event payload; unknown fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    event: str = Field(min_length=1, max_length=64)
    event_version: int = Field(default=1, ge=1, le=10)
    viewport: str = Field(default="desktop", min_length=1, max_length=16)
    source: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)
    mode: str | None = Field(default=None, max_length=32)
    phase: str | None = Field(default=None, max_length=32)
    error_type: str | None = Field(default=None, max_length=32)
    view: str | None = Field(default=None, max_length=16)
    step: int | None = Field(default=None, ge=0, le=100_000)
    count: int | None = Field(default=None, ge=0, le=10_000)
    restored: bool | None = None
    cached: bool | None = None
    has_steps: bool | None = None
    has_result: bool | None = None
    authenticated: bool | None = None
    has_public_id: bool | None = None
    has_step: bool | None = None
    duration_ms: int | None = Field(default=None, ge=0, le=120_000)
    auth_state: str | None = Field(default=None, max_length=16)
    position: str | None = Field(default=None, max_length=16)
    method: str | None = Field(default=None, max_length=16)


def _client_key(request: Request) -> str:
    client = request.client
    return client.host if client and client.host else "unknown"


def _within_rate_limit(key: str) -> bool:
    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets[key]
        while bucket and now - bucket[0] >= _RATE_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT:
            return False
        bucket.append(now)
        if len(_rate_buckets) > 2048:
            expired = [name for name, values in _rate_buckets.items() if not values]
            for name in expired[:512]:
                _rate_buckets.pop(name, None)
        return True


def _normalise_event(payload: PublicTelemetryEvent) -> dict[str, Any] | None:
    if payload.event not in _EVENT_NAMES or payload.viewport not in {"mobile", "desktop"}:
        return None
    data = payload.model_dump(exclude_none=True)
    for field, allowed in _CATEGORY_ALLOWLISTS.items():
        value = data.get(field)
        if value is not None and value not in allowed:
            data.pop(field, None)
    return data


@router.post("/telemetry", status_code=204, response_model=None)
async def receive_public_telemetry(
    payload: PublicTelemetryEvent,
    request: Request,
) -> Response:
    """Accept one privacy-safe event without requiring a visitor login."""

    data = _normalise_event(payload)
    if data is None or not _within_rate_limit(_client_key(request)):
        # Beacon callers cannot act on a response. A no-content response also
        # avoids turning telemetry failures into user-facing errors.
        return Response(status_code=204)
    if is_pool_ready():
        try:
            await record_event(data)
        except Exception:
            # UX telemetry is best-effort and must never affect public pages.
            logger.warning("public UX telemetry write failed for %s", payload.event)
    return Response(status_code=204)


@router.get("/admin/telemetry/summary")
async def get_public_telemetry_summary(
    days: int = Query(7, ge=1, le=30),
    event: str | None = Query(None, max_length=64),
    _: dict[str, Any] = Depends(get_current_user),
) -> Any:
    """Return aggregate event/timing rows for the operator dashboard."""

    event_name = event if event in _EVENT_NAMES else None
    try:
        rows = await summarize_events(days=days, event_name=event_name)
    except Exception:
        logger.warning("public UX telemetry summary failed")
        rows = []
    return success(data={"days": days, "events": rows})
