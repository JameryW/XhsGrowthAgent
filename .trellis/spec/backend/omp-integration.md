# OMP Extension & Web TUI Integration Contracts

> Cross-layer API contracts between oh-my-pi extension / Web TUI frontend and the XhsGrowthAgent backend API.

---

## Scenario: omp RPC Bridge (Web TUI ↔ Backend ↔ omp)

### 1. Scope / Trigger

- Web TUI connects to backend via WebSocket for AI agent interaction
- Backend manages `omp --mode rpc` subprocess(es) via `OmpBridgeManager`
- High-level protocol: frontend never sees raw omp NDJSON
- Multi-session: each user/session gets its own omp subprocess

### 2. Signatures

**WebSocket**: `WS /api/agent/ws?session_id=<optional>`

**Frontend → Backend** (`ClientMessageType`):
| Type | Fields | Description |
|------|--------|-------------|
| `send_message` | `content: string` | Natural language prompt → omp `prompt` command |
| `get_status` | — | Query agent state → omp `get_state` command |
| `new_session` | — | Create new omp session, switch to it |
| `abort` | — | Cancel current agent turn → omp `abort` command |
| `host_tool_result` | `id, result, is_error?` | Frontend-executed host tool result → omp `host_tool_result` |
| `extension_ui_response` | `id, value?/confirmed?/cancelled?` | User's response to extension UI request → omp `extension_ui_response` |

**Backend → Frontend** (`ServerEventType`):
| Type | Key Fields | Description |
|------|------------|-------------|
| `ready` | — | omp process ready |
| `agent_message` | `text, message_id, done` | Streaming AI text (delta; `done=true` on final) |
| `tool_call` | `tool_call_id, tool_name, args, intent?` | omp built-in tool started |
| `tool_result` | `tool_call_id, tool_name, result, is_error` | omp built-in tool finished |
| `host_tool_call` | `id, toolCallId, toolName, arguments` | Unknown host tool needs frontend execution |
| `extension_ui_request` | `id, method, title, options?/message?/placeholder?/prefill?` | Extension wants UI interaction |
| `status` | `status, model?, session_id?` | Agent status change (`idle`/`running`/`streaming`/`connected`) |
| `error` | `message, level?` | Error event |
| `session_end` | — | Agent turn completed |

### 3. Contracts

**Host Tool Auto-Execution**:
- Known XHS tools (`xhs_workflow_status`, `xhs_workflow_pause`, `xhs_workflow_resume`, `xhs_workflow_cancel`, `xhs_review_approve`, `xhs_review_reject`, `xhs_publish_retry`, etc.) are **auto-executed by the backend** via internal API calls (httpx to `localhost:8000/api/...`)
- `xhs_workflow_start` is intentionally **not exposed** to OMP free orchestration. The fixed workflow is launched only from the Simple Mode UI; OMP focuses on free orchestration for creation, evaluation, and publishing.
- Unknown host tools are forwarded to frontend as `host_tool_call` event
- Frontend must respond with `host_tool_result` message for unknown tools

**Extension UI Methods**:
| Method | Fields | Frontend Action |
|--------|--------|-----------------|
| `select` | `title, options[]` | Show picker, respond with `{value: selected}` |
| `confirm` | `title, message` | Show confirm dialog, respond with `{confirmed: true/false}` |
| `input` | `title, placeholder?` | Show input field, respond with `{value: input}` |
| `editor` | `title, prefill?` | Show editor, respond with `{value: edited_text}` |
| `cancel` | `targetId` | Cancel a previous request |
| `notify` | `message, notifyType?` | Show notification (no response needed) |

**Multi-Session**:
- `OmpBridgeManager` singleton manages `OmpSession` instances keyed by `session_id`
- Sessions start on-demand (first WebSocket connection)
- Idle timeout (default 5 min): starts on WebSocket disconnect, cancelled on reconnect
- `OMP_CWD` env var: working directory for omp subprocess (default: `os.getcwd()`)
- `OMP_IDLE_TIMEOUT` env var: idle timeout in seconds (default: 300)

**Session Lifecycle**:
1. Frontend connects `WS /api/agent/ws` → backend creates new `OmpSession` → spawns `omp --mode rpc`
2. omp sends `{"type":"ready"}` → backend registers XHS host tools → frontend receives `ready` + `status: connected`
3. Frontend sends `send_message` → omp processes → streaming `agent_message`/`tool_call`/`tool_result` events
4. Frontend disconnects → backend starts idle timer
5. Idle timeout expires → backend stops omp subprocess (SIGTERM → 5s → SIGKILL)
6. Frontend reconnects with `?session_id=xxx` → if session still alive, resume; else create new

### 4. Validation & Error Matrix

| Condition | Error Event | Behavior |
|-----------|-------------|----------|
| omp not in PATH / bun unavailable | `error` on startup | Bridge not started (non-fatal) |
| omp doesn't send ready within 30s | `error` | Session creation fails |
| Empty `send_message` content | `error` | "empty message" |
| Unknown `type` in frontend message | `error` | "unknown message type: X" |
| omp response `success: false` | `error` | Error message forwarded to frontend |
| omp subprocess crashes | `error` | stdout reader exits, pending requests cancelled |
| Host tool auto-execution API fails | `host_tool_result` with `is_error: true` | Error result sent back to omp |
| `host_tool_result` with non-dict result | Wrapped as `{content: [{type: "text", text: str(result)}]}` | Type safety for omp protocol |
| WebSocket reconnect after max retries | Falls back to command mode | Frontend shows command mode UI |

### 5. Good/Base/Bad Cases

**Good**: Connect → send "帮我写一篇母婴笔记" → streaming agent_message with draft content and evaluation guidance → optional tool_call (`xhs_evaluation_result` / `xhs_publish_retry` for an existing thread) auto-executed → tool_result → session_end

**Base**: Connect → get_status → receives `{status: "idle", model: "claude-sonnet-4-20250514", session_id: "..."}`

**Bad**: Connect → send_message with empty content → receives `{type: "error", message: "empty message"}`

**Bad**: Connect → host_tool_result with string result → auto-wrapped to `{content: [{type: "text", text: "the string"}]}`

### 6. Tests Required

- [ ] OmpSession: start/stop lifecycle, ready signal detection
- [ ] OmpSession: send_message → omp prompt command written to stdin
- [ ] OmpSession: get_status → omp get_state response parsed
- [ ] OmpSession: host_tool_call for known XHS tool → auto-executed via internal API
- [ ] OmpSession: host_tool_call for unknown tool → forwarded to frontend
- [ ] OmpSession: extension_ui_request → translated with method/title/options
- [ ] OmpSession: message_update delta calculation (streaming text)
- [ ] OmpBridgeManager: get_or_create_session creates on first call
- [ ] OmpBridgeManager: idle timer starts on disconnect, cancelled on reconnect
- [ ] OmpBridgeManager: stop_all shuts down all sessions
- [ ] agent.py: WebSocket session_id query param routes to correct session
- [ ] agent.py: NEW_SESSION creates new session, moves callbacks, starts idle timer on old

### 7. Wrong vs Correct

#### Wrong: Forwarding all host_tool_call to frontend
```python
# Every tool call requires frontend round-trip — slow and breaks agent flow
await self._emit({"type": "host_tool_call", ...})
```

#### Correct: Auto-execute known tools, forward only unknown ones
```python
if tool_name in _XHS_TOOL_NAMES:
    await self._auto_execute_host_tool(event)
else:
    await self._emit({"type": "host_tool_call", ...})
```

#### Wrong: Single omp process for all users
```python
bridge = get_bridge()  # singleton — all users share one omp session
```

#### Correct: Per-session omp processes with idle cleanup
```python
manager = get_bridge_manager()
session = await manager.get_or_create_session(session_id)  # each user gets own omp
```

#### Wrong: Infinite WebSocket reconnect loop
```typescript
ws.onclose = () => { setTimeout(connectAgentWs, 3000) }  // loops forever
```

#### Correct: Bounded reconnect with fallback
```typescript
if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
  reconnectAttempts++
  setTimeout(connectAgentWs, 3000)
} else { mode.value = 'command' }  // fallback
```

---

## Scenario: External Client Integration (omp extension + Web TUI)

### 1. Scope / Trigger

- Any external client (omp extension, Web TUI, third-party) calling the XhsGrowthAgent API
- All API responses are wrapped in `ApiResponse` envelope: `{ success, data, error }`
- Clients must unwrap the envelope to access actual data
- SSE endpoint sends **named events** (not anonymous messages)

### 2. Signatures

**API Base**: `http://localhost:8000/api` (configurable via `XHS_AGENT_API_BASE`)

| Tool | Method | Path | Request Body | Response (data field) |
|------|--------|------|-------------|----------------------|
| xhs_workflow_start | POST | `/workflow/start` | `{ account_id, workflow_mode, topic?, phase?, dry_run?, async_mode? }` | `{ thread_id, status, phase, progress_percent?, sse_url? }` |
| xhs_workflow_status | GET | `/workflow/status/{id}` | — | `{ thread_id, phase, status, current_agent, next_steps, progress_percent, ... }` |
| xhs_workflow_pause | POST | `/workflow/pause/{id}` | — | `{ thread_id, status }` |
| xhs_workflow_resume | POST | `/workflow/resume/{id}` | `{ resume_value? }` | `{ thread_id, status, phase }` |
| xhs_workflow_cancel | POST | `/workflow/cancel/{id}` | — | `{ thread_id, status, message }` |
| xhs_publish_retry | POST | `/workflow/publish-retry/{id}` | — | `{ thread_id, status, message }` |
| xhs_review_approve | POST | `/review/submit/{id}` | `{ decision: "approved", comments? }` | `{ thread_id, status, decision }` |
| xhs_review_reject | POST | `/review/submit/{id}` | `{ decision: "needs_revision", comments }` | `{ thread_id, status, decision }` |
| Health check | GET | `/system/health` | — | `{ status, ... }` (inside envelope.data) |

**SSE Stream**: `GET /api/workflow/stream/{thread_id}`

### 3. Contracts

**Response Envelope** (every API response):
```json
{
  "success": true,
  "data": { ... },        // actual payload
  "error": null,
  "timestamp": "2026-06-27T12:00:00Z",
  "request_id": "..."
}
```

**Error Envelope**:
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ERROR_WORKFLOW_NOT_FOUND",
    "message": "Workflow 'xxx' not found",
    "details": { "thread_id": "xxx" }
  }
}
```

**Review Decision** (ContentStatus enum):
- `"approved"` → content passes review gate
- `"needs_revision"` → content sent back to copywriter with comments
- `"rejected"` → hard reject (not currently used in review flow)

**SSE Event Format** (named events, NOT anonymous). Event names use **dot-notation** matching `backend/realtime/events.py` `EventType` enum exactly — `addEventListener` is name-sensitive, so a mismatch silently drops the event (the `onmessage` fallback never fires for named events):

```
event: workflow.phase_changed
data: {"thread_id": "...", "phase": "creating", "current_agent": "copywriter"}

event: workflow.data_updated
data: {"thread_id": "...", "progress_percent": 45}

event: review.pending
data: {"thread_id": "...", "status": "awaiting_review"}

event: workflow.completed
data: {"thread_id": "...", "status": "completed"}
```

Full backend enum (`EventType`): `workflow.{started,phase_changed,agent_started,agent_completed,data_updated,paused,resumed,completed,error}`, `review.{pending,submitted,approved,rejected,needs_revision}`, `ripple.progress`, `analytics.{report_updated,cost_alert,performance_new}`, `evaluator.epoch_evolved`. Any SSE listener must subscribe to each named type explicitly via `addEventListener` — there is no catch-all.

**Environment Keys**:
| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `XHS_AGENT_API_BASE` | No | `http://localhost:8000` | API base URL (omp extension + TUI) |

### 4. Validation & Error Matrix

| Condition | Error Code | HTTP Status |
|-----------|-----------|-------------|
| Workflow not found | `ERROR_WORKFLOW_NOT_FOUND` | 404 |
| No pending review | `ERROR_REVIEW_NOT_PENDING` | 400 |
| Invalid review decision | `ERROR_REVIEW_DECISION_INVALID` | 400 |
| API unreachable | — | Connection refused |
| Wrong field name (`mode` vs `workflow_mode`) | `ERROR_VALIDATION_ERROR` | 400 |

### 5. Good/Base/Bad Cases

**Good**: `POST /workflow/start { account_id: "default", workflow_mode: "trend" }`
→ 200 `{ success: true, data: { thread_id: "xhs_default_abc", ... } }`

**Base**: `GET /workflow/status/nonexistent`
→ 404 `{ success: false, error: { code: "ERROR_WORKFLOW_NOT_FOUND", ... } }`

**Bad**: `POST /workflow/start { account_id: "default", mode: "trend" }` (wrong field name)
→ 400 `{ success: false, error: { code: "ERROR_VALIDATION_ERROR", ... } }`

**Bad**: `POST /review/submit/{id} { action: "approve" }` (wrong field names)
→ 400 `{ success: false, error: { code: "ERROR_REVIEW_DECISION_INVALID", ... } }`

### 6. Tests Required

- [ ] omp extension: envelope unwrapping — `data` field extracted, error thrown on `success: false`
- [ ] omp extension: review tool sends `{ decision: "approved" }` not `{ action: "approve" }`
- [ ] omp extension: start tool sends `workflow_mode` not `mode`
- [ ] omp extension: SSE listener uses `addEventListener(eventType)` not just `onmessage`
- [ ] Web TUI: SSE listener handles named events (`phase_changed`, `progress_update`, etc.)
- [ ] Web TUI: approve/reject calls `submitReview` not `resumeWorkflow`
- [ ] Web TUI: topic parameter passed to `startWorkflow`

### 7. Wrong vs Correct

#### Wrong: Accessing response fields directly without envelope unwrapping
```typescript
const result = await res.json() as WorkflowStartResponse;
const threadId = result.thread_id; // undefined! data is nested
```

#### Correct: Unwrap envelope then access data
```typescript
const envelope = await res.json() as ApiEnvelope;
if (!envelope.success) throw new Error(envelope.error?.message);
const result = envelope.data as WorkflowStartResponse;
const threadId = result.thread_id; // works
```

#### Wrong: Using onmessage for named SSE events
```typescript
eventSource.onmessage = (msg) => { /* never fires for named events */ }
```

#### Correct: Using addEventListener for each event type
```typescript
for (const type of SSE_EVENT_TYPES) {
  eventSource.addEventListener(type, (msg) => { /* fires correctly */ })
}
```

#### Wrong: Sending wrong review field names
```typescript
await post("/review/submit/" + id, { action: "approve", feedback })
```

#### Correct: Matching backend ReviewDecision model
```typescript
await post("/review/submit/" + id, { decision: "approved", comments: feedback })
```

---

## Convention: Two Parallel omp Tool Implementations — Cross-Audit on Every Fix

**What**: The omp integration has **two parallel tool implementations** that expose the same XHS host tools to omp:

1. **TypeScript extension** — `backend/omp/extensions/xhsagent-ext/src/tools/*.ts` (≈31 tools). Registered via the omp `ExtensionAPI`; calls the backend over HTTP using native `fetch`. Richer toolset (includes `evaluation_epochs/weights/samples/trend` the bridge lacks).
2. **Python host-tool bridge** — `backend/services/omp_bridge.py` (`XHS_HOST_TOOLS`, 27 tools, `_execute_xhs_host_tool`). Auto-executes known XHS tools server-side via `httpx` to `localhost:8000/api/...`; forwards unknown tools to the frontend as `host_tool_call`.

`tests/unit/services/test_omp_bridge.py` covers **only** the Python bridge. The TS extension has **no unit tests** — it relies on `npm run typecheck` (CI `omp-typecheck` job) and shape-conformance to the backend API.

**Why**: Because the two implementations evolved independently, a data-shape or logic bug fixed in one is frequently still present in the other. Discovered during `07-07-fix-omp-tool-impl-bugs`:
- `workflow_list` read `result.count` (TS ext) while backend returns `total` — the Python bridge already used `len(workflows)` and was correct. Bug existed only in TS ext.
- Evaluation dimension list in `xhs.ts` / `events.ts` system prompts drifted to 6 dims while backend has 9 — TS-only; bridge renders dims dynamically so it never drifted.

**How to apply**: When fixing a tool's logic, data shape, or field name in one implementation, **immediately cross-audit the same tool in the other implementation** for the same bug. Concretely:
1. Grep the tool name in both `backend/omp/extensions/xhsagent-ext/src/` and `backend/services/omp_bridge.py`.
2. Compare the field names / response-type / render logic against the backend route (`backend/api/routes/<area>.py`) — the backend route is the source of truth, NOT either implementation.
3. If only one implementation has a unit test, add an assertion covering the fixed field to the other's test (or add a shape-conformance test) so the drift cannot recur silently.

**Don't assume the bridge and TS ext are in sync.** They are not. The bridge is an intentional subset (no eval sub-tools); the TS ext is the superset. A field-shape mismatch in either is a silent bug until a tool call hits it at runtime — there is no compile-time guarantee that TS interface `X` matches the backend Pydantic model `Y`.

**Related**: [[backend/api/routes]] shapes; [[backend/realtime/events]] EventType enum for SSE names.
