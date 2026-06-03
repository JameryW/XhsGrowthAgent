# Fix Ripple Timeout Handling and Tribunal Score Bug

## Goal

Fix the identified issues causing Ripple simulations to hang, timeout without cleanup, and crash on dict scores — so that XHS workflows reliably get Ripple data or clean fallbacks without orphaned jobs. Covers XHS-side timeout handling (cancel, recover, job_id tracking), tribunal score coercion, analyst agent wiring, and extensible recover API.

## What I already know

* XHS side: `content_strategist.py:19` sets `_RIPPLE_TIMEOUT = 900`, uses `asyncio.wait_for` to timeout, but never cancels the Ripple job or saves the job_id for later recovery
* `RippleService` has no `cancel_simulation` method — only submit, poll, get_result, get_report
* `wait_for_completion` (ripple_service.py:372-408) raises `TimeoutError` after `max_wait`, but the job keeps running on Ripple server
* Tribunal/DELIBERATE/SYNTHESIZE code lives in the Ripple service repo (`/app/ripple/agents/tribunal.py`), not in XHS repo
* The `int(v)` TypeError in tribunal.py occurs when LLM returns `{score: 3, reason: "..."}` instead of a plain int
* SYNTHESIZE phase has no prompt size / max_tokens / timeout limits — it's the main bottleneck for the 3 stuck jobs
* **Ripple API has no known cancel endpoint** — no DELETE or POST cancel found in codebase or public docs (see research/ripple-cancel-endpoint.md)
* `content_strategist.py:68-86` catches `asyncio.TimeoutError` but returns `None` — job_id is lost
* `ripple_service.py:410-432` `submit_and_wait` returns full result including job_id, but the caller discards it on timeout
* `integration.py` wraps RippleService calls but has no cancel/recover functions
* `client.py` has LangChain @tool wrappers for submit/status/result/log/report — no cancel tool

## Assumptions (temporary)

* ~~Ripple server exposes a cancel/abort endpoint~~ — **Disproven**: no evidence found. Will implement graceful attempt with fallback.
* If no cancel endpoint exists, we can only save job_id for async recovery
* Tribunal fix requires a PR to the Ripple service repo (separate from XHS changes)
* Ripple service repo changes (Fix #1, #3, #4, #5) are out of scope for this XHS task — they need separate PRs to the Ripple repo

## Open Questions

* ~~**Scope boundary**: Should this task only cover XHS-side fixes (Fix #2), or also the Ripple service repo changes (Fix #1, #3, #4, #5)?~~ — **Resolved**: XHS + tribunal hotfix (Fix #2 + Fix #3). Fix #4, #5 are separate efforts. Fix #1 requires Ripple repo changes that are out of scope.

## Requirements

### Fix #1: Ripple server-side hard timeout per phase/job
- **Scope**: Ripple service repo (not XHS) — **likely out of scope for this task**
- Add configurable hard timeout to each simulation phase (PROPAGATE, DELIBERATE, OBSERVE, SYNTHESIZE)
- When timeout expires, mark job as `timed_out` (not leave as `running`)
- Default: SYNTHESIZE ≤ 300s, other phases ≤ 600s each, total job ≤ 1800s

### Fix #2: XHS timeout → cancel job or async recovery
- **Scope**: XHS repo (`ripple_service.py`, `content_strategist.py`, `analyst` agent)
- Add `cancel_simulation(job_id)` method to `RippleService` — attempts DELETE, graceful fallback on 404/405
- After XHS timeout, attempt to cancel the Ripple job
- Save `ripple_job_id` in result even on timeout, so late results can be recovered
- Add `recover_result(job_id)` method for async recovery of late-completing jobs
- **Extensibility**: Design `recover_result` API to support future background polling (return structured status, not just raw data)
- **Analyst wiring**: Also wire cancel/recover into the analyst agent flow for `ripple_get_simulation_result` and `ripple_generate_report` calls

### Fix #3: Tribunal score coercion — handle dict + catch TypeError
- **Scope**: Ripple service repo (`tribunal.py`) — **IN SCOPE for this task**
- Replace `int(v)` with a `_coerce_score(v)` helper that handles:
  - `int` → pass through
  - `dict` with `score` key → extract `v["score"]`
  - `str` → try `int(v)`
  - Fallback → 0 with warning log
- Wrap in try/except TypeError/ValueError

### Fix #4: SYNTHESIZE limits (prompt size, max_tokens, timeout)
- **Scope**: Ripple service repo — **likely out of scope for this task**
- Truncate observation data fed to SYNTHESIZE prompt (max chars configurable)
- Set `max_tokens` on SYNTHESIZE LLM call
- Add per-phase timeout (default 300s for SYNTHESIZE)

### Fix #5: Structured JSON output for LLM calls
- **Scope**: Ripple service repo (multiple agents) — **likely out of scope for this task**
- Use `response_format={"type": "json_object"}` or equivalent for agents that return JSON
- Add JSON schema validation on parse
- Fallback: if structured output fails, retry with explicit "return valid JSON only" instruction

## Acceptance Criteria

- [ ] `RippleService.cancel_simulation(job_id)` method exists and is called on XHS timeout
- [ ] `RippleService.recover_result(job_id)` method exists for async recovery, returns structured status for future polling
- [ ] `content_strategist.py` saves `ripple_job_id` in result even on timeout
- [ ] `analyst.py` has timeout handling for `_ripple_report` and saves job_id on timeout
- [ ] Tribunal `_coerce_score` handles int, dict, str, and unexpected types
- [ ] Existing tests pass; new tests for cancel, recovery, timeout job_id preservation, score coercion
- [ ] (Out of scope) SYNTHESIZE has configurable prompt size limit, max_tokens, and timeout
- [ ] (Out of scope) LLM agents use structured JSON output where possible
- [ ] (Out of scope) Ripple jobs that exceed hard timeout are marked `timed_out`, not left `running`

## Definition of Done

- Tests added/updated (unit/integration where appropriate)
- Lint / typecheck / CI green
- Docs/notes updated if behavior changes
- Rollout/rollback considered if risky

## Out of Scope

- Rewriting the entire Ripple simulation pipeline
- Changing the XHS workflow graph topology
- Optimizing Ripple simulation speed (separate effort)
- Ripple service repo changes (Fix #1, #4, #5) — need separate PRs to that repo
- SYNTHESIZE limits and structured JSON output (Fix #4, #5) — separate effort after this task

## Technical Notes

### Files to modify (XHS repo)
- `backend/services/ripple_service.py` — add cancel_simulation, recover_result
- `backend/agents/content_strategist.py` — save job_id on timeout, call cancel
- `backend/agents/analyst.py` — add timeout handling for _ripple_report, save job_id
- `backend/tools/ripple/integration.py` — expose cancel/recover functions
- `backend/tools/ripple/client.py` — add cancel tool

### Files to modify (Ripple service repo — IN SCOPE for tribunal fix)
- `/app/ripple/agents/tribunal.py` — _coerce_score helper

### Files to modify (Ripple service repo — separate PRs, out of scope)
- SYNTHESIZE phase code — add limits
- LLM agent base — structured JSON output
- Job lifecycle — hard timeout per phase

### Ripple API endpoints (known)
- `POST /v1/simulations` — submit
- `GET /v1/simulations/{job_id}` — status
- `GET /v1/simulations/{job_id}/artifacts/output-json` — result
- `POST /v1/simulations/{job_id}/report` — report
- Cancel endpoint: **unknown** — will attempt DELETE optimistically

### Research References
- [`research/ripple-cancel-endpoint.md`](research/ripple-cancel-endpoint.md) — No cancel endpoint found in codebase or public docs; implement optimistic DELETE with graceful fallback

## Decision (ADR-lite)

**Context**: Scope boundary — 5 fixes span 2 repos. Only XHS repo is checked out.
**Decision**: Implement Fix #2 (XHS-side: cancel, recover, job_id preservation) + Fix #3 (tribunal _coerce_score). Also wire cancel/recover into analyst agent. Design recover_result API for future background polling extensibility. Fix #1, #4, #5 are documented as follow-up tasks.
**Consequences**: XHS workflows will save job_id on timeout and attempt cancel. Analyst will have timeout protection. Tribunal won't crash on dict scores. SYNTHESIZE bottlenecks and structured JSON remain unaddressed until follow-up PRs.

## Technical Approach

### RippleService changes (ripple_service.py)

1. **`cancel_simulation(job_id)`**: Attempt `DELETE /v1/simulations/{job_id}`, catch 404/405/network errors gracefully, log outcome. Returns `{"cancelled": bool, "job_id": str, "status": str}`.

2. **`recover_result(job_id)`**: Check job status via `GET /v1/simulations/{job_id}`. If completed, fetch result via `get_result()`. Returns structured `RecoveryStatus` with `job_id`, `status` (completed/timed_out/running/failed), and `result` (if available). This structure supports future background polling — a polling task just calls `recover_result` and acts on `status`.

3. **`wait_for_completion` enhancement**: Return job_id from `submit_and_wait` even on timeout — currently `submit_and_wait` raises TimeoutError with no job_id in the exception. Change to raise a `RippleTimeoutError(job_id)` that carries the job_id.

### Content strategist changes (content_strategist.py)

4. **Save job_id on timeout**: In `_predict()` and `_validate_pmf()`, catch the timeout, extract job_id from the exception, save it in result dict as `ripple_job_id` and `ripple_reason: "timeout"`. Then call `cancel_simulation(job_id)`.

5. **`_ripple_predict` / `_ripple_validate_pmf` refactor**: Instead of returning None on timeout, return `{"ripple_job_id": job_id, "ripple_reason": "timeout"}` so the caller can save it.

### Analyst changes (analyst.py)

6. **`_ripple_report` timeout**: Add `asyncio.wait_for` with a configurable timeout (default 120s for report generation). On timeout, log warning and return None (report is nice-to-have, not critical). If job_id is known, attempt cancel.

### Integration layer (integration.py)

7. **`cancel_simulation(job_id)`**: Thin wrapper around `RippleService.cancel_simulation`.
8. **`recover_result(job_id)`**: Thin wrapper around `RippleService.recover_result`.

### Client tools (client.py)

9. **`ripple_cancel_simulation` @tool**: LangChain tool wrapper for cancel.

### Tribunal fix (ripple service repo — tribunal.py)

10. **`_coerce_score(v)` helper**:
    ```python
    def _coerce_score(v) -> int:
        if isinstance(v, int):
            return v
        if isinstance(v, dict):
            return _coerce_score(v.get("score", 0))
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                logger.warning(f"Cannot coerce score string: {v!r}")
                return 0
        logger.warning(f"Unexpected score type: {type(v).__name__}, value: {v!r}")
        return 0
    ```
    Replace all `int(v)` calls in tribunal score handling with `_coerce_score(v)`.

## Implementation Plan (small PRs)

- **PR1**: RippleService — add `cancel_simulation`, `recover_result`, `RippleTimeoutError`; update `submit_and_wait` to carry job_id on timeout
- **PR2**: Content strategist — save job_id on timeout, call cancel, refactor _predict/_validate_pmf
- **PR3**: Analyst — add timeout handling for _ripple_report
- **PR4**: Integration + client tools — expose cancel/recover in integration.py and client.py
- **PR5**: Tribunal — add `_coerce_score` helper (separate repo PR)
- **PR6**: Tests — new unit tests for cancel, recovery, timeout job_id preservation, score coercion
