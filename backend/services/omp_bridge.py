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
  Known XHS tools (xhs_workflow_start, etc.) are auto-executed by the backend
  via internal API calls. Unknown host tools are forwarded to the frontend.

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
# These are the 7 tools the omp agent can call via host_tool_call mechanism.

XHS_HOST_TOOLS: list[dict[str, Any]] = [
    {
        "name": "xhs_workflow_start",
        "label": "XHS Workflow Start",
        "description": ("Start a XHS content creation workflow with real-time SSE progress"),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "XHS account ID to run the workflow for",
                },
                "workflow_mode": {
                    "type": "string",
                    "enum": ["trend", "brief"],
                    "default": "trend",
                    "description": "Workflow mode: trend-based or brief-based",
                },
                "topic": {
                    "type": "string",
                    "description": "Topic or niche to focus on (optional)",
                },
                "async_mode": {
                    "type": "boolean",
                    "default": True,
                    "description": "Run workflow asynchronously with SSE progress",
                },
            },
            "required": ["account_id"],
        },
    },
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
]

# Names of XHS tools that the backend auto-executes
_XHS_TOOL_NAMES = {t["name"] for t in XHS_HOST_TOOLS}


async def _execute_xhs_host_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Auto-execute a known XHS host tool by calling the backend API internally.

    Uses httpx to call the FastAPI app's own endpoints, so no external HTTP needed.
    """
    import httpx

    api_base = os.environ.get("XHS_AGENT_API_BASE", "http://localhost:8000")
    url = f"{api_base}/api"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if tool_name == "xhs_workflow_start":
                body: dict[str, Any] = {
                    "account_id": arguments.get("account_id", "default"),
                    "workflow_mode": arguments.get("workflow_mode", "trend"),
                    "async_mode": arguments.get("async_mode", True),
                }
                if arguments.get("topic"):
                    body["topic"] = arguments["topic"]
                resp = await client.post(f"{url}/workflow/start", json=body)
                data = _unwrap_envelope(resp)
                text = (
                    f"Workflow started!\n"
                    f"Thread: {data.get('thread_id', '')}\n"
                    f"Phase: {data.get('phase', '')}\n"
                    f"Status: {data.get('status', '')}\n"
                    f"Mode: {arguments.get('workflow_mode', 'trend')}"
                )
                return _make_text_result(text, data)

            elif tool_name == "xhs_workflow_status":
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

            else:
                return _make_text_result(f"Unknown tool: {tool_name}", None, is_error=True)

    except Exception as e:
        logger.exception("host tool auto-execution failed for %s", tool_name)
        return _make_text_result(f"Failed: {e}", None, is_error=True)


def _unwrap_envelope(resp: Any) -> dict[str, Any]:
    """Unwrap the ApiResponse envelope {success, data, error}."""
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
