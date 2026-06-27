# OMP Extension & Web TUI Integration Contracts

> Cross-layer API contracts between oh-my-pi extension / Web TUI frontend and the XhsGrowthAgent backend API.

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

**SSE Event Format** (named events, NOT anonymous):
```
event: phase_changed
data: {"thread_id": "...", "phase": "creating", "current_agent": "copywriter"}

event: progress_update
data: {"thread_id": "...", "progress_percent": 45}

event: review_requested
data: {"thread_id": "...", "status": "awaiting_review"}

event: workflow_completed
data: {"thread_id": "...", "status": "completed"}
```

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
