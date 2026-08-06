# Stop leaking raw exception text to API/websocket clients

## Goal

Three sites send raw `str(e)` (unhandled exception text) to the client —
internal paths, SQL errors, library traceback fragments, internal class names
reach the API JSON / websocket / frontend UI. Security + information-leakage
gap. The server-side logging side was already hardened (the `error-log-type-
name` series #471/#474 added `{type(e).__name__}` to logger.error); this PR
closes the **client-facing** side — log the full detail server-side, send a
generic message + request_id to the client.

## Confirmed leak sites

1. **`backend/api/middleware.py:37`** — catch-all 500 handler:
   ```python
   details={"exception": str(e)}
   ```
   Any unhandled exception (SQL error, internal path, library traceback
   fragment) lands in the client JSON response under `details.exception`.
   The `message` is already generic ("Internal server error") — only the
   `details.exception` leaks.

2. **`backend/api/routes/workflow.py:147→165`** — background task `task_done`
   callback:
   ```python
   task_error = str(e)              # line 147
   ...
   updates["error"] = task_error    # line 165 → DB `error` column
   ```
   `to_dict()` (db/workflows.py:64) exposes `error` directly → `/list` and
   `/status` JSON → frontend `WorkflowListItem.error?: string` (types/workflow
   .ts:319) → `workflow.ts:876 error.value = state?.error` → displayed in UI.
   Raw background-task exception text reaches the user.

3. **`backend/api/routes/agent.py:286`** — websocket handler:
   ```python
   await websocket.send_json({"type": ServerEventType.ERROR, "message": str(e)})
   ```
   Raw exception text sent to the websocket client.

## What I already know

- Server-side logging is already good: middleware.py:31 `logger.exception(...)`
  captures the full traceback; workflow.py:146 `logger.error("...: %s", e)`;
  agent.py:285 `logger.exception("agent ws handler error")`. The full detail is
  preserved server-side — only the client-facing copy leaks.
- The `error-log-type-name` series (#471 ripple, #474 XHS chain) added
  `{type(e).__name__}` to `logger.error` calls — but those were logging
  improvements, not client-response sanitization. This PR is the client side.
- `APIError` (handled at middleware.py:24) already sends curated
  `e.message` — NOT a leak. Only the catch-all `Exception` branch (line 30)
  leaks.
- The `accounts.py` `LoginError` cases (investigator flagged lines 337/399/435)
  are curated messages, lower risk — leave them.
- Frontend consumes `state?.error` (workflow.ts:876) for display — so the
  workflow.py fix must still send *something* human-readable to the `error`
  column (not empty), just not raw `str(e)`. A generic "后台任务异常，请联系
  管理员" or the exception class name without the message is appropriate.
- `request_id` (middleware.py:20) is already generated and sent to the client
  — the client can quote it for support to cross-ref server logs. So the
  generic client message + request_id is sufficient for diagnosability.

## Recommended approach (ponytail)

Three minimal sanitizations, each preserving server-side logging:

### Site 1: middleware.py:37
Drop the raw exception from client `details`; keep it in the logger (already
done by `logger.exception` at :31). Send only the request_id (already present)
so support can cross-ref.
```python
# before:
details={"exception": str(e)},
# after:
details=None,  # ponytail: don't leak raw exception text; request_id cross-refs server logs
```
Or omit the `details` kwarg entirely if `error()` tolerates None (check the
signature). ~1 line.

### Site 2: workflow.py:147
Replace raw `str(e)` in the DB `error` column with a generic message (the
column is user-visible via /list + /status). Keep `str(e)` in the logger
(already at :146).
```python
# before:
task_error = str(e)
# after:
task_error = "后台任务异常"  # ponytail: raw str(e) flows to DB error col → /list → UI; keep detail in logger only
```
~1 line. (Consider including `type(e).__name__` for slightly better
diagnosability without leaking internals — `f"后台任务异常: {type(e).__name__}"`
— matches the #471/#474 logging pattern. Decide: bare generic vs
generic+typename. Prefer generic+typename — gives operator a hint without
leaking the message/paths.)

### Site 3: agent.py:286
Replace `str(e)` with a generic message; keep `logger.exception` (already
:285).
```python
# before:
"message": str(e)
# after:
"message": "internal error"  # ponytail: raw str(e) to websocket client; detail in logger only
```
~1 line.

- Pros: closes a real information-leakage security gap. 3 one-line fixes.
  Server-side logging unchanged (full detail still captured for ops). Client
  gets generic message + request_id (middleware) for support cross-ref. Same
  family as the completed error-log-type-name series, now on the client side.
- Cons: clients lose the raw exception text in responses. This is the point
  (security) — but verify no frontend code *depends* on parsing `details.
  exception` or the raw `error` string (grep frontend for `.exception` /
  pattern-matching on `error`). If something does, it's already broken
  behavior (parsing exception text is fragile) — but flag it.

**Rejected: keep str(e) but truncate** — truncation still leaks the prefix
(paths, class names). Generic is correct.

**Rejected: add a new sanitization helper** — YAGNI; 3 one-line sites, inline
is clearer than a helper.

## Requirements

- No site sends raw `str(e)` to the client (API JSON, DB error column exposed
  via /list + /status, websocket message).
- Server-side logging unchanged — full `str(e)` / traceback still captured by
  `logger.exception` / `logger.error`.
- Client receives a generic message (site-dependent: "Internal server error"
  already there for middleware; "后台任务异常"[:typename] for workflow;
  "internal error" for ws). Middleware already sends request_id for cross-ref.
- No frontend code breaks (verify no consumer parses the raw exception text).

## Acceptance Criteria

- [ ] middleware.py catch-all 500 no longer includes `str(e)` in client
      `details`.
- [ ] workflow.py `task_error` written to DB `error` column is generic (not
      raw `str(e)`); logger still has full detail.
- [ ] agent.py websocket error message is generic (not raw `str(e)`).
- [ ] No frontend consumer breaks (grep + verify — no `.exception` parsing,
      no regex on raw `error` text).
- [ ] Tests: add/extend tests asserting the client-facing payload does NOT
      contain raw exception text (middleware 500 test, workflow task_error
      DB-write test, ws error test). Existing error-handling tests stay green.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- 3 one-line sanitizations (middleware, workflow, agent)
- Tests asserting no raw exception in client payloads
- Pre-push triple green
- PR off `origin/main`, separate branch

## Out of Scope

- `accounts.py` `LoginError` curated messages (already safe).
- Changing `APIError` handling (already sends curated `e.message`).
- Frontend changes (no UI change — the `error` field still renders, just with
  generic text now).
- Structured error codes / error-response redesign (separate effort).

## Technical Notes

- Files: `backend/api/middleware.py` (1 line), `backend/api/routes/workflow.py`
  (1 line), `backend/api/routes/agent.py` (1 line) + tests.
- Check `error()` signature in `backend/api/responses.py` — does `details=None`
  work, or should the kwarg be omitted? Match the happy-path calls.
- Grep frontend: `grep -rn "details\.exception\|\.exception\b" frontend/src/`
  and `grep -rn "error" frontend/src/stores/workflow.ts` — confirm no raw-text
  parsing.
- Existing tests: find via `grep -rln "error_handler_middleware\|INTERNAL_ERROR\|task_error\|task_done" tests/`.
- Pattern precedent: the `error-log-type-name` series (#471/#474) — same
  philosophy (preserve type name for ops, don't leak raw internals), now
  applied to client responses.

## Decision (ADR-lite)

**Context**: 3 sites send raw `str(e)` to clients (API 500 details, DB error
column → /list + /status → UI, websocket message). Information-leakage
security gap. Server-side logging already captures full detail.
**Decision**: sanitize each client-facing copy to a generic message (+
type(e).__name__ where it aids ops without leaking internals for the workflow
column); keep `str(e)` only in loggers. Middleware request_id already lets
support cross-ref server logs.
**Consequences**: clients lose raw exception text (the point). 3 one-line
fixes, low risk, no frontend change. Closes the client-facing side of the
error-handling work started by #471/#474.
