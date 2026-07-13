"""omp RPC bridge — manages omp --mode rpc subprocess(es) for Web TUI agent interaction.

Architecture:
  Python backend spawns ``omp --mode rpc`` as child processes.
  Communication via NDJSON on stdin/stdout.
  Translates between high-level frontend protocol and low-level omp RPC commands.

Multi-session:
  ``OmpSession`` represents one omp subprocess (one user/session).
  ``OmpBridgeManager`` is the singleton that manages multiple OmpSessions,
  keyed by session_id. Sessions start on-demand and stop after idle timeout.

Host tools:
  Known XHS tools are auto-executed by the backend via internal API calls.
  The fixed workflow start tool is intentionally not exposed to OMP free
  orchestration; users choose that path from the Simple Mode UI.
  Unknown host tools are forwarded to the frontend.

Extension UI:
  omp can request UI interaction (select, confirm, input, editor).
  These are translated to EXTENSION_UI_REQUEST events pushed to frontend,
  and the frontend's response is forwarded back to omp stdin.

Lifecycle:
  - OmpBridgeManager started in FastAPI lifespan (startup)
  - Sessions start on-demand (first WebSocket connection)
  - Sessions stop after idle timeout (default 5 min) or on manager shutdown
  - Graceful shutdown: SIGTERM + timeout -> SIGKILL
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger("xhs_growth.omp_bridge")

# ── High-level protocol types (frontend <-> backend) ────────────────────────


class ClientMessageType(StrEnum):
    """Messages from frontend to backend."""

    SEND_MESSAGE = "send_message"
    GET_STATUS = "get_status"
    NEW_SESSION = "new_session"
    ABORT = "abort"
    HOST_TOOL_RESULT = "host_tool_result"
    EXTENSION_UI_RESPONSE = "extension_ui_response"


class ServerEventType(StrEnum):
    """Events from backend to frontend."""

    READY = "ready"
    AGENT_MESSAGE = "agent_message"  # AI text content (streaming)
    TOOL_CALL = "tool_call"  # Tool invocation started
    TOOL_RESULT = "tool_result"  # Tool execution finished
    STATUS = "status"  # Agent status change
    ERROR = "error"  # Error event
    SESSION_END = "session_end"  # Agent turn completed
    HOST_TOOL_CALL = "host_tool_call"  # Host tool needs execution (unknown tool)
    EXTENSION_UI_REQUEST = "extension_ui_request"  # Extension wants UI interaction


@dataclass
class AgentMessage:
    """Streaming AI message chunk."""

    text: str
    message_id: str = ""
    done: bool = False  # True on final chunk


@dataclass
class ToolCall:
    """Tool invocation event."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    intent: str = ""


@dataclass
class ToolResult:
    """Tool execution result."""

    tool_call_id: str
    tool_name: str
    result: Any = None
    is_error: bool = False


@dataclass
class AgentStatus:
    """Agent status snapshot."""

    is_streaming: bool = False
    model: str = ""
    session_id: str = ""


# ── XHS host tool definitions ───────────────────────────────────────────────

# ponytail: tool schemas derived from xhsagent-ext/src/tools/*.ts
# These are the XHS tools the omp agent can call via host_tool_call mechanism.

XHS_HOST_TOOLS: list[dict[str, Any]] = [
    {
        "name": "xhs_workflow_status",
        "label": "XHS Workflow Status",
        "description": "Query workflow status with full snapshot (phase, progress, data summaries)",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID to check"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_workflow_pause",
        "label": "XHS Workflow Pause",
        "description": "Pause a running workflow",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID to pause"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_workflow_resume",
        "label": "XHS Workflow Resume",
        "description": "Resume a paused workflow",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID to resume"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_workflow_cancel",
        "label": "XHS Workflow Cancel",
        "description": "Cancel a workflow",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID to cancel"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_review_approve",
        "label": "XHS Review Approve",
        "description": "Approve content in the review gate",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID"},
                "feedback": {"type": "string", "description": "Optional approval feedback"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_review_reject",
        "label": "XHS Review Reject",
        "description": "Reject content with revision feedback",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Workflow thread ID",
                },
                "feedback": {
                    "type": "string",
                    "description": "Revision feedback / reason for rejection",
                },
            },
            "required": ["thread_id", "feedback"],
        },
    },
    {
        "name": "xhs_review_pending",
        "label": "XHS Review Pending",
        "description": "Get content details awaiting review at the review gate",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_review_versions",
        "label": "XHS Review Versions",
        "description": "Get all content versions for comparison before review decision",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_blogger_pending",
        "label": "XHS Blogger Pending",
        "description": "Get pending blogger candidates for a workflow at blogger selection gate",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_blogger_select",
        "label": "XHS Blogger Select",
        "description": "Select a blogger candidate or skip blogger selection",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID"},
                "user_id": {"type": "string", "description": "Selected blogger user_id"},
                "nickname": {"type": "string", "description": "Selected blogger nickname"},
                "skip": {
                    "type": "boolean",
                    "default": False,
                    "description": "Skip blogger selection",
                },
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_optimization_draft",
        "label": "XHS Optimization Draft",
        "description": "Generate an optimization draft for content at the optimization stage",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_optimization_select",
        "label": "XHS Optimization Select",
        "description": "Select a specific optimization version to proceed with",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID"},
                "version_id": {
                    "type": "string",
                    "description": "Version ID to select (from content_versions)",
                },
                "version_type": {
                    "type": "string",
                    "description": "Version type: A/B/C (optional)",
                },
            },
            "required": ["thread_id", "version_id"],
        },
    },
    {
        "name": "xhs_workflow_list",
        "label": "XHS Workflow List",
        "description": "List all workflows with their status and phase",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "xhs_workflow_delete",
        "label": "XHS Workflow Delete",
        "description": "Delete a workflow and its data",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID to delete"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_analytics_dashboard",
        "label": "XHS Analytics Dashboard",
        "description": "Get analytics dashboard data for an account",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Account ID"},
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "xhs_analytics_costs",
        "label": "XHS Analytics Costs",
        "description": "Get LLM cost tracking data across all workflows",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "default": "weekly",
                    "description": "Time period: daily, weekly, monthly",
                },
            },
        },
    },
    {
        "name": "xhs_system_health",
        "label": "XHS System Health",
        "description": (
            "Check XhsGrowthAgent system health — "
            "LLM providers, XHS platform, Ripple, database, memory store"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "xhs_workflow_history",
        "label": "XHS Workflow History",
        "description": "Get checkpoint history for a workflow (execution timeline)",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Workflow thread ID",
                },
                "limit": {
                    "type": "number",
                    "default": 20,
                    "description": "Max checkpoints to return (1-100)",
                },
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_workflow_trigger_analytics",
        "label": "XHS Trigger Analytics",
        "description": ("Manually trigger analytics for a workflow after publishing"),
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Workflow thread ID (must have publish result)",
                },
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_publish_retry",
        "label": "XHS Publish Retry",
        "description": (
            "Publish or retry publishing existing workflow content without restarting the "
            "fixed creation workflow"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Workflow thread ID with generated content and a publish result",
                },
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_ripple_pending",
        "label": "XHS Ripple Pending",
        "description": ("Get Ripple CAS decision status and available options"),
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Workflow thread ID",
                },
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_ripple_decision",
        "label": "XHS Ripple Decision",
        "description": ("Submit Ripple CAS decision: accept, reangle, or retopic"),
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Workflow thread ID",
                },
                "action": {
                    "type": "string",
                    "enum": ["accept", "reangle", "retopic"],
                    "description": (
                        "Decision: accept, reangle (change angle), or retopic (change topic)"
                    ),
                },
            },
            "required": ["thread_id", "action"],
        },
    },
    {
        "name": "xhs_ripple_retry",
        "label": "XHS Ripple Retry",
        "description": ("Retry Ripple CAS analysis when it previously timed out or failed"),
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Workflow thread ID",
                },
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_analytics_report",
        "label": "XHS Analytics Report",
        "description": "Get growth report for an account",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Account ID"},
                "period": {
                    "type": "string",
                    "default": "weekly",
                    "description": "Time period: daily, weekly, monthly",
                },
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "xhs_analytics_performance",
        "label": "XHS Analytics Performance",
        "description": "Get recent post performance data",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Account ID"},
                "period": {
                    "type": "string",
                    "default": "weekly",
                    "description": "Time period: daily, weekly, monthly",
                },
                "limit": {
                    "type": "number",
                    "default": 10,
                    "description": "Max posts (1-100)",
                },
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "xhs_creator_stats",
        "label": "XHS Creator Statistics",
        "description": (
            "Inspect imported Creator Center account and note metrics; summarizes engagement and "
            "top notes without triggering a live sync"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Account ID with imported Creator Center statistics",
                },
                "limit": {
                    "type": "number",
                    "default": 20,
                    "description": "Maximum imported notes to inspect (1-200)",
                },
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "xhs_creator_analysis",
        "label": "XHS Creator Data Analysis",
        "description": (
            "Analyze imported Creator Center notes for engagement patterns, style findings, and "
            "actionable recommendations"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Account ID with imported Creator Center statistics",
                },
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "xhs_creator_suggestions",
        "label": "XHS Creator Suggestions",
        "description": (
            "Get trend, brief, or free-creation recommendations derived from an account's imported "
            "Creator Center statistics"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Account ID with imported Creator Center statistics",
                },
                "mode": {
                    "type": "string",
                    "enum": ["trend", "brief", "free"],
                    "default": "trend",
                    "description": "Creation mode to guide",
                },
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "xhs_creator_quality",
        "label": "XHS Historical Creative Quality",
        "description": (
            "Assess an account's imported Creator Center history for overall creative-quality "
            "signals, strengths, gaps, and prioritized next-post actions without a live sync"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Account ID with imported Creator Center note history",
                },
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "xhs_evaluation_result",
        "label": "XHS Evaluation Result",
        "description": (
            "Get the creation-quality evaluation (RQGM agent-as-a-judge panel) for a "
            "workflow. Returns 9-dimension scores + overall + decision + revision hints."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_evaluation_run",
        "label": "XHS Evaluation Run",
        "description": (
            "Manually evaluate a workflow's current content with the RQGM agent-as-a-judge "
            "panel. Does NOT advance the workflow."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Workflow thread ID"},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "xhs_free_draft_create",
        "label": "XHS Free Draft Create",
        "description": (
            "Step 1 of 3 (create). Create a free-mode content draft (thread-less). "
            "Returns draft_id — feed it to xhs_free_evaluate (step 2) "
            "then xhs_free_publish (step 3). "
            "For the full orchestration guide call xhs_free_guide."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "default": "default", "description": "Account ID"},
                "title": {"type": "string", "description": "Post title"},
                "body": {"type": "string", "description": "Post body text"},
                "hashtags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Hashtag list",
                },
                "image_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Image file paths",
                },
                "niche": {"type": "string", "description": "Account niche (for evaluation)"},
                "content_angle": {
                    "type": "string",
                    "description": "Content angle (for evaluation)",
                },
                "target_audience": {
                    "type": "string",
                    "description": "Target audience (for evaluation)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "xhs_free_evaluate",
        "label": "XHS Free Draft Evaluate",
        "description": (
            "Step 2 of 3 (evaluate). Evaluate a free-mode draft via the RQGM agent-as-a-judge "
            "panel. Input draft_id from xhs_free_draft_create. Returns EvaluationResult "
            "(overall_score, dimensions, decision)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "default": "default", "description": "Account ID"},
                "draft_id": {
                    "type": "string",
                    "description": "Draft ID from xhs_free_draft_create",
                },
            },
            "required": ["draft_id"],
        },
    },
    {
        "name": "xhs_free_publish",
        "label": "XHS Free Draft Publish",
        "description": (
            "Step 3 of 3 (publish). Publish a free-mode draft to Xiaohongshu (thread-less) "
            "via the account's CDP profile login state. Input draft_id from xhs_free_draft_create. "
            "Run xhs_free_evaluate first for a quality check."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "default": "default", "description": "Account ID"},
                "draft_id": {
                    "type": "string",
                    "description": "Draft ID from xhs_free_draft_create",
                },
            },
            "required": ["draft_id"],
        },
    },
    {
        "name": "xhs_free_analytics",
        "label": "XHS Free Draft Analytics",
        "description": (
            "Post-publish engagement check. Fetch views/likes/collects/comments/shares/"
            "engagement_rate for a published free draft via XHSClient.get_post_analytics. "
            "Input draft_id from xhs_free_draft_create/publish. The draft must have been "
            "published (post_id persisted) — call xhs_free_publish first. Returns current "
            "engagement snapshot (single fetch, not trend over time)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "default": "default", "description": "Account ID"},
                "draft_id": {
                    "type": "string",
                    "description": "Draft ID (must have been published)",
                },
            },
            "required": ["draft_id"],
        },
    },
    {
        "name": "xhs_free_draft_list",
        "label": "XHS Free Draft List",
        "description": (
            "List free-mode drafts for an account (thread-less). Returns draft_id + title "
            "summary, no full body. Use to find a draft_id for evaluate/publish/update/delete."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "default": "default", "description": "Account ID"},
            },
            "required": [],
        },
    },
    {
        "name": "xhs_free_draft_update",
        "label": "XHS Free Draft Update",
        "description": (
            "Update a free-mode draft (thread-less). Overwrites specified fields, keeps "
            "draft_id unchanged. Use to refine before evaluate/publish."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "default": "default", "description": "Account ID"},
                "draft_id": {
                    "type": "string",
                    "description": "Draft ID to update",
                },
                "title": {"type": "string", "description": "New title"},
                "body": {"type": "string", "description": "New body text"},
                "hashtags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "New hashtag list",
                },
                "image_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "New image file paths",
                },
                "niche": {"type": "string", "description": "Account niche (for evaluation)"},
                "content_angle": {
                    "type": "string",
                    "description": "Content angle (for evaluation)",
                },
                "target_audience": {
                    "type": "string",
                    "description": "Target audience (for evaluation)",
                },
            },
            "required": ["draft_id"],
        },
    },
    {
        "name": "xhs_free_draft_delete",
        "label": "XHS Free Draft Delete",
        "description": (
            "Delete a free-mode draft (thread-less). Idempotent — deleting a non-existent "
            "draft is not an error."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "default": "default", "description": "Account ID"},
                "draft_id": {
                    "type": "string",
                    "description": "Draft ID to delete",
                },
            },
            "required": ["draft_id"],
        },
    },
    {
        "name": "xhs_free_guide",
        "label": "XHS Free Mode Guide",
        "description": (
            "Read-only guide for free creation mode. Returns the orchestration steps and tool "
            "chain. Call this first in free mode to learn the create→evaluate→publish loop and "
            "which tools to use."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]

# Names of XHS tools that the backend auto-executes
_XHS_TOOL_NAMES = {t["name"] for t in XHS_HOST_TOOLS}

# Retry config for transient HTTP errors
_RETRYABLE_STATUS = {429, 502, 503, 504}
_MAX_RETRIES = 3


async def _retry_http(
    fn: Callable[..., Coroutine[Any, Any, Any]],
    *args: Any,
    tool_name: str = "",
    **kwargs: Any,
) -> Any:
    """Call an httpx method with exponential backoff on transient errors."""
    import httpx

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return await fn(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES - 1:
                delay = 0.5 * (2**attempt)
                logger.info(
                    "retryable HTTP %d for %s, retry %d/%d in %.1fs",
                    e.response.status_code,
                    tool_name,
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            last_exc = e
            if attempt < _MAX_RETRIES - 1:
                delay = 0.5 * (2**attempt)
                logger.info(
                    "connection error for %s, retry %d/%d in %.1fs",
                    tool_name,
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise
    raise last_exc or RuntimeError("unreachable")  # ponytail: safety


class _RetryingClient:
    """Wraps httpx.AsyncClient to add retry with backoff on transient errors."""

    def __init__(self, client: Any, tool_name: str) -> None:
        self._client = client
        self._tool_name = tool_name

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        return await _retry_http(self._client.get, *args, tool_name=self._tool_name, **kwargs)

    async def post(self, *args: Any, **kwargs: Any) -> Any:
        return await _retry_http(self._client.post, *args, tool_name=self._tool_name, **kwargs)

    async def patch(self, *args: Any, **kwargs: Any) -> Any:
        return await _retry_http(self._client.patch, *args, tool_name=self._tool_name, **kwargs)

    async def delete(self, *args: Any, **kwargs: Any) -> Any:
        return await _retry_http(self._client.delete, *args, tool_name=self._tool_name, **kwargs)


def _creator_number(value: Any) -> float:
    """Coerce an imported Creator Center metric without breaking tool rendering."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _creator_percent(value: Any) -> str:
    """Render Creator Center's fractional engagement rate as a percentage."""
    rate = _creator_number(value)
    if rate <= 1:
        rate *= 100
    return f"{rate:.2f}%"


async def _execute_xhs_host_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Auto-execute a known XHS host tool by calling the backend API internally.

    Uses httpx to call the FastAPI app's own endpoints, so no external HTTP needed.
    Retries transient HTTP errors (429, 502, 503, 504) with exponential backoff.
    """
    import httpx

    api_base = os.environ.get("XHS_AGENT_API_BASE", "http://localhost:8889")
    url = f"{api_base}/api"

    if tool_name == "xhs_workflow_start":
        return _make_text_result(
            (
                "xhs_workflow_start is disabled in OMP free orchestration. "
                "Use the Simple Mode UI to run the fixed workflow."
            ),
            None,
            is_error=True,
        )

    if tool_name == "xhs_free_guide":
        # Local-only: no backend call, just return the orchestration guide text.
        guide = (
            "Free Creation Mode — Orchestration Guide\n"
            "\n"
            "You are in free creation mode (no workflow thread). Use these thread-less tools:\n"
            "\n"
            "1. CREATE: xhs_free_draft_create (title, body, hashtags, image_paths, niche) "
            "→ returns draft_id\n"
            "2. EVALUATE: xhs_free_evaluate (draft_id) → RQGM 6-dimension quality score "
            "+ decision\n"
            "3. PUBLISH: xhs_free_publish (draft_id) → publishes via account CDP login state\n"
            "4. ANALYTICS: xhs_free_analytics (draft_id) → post-publish engagement "
            "(views/likes/collects/comments/shares/engagement_rate)\n"
            "\n"
            "Draft management:\n"
            "- xhs_free_draft_list (account_id) → list drafts (shows [score decision] /\n"
            "  [degraded] / [published] / [publish failed] badges so you can pick the\n"
            "  next step from the list)\n"
            "- xhs_free_draft_update (draft_id, fields...) → refine a draft (keeps draft_id)\n"
            "- xhs_free_draft_delete (draft_id) → remove a draft\n"
            "\n"
            "Rules:\n"
            "- Do NOT call thread-bound tools (xhs_workflow_status/pause/resume/cancel, "
            "xhs_review_*, xhs_optimization_*) — free mode has no thread_id; they will fail.\n"
            "- xhs_workflow_start is disabled in free mode.\n"
            "- Reuse draft_id across create→evaluate→publish; do not recreate on each step.\n"
            "- Run xhs_free_evaluate before xhs_free_publish for a quality gate.\n"
            "- If evaluate returns needs_revision/rejected, use xhs_free_draft_update "
            "per the revision_hints (keep the same draft_id), then xhs_free_evaluate "
            "again before publish — do not publish a needs_revision draft.\n"
            "- Evaluate can degrade (LLM timeout → pass-through fallback with "
            "degraded=True, overall_score=100/decision=approved): the 100/approved "
            "is a FAKE fallback, NOT a real score. The render flags it (⚠ Evaluation "
            "degraded); do NOT publish on a degraded verdict — re-run xhs_free_evaluate "
            "(keep draft_id) once the LLM is available. The draft list shows a "
            "[degraded] badge.\n"
            "- Publish can fail (status=failed/auth_expired): the render shows "
            "Error/Error Type/Recovery — read the recovery hint, fix the cause "
            "(e.g. re-login the account, verify it), then re-run xhs_free_publish "
            "(keep the same draft_id). Do NOT call xhs_free_analytics on a failed "
            "publish (no post_id → 400). The failed attempt is persisted as "
            "last_publish; the draft list shows a [publish failed] badge.\n"
            "- After a successful publish, call xhs_free_analytics to check engagement."
        )
        return _make_text_result(guide, {"mode": "free"})

    try:
        async with httpx.AsyncClient(timeout=30.0) as raw_client:
            # Wrap client methods with retry logic
            client = _RetryingClient(raw_client, tool_name)
            if tool_name == "xhs_workflow_status":
                thread_id = arguments.get("thread_id", "")
                resp = await client.get(f"{url}/workflow/status/{thread_id}")
                data = _unwrap_envelope(resp)
                lines = [
                    f"Workflow Status: {thread_id}",
                    f"  Phase: {data.get('phase', '')}",
                    f"  Status: {data.get('status', '')}",
                    f"  Progress: {data.get('progress_percent', 0)}%",
                    f"  Current Agent: {data.get('current_agent', '')}",
                    f"  Next Steps: {', '.join(data.get('next_steps') or []) or 'none'}",
                ]
                if data.get("error"):
                    lines.append(f"  Error: {data['error']}")
                summaries = []
                for key in (
                    "trend_data",
                    "content_plan",
                    "copy_content",
                    "visual_plan",
                    "publish_result",
                    "analytics",
                ):
                    if data.get(key) and data[key] not in ({}, None):
                        summaries.append(key)
                if summaries:
                    lines.append(f"  Data: {', '.join(summaries)}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_workflow_pause":
                thread_id = arguments.get("thread_id", "")
                resp = await client.post(f"{url}/workflow/pause/{thread_id}")
                data = _unwrap_envelope(resp)
                return _make_text_result(f"Workflow {thread_id} paused.", data)

            elif tool_name == "xhs_workflow_resume":
                thread_id = arguments.get("thread_id", "")
                resp = await client.post(f"{url}/workflow/resume/{thread_id}", json={})
                data = _unwrap_envelope(resp)
                return _make_text_result(f"Workflow {thread_id} resumed.", data)

            elif tool_name == "xhs_workflow_cancel":
                thread_id = arguments.get("thread_id", "")
                resp = await client.post(f"{url}/workflow/cancel/{thread_id}")
                data = _unwrap_envelope(resp)
                return _make_text_result(f"Workflow {thread_id} cancelled.", data)

            elif tool_name == "xhs_review_approve":
                thread_id = arguments.get("thread_id", "")
                body = {"decision": "approved"}
                if arguments.get("feedback"):
                    body["comments"] = arguments["feedback"]
                resp = await client.post(f"{url}/review/submit/{thread_id}", json=body)
                data = _unwrap_envelope(resp)
                return _make_text_result(
                    (
                        f"Content approved for workflow {thread_id}.\n"
                        f"Next phase: {data.get('next_phase', '')}"
                    ),
                    data,
                )

            elif tool_name == "xhs_review_reject":
                thread_id = arguments.get("thread_id", "")
                feedback = arguments.get("feedback", "")
                body = {"decision": "needs_revision", "comments": feedback}
                resp = await client.post(f"{url}/review/submit/{thread_id}", json=body)
                data = _unwrap_envelope(resp)
                return _make_text_result(
                    (
                        f"Content rejected for workflow {thread_id}."
                        " Revision requested.\n"
                        f"Next phase: {data.get('next_phase', '')}"
                    ),
                    data,
                )

            elif tool_name == "xhs_review_pending":
                thread_id = arguments.get("thread_id", "")
                resp = await client.get(f"{url}/review/pending/{thread_id}")
                data = _unwrap_envelope(resp)
                if data.get("status") != "awaiting_review":
                    return _make_text_result(
                        f"Workflow {thread_id} is not at review gate.",
                        data,
                    )
                lines = [f"Content Pending Review — {thread_id}:"]
                copy = data.get("copy_content") or {}
                title = copy.get("selected_title") or copy.get("title") or ""
                body_text = copy.get("body_text") or copy.get("body") or ""
                if title:
                    lines.append(f"  Title: {title}")
                if body_text:
                    lines.append(f"  Body: {str(body_text)[:500]}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_review_versions":
                thread_id = arguments.get("thread_id", "")
                resp = await client.get(f"{url}/review/versions/{thread_id}")
                data = _unwrap_envelope(resp)
                versions = data.get("versions", [])
                if not versions:
                    return _make_text_result("No content versions available.", data)
                current = data.get("current", {})
                current_title = current.get("title", "(no title)")
                lines = [f"Content Versions — {thread_id}:", f"  Current: {current_title}"]
                for i, v in enumerate(versions, 1):
                    vid = v.get("version_id", "?")
                    summary = v.get("changes_summary", "draft")
                    lines.append(f"  {i}. [{vid}] {summary}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_blogger_pending":
                thread_id = arguments.get("thread_id", "")
                resp = await client.get(f"{url}/optimization/blogger-pending/{thread_id}")
                data = _unwrap_envelope(resp)
                if not data.get("is_pending"):
                    return _make_text_result(
                        f"Workflow {thread_id} is not at blogger selection gate.", data
                    )
                candidates = data.get("blogger_candidates", [])
                if not candidates:
                    return _make_text_result("No blogger candidates available.", data)
                lines = [f"Blogger Candidates for {thread_id}:"]
                for i, c in enumerate(candidates, 1):
                    lines.append(f"  {i}. {c.get('nickname', '?')} (ID: {c.get('user_id', '?')})")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_blogger_select":
                thread_id = arguments.get("thread_id", "")
                sel_body: dict[str, Any] = {"skip": arguments.get("skip", False)}
                if not arguments.get("skip"):
                    if not arguments.get("user_id"):
                        return _make_text_result(
                            "user_id is required when not skipping.", None, is_error=True
                        )
                    sel_body["user_id"] = arguments["user_id"]
                    if arguments.get("nickname"):
                        sel_body["nickname"] = arguments["nickname"]
                resp = await client.post(
                    f"{url}/optimization/blogger-select/{thread_id}", json=sel_body
                )
                data = _unwrap_envelope(resp)
                if arguments.get("skip"):
                    action = "skipped"
                else:
                    action = f'selected "{arguments.get("nickname", "")}"'
                next_phase = data.get("next_phase", "")
                return _make_text_result(
                    f"Blogger {action} for {thread_id}. Next: {next_phase}",
                    data,
                )

            elif tool_name == "xhs_optimization_draft":
                thread_id = arguments.get("thread_id", "")
                resp = await client.post(f"{url}/optimization/draft/{thread_id}")
                data = _unwrap_envelope(resp)
                status = data.get("status", "")
                lines = [f"Optimization Draft — {thread_id}:", f"  Status: {status}"]
                draft = data.get("draft_content") or {}
                title = draft.get("title") or ""
                body_text = draft.get("text") or ""
                if title:
                    lines.append(f"  Title: {title}")
                if body_text:
                    lines.append(f"  Body: {str(body_text)[:500]}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_optimization_select":
                thread_id = arguments.get("thread_id", "")
                version_id = arguments.get("version_id", "")
                version_type = arguments.get("version_type")
                opt_body: dict[str, Any] = {"version_id": version_id}
                if version_type:
                    opt_body["version_type"] = version_type
                resp = await client.post(f"{url}/optimization/select/{thread_id}", json=opt_body)
                data = _unwrap_envelope(resp)
                next_phase = data.get("next_phase", "")
                return _make_text_result(
                    f"Selected version {version_id} for {thread_id}. Next: {next_phase}",
                    data,
                )

            elif tool_name == "xhs_workflow_list":
                resp = await client.get(f"{url}/workflow/list")
                data = _unwrap_envelope(resp)
                workflows = data.get("workflows", [])
                if not workflows:
                    return _make_text_result("No workflows found.", data)
                lines = [f"Workflows ({len(workflows)}):"]
                for w in workflows:
                    tid = w.get("thread_id", "")
                    lines.append(f"  {tid[:8]}… | {w.get('phase', '')} | {w.get('status', '')}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_workflow_delete":
                thread_id = arguments.get("thread_id", "")
                resp = await client.delete(f"{url}/workflow/{thread_id}")
                _unwrap_envelope(resp)
                return _make_text_result(f"Workflow {thread_id} deleted.")

            elif tool_name == "xhs_analytics_dashboard":
                account_id = arguments.get("account_id", "")
                resp = await client.get(f"{url}/analytics/dashboard/{account_id}")
                data = _unwrap_envelope(resp)
                lines = [f"Analytics Dashboard — {account_id}:"]
                report = data.get("report", {})
                metrics = report.get("metrics", {})
                if metrics:
                    lines.append(
                        f"  Posts: {metrics.get('total_posts', 0)}, "
                        f"Engagement: {metrics.get('total_engagement', 0)}, "
                        f"Avg Rate: {metrics.get('avg_engagement_rate', 0)}%"
                    )
                    best = metrics.get("best_post_title", "")
                    if best:
                        lines.append(f"  Best Post: {best}")
                costs = data.get("costs", {})
                if costs:
                    lines.append(
                        f"  Costs: ${costs.get('period_cost_usd', 0):.2f} this period, "
                        f"${costs.get('today_cost_usd', 0):.2f} today"
                    )
                perf = data.get("performance", {})
                if perf.get("posts"):
                    lines.append(f"  Recent Posts: {len(perf['posts'])}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_analytics_costs":
                period = arguments.get("period", "weekly")
                resp = await client.get(f"{url}/analytics/costs", params={"period": period})
                data = _unwrap_envelope(resp)
                total = data.get("total_cost_usd", 0)
                period_cost = data.get("period_cost_usd", 0)
                today_cost = data.get("today_cost_usd", 0)
                lines = [
                    f"LLM Cost Report (period: {period}):",
                    f"  Total: ${total:.4f}",
                    f"  This Period: ${period_cost:.4f}",
                    f"  Today: ${today_cost:.4f}",
                ]
                by_model = data.get("by_model", {})
                if by_model:
                    lines.append("  By Model:")
                    for model, cost in by_model.items():
                        lines.append(f"    {model}: ${cost:.4f}")
                budget = data.get("budget_remaining_usd")
                if budget is not None:
                    lines.append(f"  Budget Remaining: ${budget:.2f}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_system_health":
                resp = await client.get(f"{url}/system/health")
                data = _unwrap_envelope(resp)
                checks = data.get("checks", {})
                lines = [
                    f"System Health: {data.get('status', 'unknown').upper()}",
                    f"  LLM Providers: {checks.get('llm_providers', {}).get('status', '?')}",
                    f"  Ripple CAS: {checks.get('ripple_cas', {}).get('status', '?')}",
                ]
                db_check = checks.get("database", {})
                lines.append(
                    f"  Database: {db_check.get('status', '?')} ({db_check.get('mode', '?')})"
                )
                lines.append(f"  Memory Store: {checks.get('memory_store', {}).get('status', '?')}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_workflow_history":
                thread_id = arguments.get("thread_id", "")
                limit = arguments.get("limit", 20)
                resp = await client.get(
                    f"{url}/workflow/history/{thread_id}",
                    params={"limit": limit},
                )
                data = _unwrap_envelope(resp)
                checkpoints = data.get("checkpoints", [])
                if not checkpoints:
                    return _make_text_result(f"No history for {thread_id}.", data)
                has_more = ", more available" if data.get("has_more") else ""
                lines = [
                    f"Workflow History — {thread_id} ({len(checkpoints)} checkpoints{has_more}):",
                ]
                for c in checkpoints:
                    step = c.get("step", "?")
                    phase = c.get("phase", "?")
                    agent = c.get("current_agent", "—")
                    ts = c.get("created_at") or "N/A"
                    lines.append(f"  Step {step} | {phase} | {agent} | {ts}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_workflow_trigger_analytics":
                thread_id = arguments.get("thread_id", "")
                resp = await client.post(f"{url}/workflow/trigger-analytics/{thread_id}")
                data = _unwrap_envelope(resp)
                status = data.get("status", "")
                if status == "completed":
                    return _make_text_result(f"Analytics already completed for {thread_id}.", data)
                if status == "error":
                    return _make_text_result(
                        f"Cannot trigger analytics: {data.get('message', 'unknown error')}",
                        data,
                    )
                return _make_text_result(
                    f"Analytics triggered for {thread_id}. Phase: {data.get('phase', 'analyzing')}",
                    data,
                )

            elif tool_name == "xhs_publish_retry":
                thread_id = arguments.get("thread_id", "")
                resp = await client.post(f"{url}/workflow/publish-retry/{thread_id}")
                data = _unwrap_envelope(resp)
                status = data.get("status", "")
                message = data.get("message", "")
                text = f"Publish retry for {thread_id}: {status}"
                if message:
                    text += f"\n{message}"
                return _make_text_result(text, data)

            elif tool_name == "xhs_ripple_pending":
                thread_id = arguments.get("thread_id", "")
                resp = await client.get(f"{url}/review/ripple-pending/{thread_id}")
                data = _unwrap_envelope(resp)
                pred = data.get("ripple_prediction", {})
                lines = [
                    f"Ripple Decision — {thread_id}:",
                    f"  Status: {data.get('status', '')}",
                    f"  Reselect: {data.get('reselect_count', 0)}/{data.get('max_reselect', 0)}",
                    f"  Options: {', '.join(data.get('options', []))}",
                ]
                if pred.get("viral_probability"):
                    lines.append(f"  Viral Prob: {pred['viral_probability']}")
                if pred.get("estimated_reach"):
                    lines.append(f"  Est Reach: {pred['estimated_reach']}")
                if pred.get("confidence"):
                    lines.append(f"  Confidence: {pred['confidence']}")
                pmf = data.get("ripple_pmf", {})
                if pmf.get("pmf_score"):
                    lines.append(f"  PMF Score: {pmf['pmf_score']}")
                if data.get("ripple_reason"):
                    lines.append(f"  Reason: {data['ripple_reason']}")
                lines.append("")
                lines.append("Use xhs_ripple_decision to submit your choice.")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_ripple_decision":
                thread_id = arguments.get("thread_id", "")
                action = arguments.get("action", "accept")
                resp = await client.post(
                    f"{url}/review/ripple-decision/{thread_id}",
                    json={"action": action},
                )
                data = _unwrap_envelope(resp)
                labels = {
                    "accept": "Accepted",
                    "reangle": "Angle change requested",
                    "retopic": "Topic change requested",
                }
                return _make_text_result(
                    f"{labels.get(action, action)} for {thread_id}."
                    f" Next: {data.get('next_phase', '')}",
                    data,
                )

            elif tool_name == "xhs_ripple_retry":
                thread_id = arguments.get("thread_id", "")
                resp = await client.post(f"{url}/workflow/ripple-retry/{thread_id}")
                data = _unwrap_envelope(resp)
                if data.get("status") == "skipped":
                    return _make_text_result(
                        f"Ripple retry skipped: {data.get('message', '')}",
                        data,
                    )
                return _make_text_result(
                    f"Ripple retry started for {thread_id}. Status: {data.get('status', '')}",
                    data,
                )

            elif tool_name == "xhs_analytics_report":
                account_id = arguments.get("account_id", "")
                period = arguments.get("period", "weekly")
                resp = await client.get(
                    f"{url}/analytics/report/{account_id}",
                    params={"period": period},
                )
                data = _unwrap_envelope(resp)
                m = data.get("metrics", {})
                lines = [
                    f"Growth Report — {account_id} ({period}):",
                    f"  Posts: {m.get('total_posts', 0)}",
                    f"  Engagement: {m.get('total_engagement', 0)}",
                    f"  Avg Rate: {m.get('avg_engagement_rate', 0)}%",
                ]
                if m.get("best_post_title"):
                    lines.append(f"  Best: {m['best_post_title']}")
                if m.get("trend_topics"):
                    lines.append(f"  Trends: {', '.join(m['trend_topics'])}")
                for ins in data.get("insights", []):
                    lines.append(f"  - {ins.get('message', '')}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_analytics_performance":
                account_id = arguments.get("account_id", "")
                period = arguments.get("period", "weekly")
                limit = arguments.get("limit", 10)
                resp = await client.get(
                    f"{url}/analytics/performance/{account_id}",
                    params={"period": period, "limit": limit},
                )
                data = _unwrap_envelope(resp)
                posts = data.get("posts", [])
                if not posts:
                    return _make_text_result("No performance data.", data)
                lines = [
                    f"Performance — {account_id} ({data.get('total', 0)} posts):",
                ]
                for p in posts:
                    lines.append(
                        f"  {p.get('title', '?')} —"
                        f" ❤{p.get('likes', 0)}"
                        f" 💬{p.get('comments', 0)}"
                        f" ⭐{p.get('collects', 0)}"
                        f" ({p.get('engagement_rate', 0)}%)"
                    )
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_creator_stats":
                account_id = arguments.get("account_id", "")
                limit = arguments.get("limit", 20)
                resp = await client.get(
                    f"{url}/analytics/creator-stats/{account_id}",
                    params={"limit": limit},
                )
                data = _unwrap_envelope(resp)
                account = data.get("account") if isinstance(data.get("account"), dict) else {}
                notes = [note for note in data.get("notes", []) if isinstance(note, dict)]
                lines = [f"Creator Statistics — {account_id}:"]
                if account:
                    lines.extend(
                        [
                            (
                                f"  Account ({account.get('period') or 'unknown window'}): "
                                f"{account.get('views', 0)} views, "
                                f"{account.get('likes', 0)} likes, "
                                f"{account.get('collects', 0)} collects, "
                                f"{account.get('comments', 0)} comments, "
                                f"{account.get('shares', 0)} shares"
                            ),
                            (
                                f"  Followers: {account.get('fans', 0)}; reported notes: "
                                f"{account.get('note_count') or data.get('total', 0)}; "
                                f"source: {account.get('source') or 'unknown'}"
                            ),
                        ]
                    )
                if not notes:
                    lines.append(
                        "  No imported notes are available. Sync Creator Center statistics before "
                        "analyzing content."
                    )
                    return _make_text_result("\n".join(lines), data)

                average_rate = sum(
                    _creator_number(note.get("engagement_rate")) for note in notes
                ) / len(notes)
                top_notes = sorted(
                    notes,
                    key=lambda note: (
                        _creator_number(note.get("engagement_rate")),
                        _creator_number(note.get("views")),
                    ),
                    reverse=True,
                )[:5]
                lines.extend(
                    [
                        (
                            f"  Loaded: {len(notes)}/{data.get('total') or len(notes)} notes; "
                            f"average note engagement: {_creator_percent(average_rate)}"
                        ),
                        "  Top notes by engagement:",
                    ]
                )
                for index, note in enumerate(top_notes, 1):
                    lines.append(
                        f"  {index}. {note.get('title') or '(untitled)'} — "
                        f"{_creator_percent(note.get('engagement_rate'))}; "
                        f"{note.get('views', 0)} views; ❤{note.get('likes', 0)} "
                        f"⭐{note.get('collects', 0)} 💬{note.get('comments', 0)}"
                    )
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_creator_analysis":
                account_id = arguments.get("account_id", "")
                resp = await client.get(f"{url}/analytics/creator-stats/{account_id}/analysis")
                data = _unwrap_envelope(resp)
                analysis_raw = data.get("analysis")
                analysis: dict[str, Any] = analysis_raw if isinstance(analysis_raw, dict) else {}
                findings = [
                    finding for finding in analysis.get("findings", []) if isinstance(finding, dict)
                ]
                lines = [
                    f"Creator Data Analysis — {account_id}:",
                    (
                        f"  Notes analyzed: {analysis.get('note_count', 0)}; average engagement: "
                        f"{_creator_percent(analysis.get('avg_engagement_rate'))}"
                    ),
                ]
                if not findings:
                    lines.append(
                        "  No evidence-backed findings yet. Import more notes for a stronger "
                        "analysis."
                    )
                else:
                    lines.append("  Findings:")
                    for finding in findings[:8]:
                        evidence = (
                            f" — {finding.get('evidence')}" if finding.get("evidence") else ""
                        )
                        lines.append(
                            f"  - [{finding.get('finding_type') or 'pattern'}] "
                            f"{finding.get('label') or 'unnamed'}{evidence} "
                            f"(score {_creator_number(finding.get('score')):.3f}, "
                            f"n={finding.get('sample_count') or 0})"
                        )
                suggestions_raw = data.get("suggestions")
                suggestions: dict[str, Any] = (
                    suggestions_raw if isinstance(suggestions_raw, dict) else {}
                )
                for mode, items in suggestions.items():
                    mode_items = (
                        [item for item in items if isinstance(item, dict)]
                        if isinstance(items, list)
                        else []
                    )
                    if not mode_items:
                        continue
                    lines.append(f"  {mode} recommendations:")
                    for suggestion in mode_items[:2]:
                        title = (
                            suggestion.get("title")
                            or suggestion.get("category")
                            or "Recommendation"
                        )
                        advice = suggestion.get("advice") or suggestion.get("evidence") or ""
                        lines.append(f"  - {title}: {advice}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_creator_suggestions":
                account_id = arguments.get("account_id", "")
                mode = arguments.get("mode", "trend")
                resp = await client.get(
                    f"{url}/analytics/creator-stats/{account_id}/suggestions",
                    params={"mode": mode},
                )
                data = _unwrap_envelope(resp)
                creator_suggestions = [
                    item for item in data.get("suggestions", []) if isinstance(item, dict)
                ]
                lines = [f"Creator Suggestions — {account_id} ({data.get('mode') or mode}):"]
                if data.get("cold_start"):
                    lines.append(
                        "  Note: this account is in cold start; recommendations use limited "
                        "evidence."
                    )
                if not creator_suggestions:
                    lines.append(
                        "  No suggestions are available yet. Import and analyze Creator Center "
                        "notes first."
                    )
                    return _make_text_result("\n".join(lines), data)
                for creator_suggestion in creator_suggestions:
                    evidence = (
                        f" Evidence: {creator_suggestion.get('evidence')}"
                        if creator_suggestion.get("evidence")
                        else ""
                    )
                    title = (
                        creator_suggestion.get("title")
                        or creator_suggestion.get("category")
                        or "Recommendation"
                    )
                    lines.append(
                        f"  - [P{creator_suggestion.get('priority', '?')}] {title}: "
                        f"{creator_suggestion.get('advice') or ''}{evidence}"
                    )
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_creator_quality":
                account_id = arguments.get("account_id", "")
                resp = await client.get(
                    f"{url}/analytics/creator-stats/{account_id}/quality",
                    params={"locale": "en"},
                )
                data = _unwrap_envelope(resp)
                report_account_id = data.get("account_id") or account_id
                notes_analyzed = int(_creator_number(data.get("notes_analyzed")))
                total_notes = int(_creator_number(data.get("total_notes")))
                insufficient_history = bool(
                    data.get("cold_start")
                    or data.get("insufficient_data")
                    or data.get("grade") == "insufficient_data"
                    or notes_analyzed < 3
                )
                lines = [f"Historical Creative Quality — {report_account_id}:"]
                if insufficient_history:
                    lines.extend(
                        [
                            (
                                "  Imported history is not yet sufficient "
                                f"({notes_analyzed}/{total_notes} notes analyzed)."
                            ),
                            (
                                "  Overall: not scored; grade: "
                                f"{data.get('grade') or 'insufficient_data'}; confidence: "
                                f"{data.get('confidence') or 'low'}"
                            ),
                        ]
                    )
                    if data.get("summary"):
                        lines.append(f"  {data['summary']}")
                    recommendations = [
                        item for item in data.get("recommendations", []) if isinstance(item, dict)
                    ]
                    if recommendations:
                        recommendation = recommendations[0]
                        title = recommendation.get("title") or "Action"
                        advice = (
                            recommendation.get("advice") or recommendation.get("evidence") or ""
                        )
                        lines.append(f"  Next action: {title}: {advice}")
                    return _make_text_result("\n".join(lines), data)

                score = data.get("overall_score")
                score_text = (
                    f"{_creator_number(score):.1f}/100"
                    if isinstance(score, (int, float))
                    else "not scored"
                )
                lines.extend(
                    [
                        (
                            f"  Overall: {score_text}; grade: {data.get('grade') or 'unknown'}; "
                            f"confidence: {data.get('confidence') or 'unknown'}"
                        ),
                        (
                            f"  Scope: {data.get('scope') or 'imported history'}; "
                            f"notes analyzed: {notes_analyzed}/{total_notes}"
                        ),
                    ]
                )
                if data.get("summary"):
                    lines.append(f"  Summary: {data['summary']}")
                for heading, key, fallback in (
                    ("Strengths", "strengths", "No evidence-backed strengths were returned."),
                    ("Gaps", "weaknesses", "No evidence-backed gaps were returned."),
                ):
                    lines.append(f"  {heading}:")
                    insights = [item for item in data.get(key, []) if isinstance(item, dict)]
                    if not insights:
                        lines.append(f"  - {fallback}")
                    for insight in insights:
                        title = insight.get("title") or insight.get("dimension") or heading[:-1]
                        evidence = f" — {insight['evidence']}" if insight.get("evidence") else ""
                        lines.append(f"  - {title}{evidence}")
                lines.append("  Priority actions:")
                recommendations = [
                    item for item in data.get("recommendations", []) if isinstance(item, dict)
                ]
                if not recommendations:
                    lines.append("  - No prioritized actions were returned.")
                for index, recommendation in enumerate(
                    sorted(
                        recommendations,
                        key=lambda item: _creator_number(item.get("priority")),
                    )[:3],
                    start=1,
                ):
                    priority = int(_creator_number(recommendation.get("priority"))) or index
                    title = (
                        recommendation.get("title") or recommendation.get("dimension") or "Action"
                    )
                    advice = recommendation.get("advice") or recommendation.get("evidence") or ""
                    lines.append(f"  - [P{priority}] {title}: {advice}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_evaluation_result":
                thread_id = arguments.get("thread_id", "")
                resp = await client.get(f"{url}/evaluation/result/{thread_id}")
                data = _unwrap_envelope(resp)
                if not data.get("has_evaluation"):
                    return _make_text_result(
                        f"No evaluation result yet for {thread_id}.",
                        data,
                    )
                ev = data.get("evaluation_result") or {}
                lines = [
                    f"Evaluation — {thread_id}:",
                    f"  Overall: {ev.get('overall_score', 'N/A')}"
                    f"  Decision: {ev.get('decision', '?')}",
                ]
                if ev.get("bias_warning"):
                    lines.append(f"  ⚠ Bias: {ev['bias_warning']}")
                for d in ev.get("dimensions") or []:
                    block = " [BLOCKING]" if d.get("is_blocking") else ""
                    lines.append(f"  - {d.get('dimension')}: {d.get('score')}{block}")
                for h in ev.get("revision_hints") or []:
                    lines.append(f"  hint: {h}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_evaluation_run":
                thread_id = arguments.get("thread_id", "")
                resp = await client.post(f"{url}/evaluation/run/{thread_id}")
                data = _unwrap_envelope(resp)
                ev = data.get("evaluation_result") or {}
                lines = [
                    f"Evaluation complete — {thread_id}:",
                    f"  Overall: {ev.get('overall_score', 'N/A')}"
                    f"  Decision: {ev.get('decision', '?')}",
                ]
                if ev.get("bias_warning"):
                    lines.append(f"  ⚠ Bias: {ev['bias_warning']}")
                for d in ev.get("dimensions") or []:
                    block = " [BLOCKING]" if d.get("is_blocking") else ""
                    lines.append(f"  - {d.get('dimension')}: {d.get('score')}{block}")
                for h in ev.get("revision_hints") or []:
                    lines.append(f"  hint: {h}")
                return _make_text_result("\n".join(lines), data)

            elif tool_name == "xhs_free_draft_create":
                body = {
                    "account_id": arguments.get("account_id", "default"),
                    "title": arguments.get("title", ""),
                    "body": arguments.get("body", ""),
                    "hashtags": arguments.get("hashtags", []),
                    "image_paths": arguments.get("image_paths", []),
                    "niche": arguments.get("niche") or "母婴",
                    "content_angle": arguments.get("content_angle", ""),
                    "target_audience": arguments.get("target_audience", ""),
                }
                resp = await client.post(f"{url}/free/draft", json=body)
                data = _unwrap_envelope(resp)
                draft = data.get("draft") or {}
                draft_id = data.get("draft_id", "")
                lines = [
                    f"Free Draft Created — draft_id: {draft_id}",
                    f"Title: {draft.get('title', '')}",
                ]
                # Create→evaluate next-step cue — the create render is the chain
                # entry point (yields the draft_id evaluate/publish depend on),
                # so surface the immediate next step. Mirrors the evaluate/publish
                # render cues (#234/#235); no cue on a failed create (no draft_id).
                if draft_id:
                    lines.append(
                        f"  next: call xhs_free_evaluate({draft_id}) for a quality "
                        "check before publish."
                    )
                return _make_text_result("\n".join(lines), {"draft_id": draft_id, **data})

            elif tool_name == "xhs_free_evaluate":
                account_id = arguments.get("account_id", "default")
                draft_id = arguments.get("draft_id", "")
                resp = await client.post(
                    f"{url}/free/evaluate",
                    json={"account_id": account_id, "draft_id": draft_id},
                )
                data = _unwrap_envelope(resp)
                ev = data.get("evaluation_result") or {}
                # Degraded (LLM timeout → pass-through fallback): the 100/approved
                # is fake, not a real score. Surface it so the agent doesn't trust
                # the verdict or publish an unevaluated draft. Mirrors #240's
                # publish-failure surfacing for the evaluate path.
                degraded = bool(ev.get("degraded"))
                lines = [
                    f"Free Draft Evaluation — {draft_id}",
                    f"  Overall: {ev.get('overall_score', 'N/A')}"
                    f"  Decision: {ev.get('decision', '?')}",
                ]
                if degraded:
                    lines.append(
                        "  ⚠ Evaluation degraded (LLM timeout/failure) — verdict is a "
                        "pass-through fallback, NOT a real score; do not publish on it."
                    )
                    if ev.get("summary"):
                        lines.append(f"  cause: {ev['summary']}")
                if ev.get("bias_warning"):
                    lines.append(f"  ⚠ Bias: {ev['bias_warning']}")
                for d in ev.get("dimensions") or []:
                    block = " [BLOCKING]" if d.get("is_blocking") else ""
                    lines.append(f"  - {d.get('dimension')}: {d.get('score')}{block}")
                for h in ev.get("revision_hints") or []:
                    lines.append(f"  hint: {h}")
                # Revise-loop next step — closes evaluate→update→re-evaluate for
                # the agent (free mode's default driver). Mirrors the TUI /draft
                # revise hint (#229): needs_revision/rejected with concrete hints
                # points at xhs_free_draft_update → re-evaluate, not straight to
                # publish. approved/rejected-without-hints get no cue. A degraded
                # (fake-approved) eval gets a re-run cue instead.
                decision = ev.get("decision", "")
                if degraded:
                    lines.append(
                        "  next: re-run xhs_free_evaluate (draft_id unchanged) once the "
                        "LLM is available; do not publish on a degraded verdict."
                    )
                elif decision in ("needs_revision", "rejected") and (
                    ev.get("revision_hints") or []
                ):
                    lines.append(
                        "  next: revise per the hints via xhs_free_draft_update "
                        "(keep draft_id), then xhs_free_evaluate again before publish."
                    )
                return _make_text_result("\n".join(lines), {"evaluation_result": ev, **data})

            elif tool_name == "xhs_free_publish":
                account_id = arguments.get("account_id", "default")
                draft_id = arguments.get("draft_id", "")
                resp = await client.post(
                    f"{url}/free/publish",
                    json={"account_id": account_id, "draft_id": draft_id},
                )
                data = _unwrap_envelope(resp)
                pub = data.get("publish_result") or {}
                lines = [
                    f"Free Draft Published — {draft_id}",
                    f"  Post ID: {pub.get('post_id', '')}",
                    f"  URL: {pub.get('post_url', '')}",
                    f"  Status: {pub.get('status', '')}",
                ]
                # Next-step cue — mirrors the evaluate render (#234) and the TUI
                # post-publish hint (#223). Real publish (status=="published",
                # non-mock post_id) → point at xhs_free_analytics for engagement.
                # Mock publish (dry-run, "mock_*" post_id / mock_published) → flag
                # it as simulated so the agent doesn't call analytics (which 400s
                # on a synthetic post_id). Failed publish → surface cause + recovery.
                pid = pub.get("post_id", "") or ""
                pstatus = pub.get("status", "") or ""
                if pstatus == "published" and pid and not pid.startswith("mock_"):
                    lines.append(
                        f"  next: call xhs_free_analytics({draft_id}) to check "
                        "post-publish engagement."
                    )
                elif pstatus == "mock_published" or pid.startswith("mock_"):
                    lines.append(
                        "  note: dry-run mock publish (no real XHS post) — analytics "
                        "not available; re-run xhs_free_publish without dry-run for a "
                        "real post."
                    )
                elif pstatus != "published" and pub.get("error"):
                    # Failed publish (status==failed/auth_expired/...) — surface the
                    # cause + recovery path that run_publish returns so the agent can
                    # tell the user why and what to do (mirrors #234/#235 cue pattern).
                    lines.append(f"  Error: {pub['error']}")
                    if pub.get("error_type"):
                        lines.append(f"  Error Type: {pub['error_type']}")
                    recovery = pub.get("recovery") or {}
                    if recovery.get("message"):
                        lines.append(f"  Recovery: {recovery['message']}")
                    if recovery.get("hint"):
                        lines.append(f"  Hint: {recovery['hint']}")
                return _make_text_result("\n".join(lines), {"publish_result": pub, **data})

            elif tool_name == "xhs_free_analytics":
                account_id = arguments.get("account_id", "default")
                draft_id = arguments.get("draft_id", "")
                resp = await client.get(
                    f"{url}/free/analytics/{draft_id}",
                    params={"account_id": account_id},
                )
                data = _unwrap_envelope(resp)
                a = data.get("analytics") or {}
                lines = [
                    f"Free Draft Analytics — {draft_id}",
                    f"  Post ID: {data.get('post_id', '')}",
                    f"  Views: {a.get('views', 0)}",
                    f"  Likes: {a.get('likes', 0)}",
                    f"  Collects: {a.get('collects', 0)}",
                    f"  Comments: {a.get('comments', 0)}",
                    f"  Shares: {a.get('shares', 0)}",
                    f"  Engagement Rate: {a.get('engagement_rate', 0)}%",
                    f"  Fetched At: {a.get('fetched_at', '')}",
                ]
                return _make_text_result("\n".join(lines), {"analytics": a, **data})

            elif tool_name == "xhs_free_draft_list":
                account_id = arguments.get("account_id", "default")
                resp = await client.get(f"{url}/free/drafts/{account_id}")
                data = _unwrap_envelope(resp)
                drafts = data.get("drafts", [])
                if not drafts:
                    return _make_text_result(f"Free Drafts — {account_id}\n  (none)", data)
                # Header with count — count is the filtered count from the route;
                # the agent can see how many drafts match without scanning lines.
                count = data.get("count", len(drafts))
                lines = [f"Free Drafts — {account_id} ({count})"]
                if data.get("truncated"):
                    # Route caps asearch at 100 — older drafts beyond the cap
                    # aren't visible. Surface it so the agent knows the list
                    # may be incomplete (mirrors the TUI /drafts truncated hint).
                    lines.append("  (truncated — older drafts not shown)")
                for d in drafts:
                    parts = [f"  - {d.get('draft_id', '')}: {d.get('title', '')}"]
                    # Eval badge — last_evaluation with a decision lets the agent
                    # pick next step from the list (unevaluated→evaluate,
                    # needs_revision→revise, approved→publish/analytics). A
                    # degraded (fake-approved fallback) eval shows [degraded]
                    # instead of the misleading [100 approved].
                    le = d.get("last_evaluation") or {}
                    if le and le.get("degraded"):
                        parts.append("  [degraded]")
                    elif le and le.get("decision"):
                        score = le.get("overall_score")
                        score_str = f"{score}" if score is not None else "?"
                        parts.append(f"  [{score_str} {le.get('decision')}]")
                    if d.get("published"):
                        parts.append("  [published]")
                    # Publish-failed badge — last_publish with a non-success status
                    # lets the agent see from the list that a publish attempt failed
                    # (→ re-attempt after fixing cause) without opening the detail.
                    lp = d.get("last_publish") or {}
                    lp_status = lp.get("status") or ""
                    if lp_status and lp_status not in ("published", "mock_published"):
                        parts.append("  [publish failed]")
                    lines.append("".join(parts))
                return _make_text_result("\n".join(lines), {"drafts": drafts, **data})

            elif tool_name == "xhs_free_draft_update":
                account_id = arguments.get("account_id", "default")
                draft_id = arguments.get("draft_id", "")
                body = {k: v for k, v in arguments.items() if k not in ("account_id", "draft_id")}
                resp = await client.patch(
                    f"{url}/free/draft/{draft_id}",
                    params={"account_id": account_id},
                    json=body,
                )
                data = _unwrap_envelope(resp)
                draft = data.get("draft") or {}
                lines = [
                    f"Free Draft Updated — {draft_id}",
                    f"Title: {draft.get('title', '')}",
                ]
                return _make_text_result(
                    "\n".join(lines), {"draft_id": draft_id, "draft": draft, **data}
                )

            elif tool_name == "xhs_free_draft_delete":
                account_id = arguments.get("account_id", "default")
                draft_id = arguments.get("draft_id", "")
                resp = await client.delete(
                    f"{url}/free/draft/{draft_id}",
                    params={"account_id": account_id},
                )
                data = _unwrap_envelope(resp)
                return _make_text_result(
                    f"Free Draft Deleted — {draft_id}",
                    {"draft_id": draft_id, "deleted": True, **data},
                )

            else:
                return _make_text_result(f"Unknown tool: {tool_name}", None, is_error=True)

    except Exception as e:
        logger.exception("host tool auto-execution failed for %s", tool_name)
        return _make_text_result(f"Failed: {e}", None, is_error=True)


def _unwrap_envelope(resp: Any) -> dict[str, Any]:
    """Unwrap the ApiResponse envelope {success, data, error}.

    Raises httpx.HTTPStatusError for retryable HTTP errors (429, 502-504).
    """
    # Raise for retryable HTTP status codes so _retry_http can catch them
    resp.raise_for_status()
    body: dict[str, Any] = resp.json()
    if body.get("success"):
        return body.get("data", {}) or {}
    err = body.get("error", {})
    msg = err.get("message", "") if isinstance(err, dict) else str(err)
    raise RuntimeError(f"API error: {msg}")


def _make_text_result(text: str, details: Any = None, is_error: bool = False) -> dict[str, Any]:
    """Create an omp host_tool_result payload with text content."""
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
    }
    if details:
        result["details"] = details
    if is_error:
        result["isError"] = True
    return result


# ── OmpSession — one omp subprocess per session ────────────────────────────


class OmpSession:
    """Manages one ``omp --mode rpc`` subprocess for a single session.

    Each session gets its own subprocess, event callbacks, and pending requests.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._proc: asyncio.subprocess.Process | None = None
        self._ready = asyncio.Event()
        self._event_callbacks: list[Callable[[dict[str, Any]], Coroutine[None, None, None]]] = []
        self._reader_task: asyncio.Task[None] | None = None
        self._cmd_id = 0
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        # Track current streaming message for message_update aggregation
        self._current_msg_id: str = ""
        self._current_msg_text: str = ""
        # Host tool execution tasks
        self._host_tool_tasks: dict[str, asyncio.Task[None]] = {}
        # Track auto-executed tool call IDs (to avoid forwarding cancels for them)
        self._auto_executed_ids: set[str] = set()

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn omp --mode rpc and start reading stdout."""
        if self._proc is not None:
            return

        # ponytail: prefer `omp` in PATH, fall back to `bun x @oh-my-pi/pi-coding-agent`
        omp_bin = shutil.which("omp")
        if omp_bin:
            cmd = [omp_bin, "--mode", "rpc"]
        else:
            bun_bin = shutil.which("bun")
            if bun_bin:
                cmd = [bun_bin, "x", "@oh-my-pi/pi-coding-agent", "--mode", "rpc"]
            else:
                raise RuntimeError("omp not found in PATH and bun not available")

        cwd = os.environ.get("OMP_CWD", os.getcwd())
        logger.info("Starting omp RPC session %s: %s (cwd=%s)", self.session_id, " ".join(cmd), cwd)

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ, "PI_NO_PTY": "1", "PI_NO_TITLE": "1"},
        )

        # Start stderr drain (log omp internal errors)
        asyncio.create_task(self._drain_stderr())

        # Start stdout reader
        self._reader_task = asyncio.create_task(self._read_stdout())

        # Wait for ready signal
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=30)
        except TimeoutError:
            await self.stop()
            raise RuntimeError("omp did not send ready signal within 30s") from None

        logger.info("omp RPC session %s ready", self.session_id)

        # Register XHS host tools right after ready
        await self.register_host_tools(XHS_HOST_TOOLS)

    async def stop(self) -> None:
        """Gracefully shut down omp subprocess."""
        if self._proc is None:
            return

        proc = self._proc
        self._proc = None

        # Cancel reader
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        self._reader_task = None

        # Cancel host tool tasks
        for task in self._host_tool_tasks.values():
            if not task.done():
                task.cancel()
        self._host_tool_tasks.clear()
        self._auto_executed_ids.clear()

        # SIGTERM -> wait 5s -> SIGKILL
        if proc.returncode is None:
            try:
                proc.send_signal(signal.SIGTERM)
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                proc.kill()
                await proc.wait()

        # Cancel pending responses
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("omp session stopped"))
        self._pending.clear()

        logger.info("omp RPC session %s stopped", self.session_id)

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set() and self._proc is not None

    # ── High-level API (called by WebSocket handler) ─────────────────────

    def on_event(self, callback: Callable[[dict[str, Any]], Coroutine[None, None, None]]) -> None:
        """Register callback for translated frontend events."""
        self._event_callbacks.append(callback)

    def remove_event_callback(
        self, callback: Callable[[dict[str, Any]], Coroutine[None, None, None]]
    ) -> None:
        """Remove a previously registered event callback."""
        with contextlib.suppress(ValueError):
            self._event_callbacks.remove(callback)

    async def send_message(self, message: str) -> None:
        """Translate frontend send_message -> omp prompt command."""
        await self._write_cmd({"type": "prompt", "message": message})

    async def get_status(self) -> AgentStatus:
        """Translate frontend get_status -> omp get_state command."""
        resp = await self._request({"type": "get_state"})
        data = resp.get("data", {})
        return AgentStatus(
            is_streaming=data.get("isStreaming", False),
            model=data.get("model", {}).get("id", ""),
            session_id=data.get("sessionId", ""),
        )

    async def new_session(self) -> None:
        """Translate frontend new_session -> omp new_session command."""
        await self._request({"type": "new_session"})

    async def abort(self) -> None:
        """Translate frontend abort -> omp abort command."""
        await self._write_cmd({"type": "abort"})

    # ── Host tool mechanism ──────────────────────────────────────────────

    async def register_host_tools(self, tools: list[dict[str, Any]]) -> None:
        """Register host tools with omp. Sends set_host_tools command."""
        await self._request({"type": "set_host_tools", "tools": tools})

    async def send_host_tool_result(
        self,
        call_id: str,
        result: dict[str, Any],
        is_error: bool = False,
    ) -> None:
        """Send host_tool_result back to omp stdin after executing a host tool."""
        cmd: dict[str, Any] = {"type": "host_tool_result", "id": call_id, "result": result}
        if is_error:
            cmd["isError"] = True
        await self._write_cmd(cmd)

    async def send_host_tool_update(self, call_id: str, partial_result: dict[str, Any]) -> None:
        """Send streaming partial result for a host tool call."""
        await self._write_cmd(
            {"type": "host_tool_update", "id": call_id, "partialResult": partial_result}
        )

    async def send_extension_ui_response(self, ui_id: str, response: dict[str, Any]) -> None:
        """Forward frontend extension_ui_response back to omp stdin."""
        cmd: dict[str, Any] = {"type": "extension_ui_response", "id": ui_id, **response}
        await self._write_cmd(cmd)

    # ── Internal: NDJSON I/O ─────────────────────────────────────────────

    async def _write_cmd(self, cmd: dict[str, Any]) -> None:
        """Write NDJSON command to omp stdin."""
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("omp process not running")
        line = json.dumps(cmd, ensure_ascii=False) + "\n"
        try:
            self._proc.stdin.write(line.encode())
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            logger.warning("omp stdin write failed for session %s: %s", self.session_id, e)
            raise RuntimeError("omp process communication failed") from e

    async def _request(self, cmd: dict[str, Any]) -> dict[str, Any]:
        """Send command with correlation ID, wait for matching response."""
        self._cmd_id += 1
        cmd_id = f"req_{self._cmd_id}"
        cmd["id"] = cmd_id

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[cmd_id] = fut

        await self._write_cmd(cmd)

        try:
            return await asyncio.wait_for(fut, timeout=30)
        finally:
            self._pending.pop(cmd_id, None)

    async def _read_stdout(self) -> None:
        """Read NDJSON from omp stdout, dispatch events/responses."""
        if not self._proc or not self._proc.stdout:
            return
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                logger.warning("omp stdout closed for session %s", self.session_id)
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("omp sent non-JSON for session %s: %s", self.session_id, line[:200])
                continue
            await self._handle_omp_output(obj)

    async def _handle_omp_output(self, obj: dict[str, Any]) -> None:
        """Route omp output to ready signal, pending responses, or event translation."""
        msg_type = obj.get("type")

        # Ready signal
        if msg_type == "ready":
            self._ready.set()
            await self._emit({"type": ServerEventType.READY, "session_id": self.session_id})
            return

        # Command response (correlated by id)
        if msg_type == "response":
            cmd_id = obj.get("id")
            if cmd_id and cmd_id in self._pending:
                fut = self._pending[cmd_id]
                if not fut.done():
                    fut.set_result(obj)
            # Emit error to frontend if command failed (no matching pending or failure)
            success = obj.get("success")
            if success is False:
                command = obj.get("command", "")
                error_msg = obj.get("error", f"Command {command} failed")
                await self._emit(
                    {
                        "type": ServerEventType.ERROR,
                        "message": error_msg,
                        "command": command,
                    }
                )
            return

        # Agent events -> translate to high-level frontend events
        await self._translate_event(obj)

    # ── Event translation (omp AgentEvent -> frontend events) ────────────

    async def _translate_event(self, event: dict[str, Any]) -> None:
        """Translate omp AgentEvent to high-level frontend event(s)."""
        etype = event.get("type")

        if etype == "message_start":
            msg = event.get("message", {})
            self._current_msg_id = msg.get("id", "")
            self._current_msg_text = ""
            await self._emit(
                {
                    "type": ServerEventType.AGENT_MESSAGE,
                    "text": "",
                    "message_id": self._current_msg_id,
                    "done": False,
                }
            )

        elif etype == "message_update":
            msg = event.get("message", {})
            full_text = ""
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    full_text += block.get("text", "")
            delta = full_text[len(self._current_msg_text) :]
            self._current_msg_text = full_text
            if delta:
                await self._emit(
                    {
                        "type": ServerEventType.AGENT_MESSAGE,
                        "text": delta,
                        "message_id": self._current_msg_id,
                        "done": False,
                    }
                )

        elif etype == "message_end":
            await self._emit(
                {
                    "type": ServerEventType.AGENT_MESSAGE,
                    "text": "",
                    "message_id": self._current_msg_id,
                    "done": True,
                }
            )
            self._current_msg_id = ""
            self._current_msg_text = ""

        elif etype == "tool_execution_start":
            await self._emit(
                {
                    "type": ServerEventType.TOOL_CALL,
                    "tool_call_id": event.get("toolCallId", ""),
                    "tool_name": event.get("toolName", ""),
                    "args": event.get("args", {}),
                    "intent": event.get("intent", ""),
                }
            )

        elif etype == "tool_execution_end":
            await self._emit(
                {
                    "type": ServerEventType.TOOL_RESULT,
                    "tool_call_id": event.get("toolCallId", ""),
                    "tool_name": event.get("toolName", ""),
                    "result": event.get("result"),
                    "is_error": event.get("isError", False),
                }
            )

        elif etype == "agent_start":
            await self._emit(
                {
                    "type": ServerEventType.STATUS,
                    "status": "running",
                }
            )

        elif etype == "agent_end":
            await self._emit(
                {
                    "type": ServerEventType.STATUS,
                    "status": "idle",
                }
            )
            await self._emit({"type": ServerEventType.SESSION_END})

        elif etype == "host_tool_call":
            await self._handle_host_tool_call(event)

        elif etype == "host_tool_cancel":
            await self._handle_host_tool_cancel(event)

        elif etype == "extension_ui_request":
            await self._handle_extension_ui_request(event)

        elif etype in (
            "auto_compaction_start",
            "auto_compaction_end",
            "auto_retry_start",
            "auto_retry_end",
        ):
            # ponytail: skip compaction/retry events for MVP
            pass

        elif etype == "notice":
            level = event.get("level", "info")
            if level in ("warning", "error"):
                await self._emit(
                    {
                        "type": ServerEventType.ERROR,
                        "message": event.get("message", ""),
                        "level": level,
                    }
                )

    # ── Host tool call handling ──────────────────────────────────────────

    async def _handle_host_tool_call(self, event: dict[str, Any]) -> None:
        """Handle host_tool_call: auto-execute known XHS tools, forward unknown."""
        call_id = event.get("id", "")
        tool_call_id = event.get("toolCallId", "")
        tool_name = event.get("toolName", "")
        arguments = event.get("arguments", {})

        if tool_name in _XHS_TOOL_NAMES:
            # Auto-execute known XHS tool in backend
            self._auto_executed_ids.add(call_id)
            task = asyncio.create_task(
                self._auto_execute_host_tool(call_id, tool_name, arguments),
            )
            self._host_tool_tasks[call_id] = task
            # Also emit a tool_call event so frontend shows the tool being invoked
            await self._emit(
                {
                    "type": ServerEventType.TOOL_CALL,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "args": arguments,
                    "intent": "auto-executed",
                }
            )
        else:
            # Unknown tool -> forward to frontend for execution
            await self._emit(
                {
                    "type": ServerEventType.HOST_TOOL_CALL,
                    "id": call_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                }
            )

    async def _auto_execute_host_tool(
        self,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        """Auto-execute a known XHS host tool and send result back to omp."""
        try:
            result = await _execute_xhs_host_tool(tool_name, arguments)
            is_error = result.get("isError", False)
            await self.send_host_tool_result(call_id, result, is_error=is_error)
            # Emit tool_result to frontend so it shows completion
            await self._emit(
                {
                    "type": ServerEventType.TOOL_RESULT,
                    "tool_call_id": "",
                    "tool_name": tool_name,
                    "result": result,
                    "is_error": is_error,
                    "auto_executed": True,
                }
            )
        except Exception as e:
            logger.exception("auto-execute host tool %s failed", tool_name)
            error_result = _make_text_result(f"Auto-execution failed: {e}", None, is_error=True)
            await self.send_host_tool_result(call_id, error_result, is_error=True)
        finally:
            self._host_tool_tasks.pop(call_id, None)
            self._auto_executed_ids.discard(call_id)

    async def _handle_host_tool_cancel(self, event: dict[str, Any]) -> None:
        """Handle host_tool_cancel from omp: cancel pending host tool task."""
        target_id = event.get("targetId", "")
        task = self._host_tool_tasks.pop(target_id, None)
        if task and not task.done():
            task.cancel()
        # Only forward cancel to frontend for unknown tools (not auto-executed ones)
        is_auto_executed = target_id in self._auto_executed_ids
        self._auto_executed_ids.discard(target_id)
        if not is_auto_executed:
            await self._emit(
                {
                    "type": ServerEventType.HOST_TOOL_CALL,
                    "id": event.get("id", ""),
                    "method": "cancel",
                    "target_id": target_id,
                }
            )

    # ── Extension UI request handling ────────────────────────────────────

    async def _handle_extension_ui_request(self, event: dict[str, Any]) -> None:
        """Handle extension_ui_request from omp: forward to frontend for user interaction."""
        await self._emit(
            {
                "type": ServerEventType.EXTENSION_UI_REQUEST,
                "id": event.get("id", ""),
                "method": event.get("method", ""),
                "title": event.get("title", ""),
                "options": event.get("options", []),
                "message": event.get("message", ""),
                "placeholder": event.get("placeholder", ""),
                "prefill": event.get("prefill", ""),
                "prompt_style": event.get("promptStyle", False),
                "timeout": event.get("timeout"),
            }
        )

    async def _emit(self, event: dict[str, Any]) -> None:
        """Push translated event to all registered callbacks."""
        # Add session_id to all events so frontend can route
        event.setdefault("session_id", self.session_id)
        for cb in self._event_callbacks:
            try:
                await cb(event)
            except Exception:
                logger.exception("event callback error for session %s", self.session_id)

    async def _drain_stderr(self) -> None:
        """Log omp stderr for debugging."""
        if not self._proc or not self._proc.stderr:
            return
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            logger.debug(
                "omp stderr [%s]: %s",
                self.session_id,
                line.decode(errors="replace").rstrip(),
            )


# ── OmpBridgeManager — singleton managing multiple OmpSessions ────────────

_DEFAULT_IDLE_TIMEOUT = 300  # 5 minutes


class OmpBridgeManager:
    """Manages multiple OmpSession instances, keyed by session_id.

    Sessions start on-demand (first WebSocket connection) and stop after
    idle timeout. On manager shutdown, all sessions are stopped.
    """

    def __init__(self, idle_timeout: int = _DEFAULT_IDLE_TIMEOUT) -> None:
        self._sessions: dict[str, OmpSession] = {}
        self._idle_timers: dict[str, asyncio.Task[None]] = {}
        self._idle_timeout = idle_timeout

    async def start(self) -> None:
        """Start the manager. No sessions are started yet (on-demand)."""
        logger.info("OmpBridgeManager started (idle_timeout=%ds)", self._idle_timeout)

    async def stop(self) -> None:
        """Stop all sessions and the manager."""
        # Cancel all idle timers
        for timer_task in self._idle_timers.values():
            if not timer_task.done():
                timer_task.cancel()
        self._idle_timers.clear()

        # Stop all sessions
        for session in self._sessions.values():
            with contextlib.suppress(Exception):
                await session.stop()
        self._sessions.clear()

        logger.info("OmpBridgeManager stopped")

    async def get_or_create_session(self, session_id: str | None = None) -> OmpSession:
        """Get an existing session or create a new one.

        If session_id is None, generates a new UUID and starts a new session.
        If session_id is provided and exists, cancels its idle timer and returns it.
        If session_id is provided but doesn't exist, creates a new session with that ID.
        """
        if session_id and session_id in self._sessions:
            # Cancel idle timer on reconnect
            timer = self._idle_timers.pop(session_id, None)
            if timer and not timer.done():
                timer.cancel()
            return self._sessions[session_id]

        # Create new session
        if not session_id:
            session_id = f"omp_{uuid.uuid4().hex[:8]}"
        session = OmpSession(session_id)
        await session.start()
        self._sessions[session_id] = session
        logger.info("Created omp session %s", session_id)
        return session

    def start_idle_timer(self, session_id: str) -> None:
        """Start idle timer for a session. Called on WebSocket disconnect."""
        # Cancel existing timer if any
        existing = self._idle_timers.pop(session_id, None)
        if existing and not existing.done():
            existing.cancel()

        async def _idle_timeout() -> None:
            await asyncio.sleep(self._idle_timeout)
            session = self._sessions.pop(session_id, None)
            if session:
                logger.info("Idle timeout for session %s, stopping", session_id)
                with contextlib.suppress(Exception):
                    await session.stop()

        self._idle_timers[session_id] = asyncio.create_task(_idle_timeout())

    def cancel_idle_timer(self, session_id: str) -> None:
        """Cancel idle timer for a session. Called on WebSocket reconnect."""
        timer = self._idle_timers.pop(session_id, None)
        if timer and not timer.done():
            timer.cancel()

    def get_session(self, session_id: str) -> OmpSession | None:
        """Get an existing session without creating a new one."""
        return self._sessions.get(session_id)

    @property
    def session_ids(self) -> list[str]:
        return list(self._sessions.keys())


# ── Singleton ─────────────────────────────────────────────────────────────

_manager: OmpBridgeManager | None = None


def get_bridge_manager() -> OmpBridgeManager:
    """Get or create the singleton OmpBridgeManager."""
    global _manager
    if _manager is None:
        _manager = OmpBridgeManager()
    return _manager
