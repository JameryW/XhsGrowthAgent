"""Agent WebSocket route -- bridges frontend to omp RPC via OmpBridgeManager.

Frontend sends high-level messages:
  - send_message: natural language prompt
  - get_status: query agent state
  - new_session: reset conversation
  - abort: cancel current turn
  - host_tool_result: result of a host tool execution (unknown tools forwarded to frontend)
  - extension_ui_response: user's response to an extension UI request

Backend pushes translated events:
  - ready, agent_message, tool_call, tool_result, status, error, session_end
  - host_tool_call: unknown host tool needs frontend execution
  - extension_ui_request: extension wants user interaction

WebSocket URL: WS /api/agent/ws?session_id=xxx
  - session_id optional: if provided, reconnect to existing session
  - if omitted, creates a new session
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from backend.api.deps import get_current_user
from backend.api.responses import ApiResponse, success
from backend.services.omp_bridge import (
    ClientMessageType,
    OmpSession,
    ServerEventType,
    get_bridge_manager,
)

logger = logging.getLogger("xhs_growth.api.agent")

router = APIRouter()

# Application-level heartbeat: keeps the WebSocket busy during long silent
# stretches (host-tool execution, waiting on extension UI) so browsers,
# proxies, and container networks don't drop the connection mid-turn.
_HEARTBEAT_SECONDS = 25

# Coalesce concurrent free-mode prewarm requests (form mode select + submit).
_prewarm_tasks: dict[str, asyncio.Task[None]] = {}


@router.post("/api/agent/prewarm")
async def prewarm_agent_session(
    mode: Annotated[str, Query(description="omp session mode: free | workflow")] = "free",
    _user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Fire-and-forget omp session warm-up for free-creation entry latency.

    Returns immediately. The subprocess start (up to ~60s cold) runs in the
    background so selecting free mode on /start can overlap with form fill-in.
    """
    session_mode = mode if mode in ("free", "workflow") else "free"
    manager = get_bridge_manager()

    existing = _prewarm_tasks.get(session_mode)
    if existing is not None and not existing.done():
        return success(data={"status": "warming", "mode": session_mode})

    # Reuse a live ready session if one already exists for this mode.
    for sid in manager.session_ids:
        sess = manager.get_session(sid)
        if sess is not None and sess.mode == session_mode and sess.is_ready:
            return success(data={"status": "ready", "mode": session_mode, "session_id": sid})

    async def _warm() -> None:
        try:
            session = await manager.get_or_create_session(mode=session_mode)
            logger.info(
                "omp prewarm ready mode=%s session_id=%s",
                session_mode,
                session.session_id,
            )
        except Exception:
            logger.exception("omp prewarm failed mode=%s", session_mode)
        finally:
            _prewarm_tasks.pop(session_mode, None)

    _prewarm_tasks[session_mode] = asyncio.create_task(_warm())
    return success(data={"status": "warming", "mode": session_mode})


@router.websocket_route("/api/agent/ws")
async def agent_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint for AI Agent interaction via omp.

    Connects frontend to an omp session via the bridge manager.
    session_id query param: reconnect to existing session or create new one.
    """
    # Accept query params before accepting the websocket
    session_id_param = websocket.query_params.get("session_id")
    mode_param = websocket.query_params.get("mode", "workflow")
    # Reconnect replay cursor: seq of the last event the client received.
    try:
        last_seq = int(websocket.query_params.get("last_seq", "0") or 0)
    except ValueError:
        last_seq = 0

    await websocket.accept()
    manager = get_bridge_manager()

    # Get or create session. Capture the prior instance so we can tell the
    # frontend whether this connection RESUMED a live session or spawned a
    # fresh one behind a familiar session_id (server restart, dead-session
    # replacement) — replay cursors only survive a genuine resume.
    prior = manager.get_session(session_id_param) if session_id_param else None
    session: OmpSession | None = None
    try:
        session = await manager.get_or_create_session(session_id_param, mode=mode_param)
    except Exception as e:
        logger.exception("failed to start omp session")
        await websocket.send_json(
            {
                "type": ServerEventType.ERROR,
                "message": f"omp session failed: {e}",
            }
        )
        await websocket.close()
        return

    if not session.is_ready:
        await websocket.send_json({"type": ServerEventType.ERROR, "message": "omp not ready"})
        await websocket.close()
        return

    resumed = prior is not None and prior is session
    current_session_id = session.session_id

    # ponytail: send session_id to frontend so it can reconnect later
    await websocket.send_json(
        {
            "type": ServerEventType.STATUS,
            "status": "connected",
            "session_id": current_session_id,
            "resumed": resumed,
        }
    )

    # -- Bridge -> frontend event forwarder ────────────────────────────────
    send_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def on_bridge_event(event: dict[str, Any]) -> None:
        """Callback from OmpSession -- enqueue event for sending."""
        await send_queue.put(event)

    session.on_event(on_bridge_event)

    # Reconnect replay: enqueue the buffered events this client missed while
    # disconnected. Registration and current_seq read are synchronous, and
    # put_nowait never yields, so no live event can overtake the replayed
    # ones or be delivered twice (live events have seq > high_water). Only a
    # genuinely resumed session shares seq history with the client's cursor.
    if last_seq and resumed:
        for missed in session.events_after(last_seq, session.current_seq):
            send_queue.put_nowait(missed)

    # Task that drains send_queue -> websocket. Sends an application-level
    # ping after HEARTBEAT_SECONDS of silence so idle connections (e.g.
    # during long host-tool execution) are not dropped by intermediaries.
    async def sender() -> None:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(send_queue.get(), timeout=_HEARTBEAT_SECONDS)
                except TimeoutError:
                    event = {"type": "ping"}
                await websocket.send_json(event)
        except Exception as e:
            # Websocket closed mid-send; the receive loop surfaces the
            # disconnect. Log instead of dying silently.
            logger.debug("agent ws sender stopped (session %s): %s", current_session_id, e)

    sender_task = asyncio.create_task(sender())

    # -- Frontend -> bridge message loop ───────────────────────────────────
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                err = {"type": ServerEventType.ERROR, "message": "invalid JSON"}
                await websocket.send_json(err)
                continue

            msg_type = msg.get("type")

            try:
                if msg_type == "pong":
                    # Heartbeat reply — keeps the client->server direction
                    # busy; nothing else to do.
                    continue

                if msg_type == ClientMessageType.SEND_MESSAGE:
                    content = msg.get("content", "")
                    if not content:
                        err = {"type": ServerEventType.ERROR, "message": "empty message"}
                        await websocket.send_json(err)
                        continue
                    await session.send_message(content)

                elif msg_type == ClientMessageType.GET_STATUS:
                    status = await session.get_status()
                    await websocket.send_json(
                        {
                            "type": ServerEventType.STATUS,
                            "status": "streaming" if status.is_streaming else "idle",
                            "model": status.model,
                            "session_id": status.session_id,
                        }
                    )

                elif msg_type == ClientMessageType.NEW_SESSION:
                    # Create a new omp session and switch to it
                    # Preserve the connection's mode.  In free mode `/start`
                    # is implemented as new_session; falling back to the
                    # manager's workflow default would re-register all
                    # thread-bound tools after the user intentionally entered
                    # the isolated free tool set.
                    new_session = await manager.get_or_create_session(mode=session.mode)
                    # Remove callback from old session
                    session.remove_event_callback(on_bridge_event)
                    # Start idle timer on old session
                    manager.start_idle_timer(current_session_id)
                    # Add callback to new session
                    new_session.on_event(on_bridge_event)
                    session = new_session
                    current_session_id = new_session.session_id
                    await websocket.send_json(
                        {
                            "type": ServerEventType.STATUS,
                            "status": "idle",
                            "session_id": current_session_id,
                        }
                    )

                elif msg_type == ClientMessageType.ABORT:
                    await session.abort()

                elif msg_type == ClientMessageType.HOST_TOOL_RESULT:
                    # Frontend executed an unknown host tool, send result back to omp
                    call_id = msg.get("id", "")
                    raw_result = msg.get("result", {})
                    result = (
                        raw_result
                        if isinstance(raw_result, dict)
                        else {"content": [{"type": "text", "text": str(raw_result)}]}
                    )
                    is_error = msg.get("is_error", False)
                    await session.send_host_tool_result(call_id, result, is_error)

                elif msg_type == ClientMessageType.EXTENSION_UI_RESPONSE:
                    # Frontend responded to an extension_ui_request
                    ui_id = msg.get("id", "")
                    response = {}
                    # Build the appropriate response fields based on what frontend sends
                    if "value" in msg:
                        response["value"] = msg["value"]
                    elif "confirmed" in msg:
                        response["confirmed"] = msg["confirmed"]
                    elif "cancelled" in msg:
                        response["cancelled"] = msg["cancelled"]
                        if msg.get("timedOut"):
                            response["timedOut"] = True
                    await session.send_extension_ui_response(ui_id, response)

                else:
                    await websocket.send_json(
                        {
                            "type": ServerEventType.ERROR,
                            "message": f"unknown message type: {msg_type}",
                        }
                    )
            except Exception:
                logger.exception("agent ws handler error")
                # ponytail: raw str(e) to the websocket client leaks internals;
                # full detail is preserved in logger.exception above.
                await websocket.send_json(
                    {"type": ServerEventType.ERROR, "message": "internal error"}
                )

    except WebSocketDisconnect:
        logger.info("agent ws disconnected (session %s)", current_session_id)
    finally:
        sender_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender_task
        # Remove event callback from session
        if session:
            session.remove_event_callback(on_bridge_event)
        # Start idle timer -- session will be stopped after timeout if no reconnect
        if current_session_id:
            manager.start_idle_timer(current_session_id)
