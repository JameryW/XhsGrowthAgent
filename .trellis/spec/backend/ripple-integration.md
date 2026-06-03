# Ripple Service Integration Spec

Cross-layer contracts between XHS workflows and Ripple CAS simulation service.

## Scenario: Ripple Simulation Lifecycle

### 1. Scope / Trigger

XHS agents (`content_strategist`, `analyst`) call Ripple for content spread prediction and PMF validation. The simulation lifecycle now has server-side hard timeouts, structured JSON output, and prompt truncation that affect how XHS should handle results.

### 2. Signatures

```python
# XHS side (RippleService)
async def submit_and_wait(simulation_input: dict, max_wait: float = 900) -> dict
async def cancel_simulation(job_id: str) -> dict[str, Any]
async def recover_result(job_id: str) -> RecoveryStatus

# Ripple side (API)
POST   /v1/simulations                    → {"job_id": str, "status": "running"}
GET    /v1/simulations/{job_id}           → {"job_id": str, "status": str, ...}
DELETE /v1/simulations/{job_id}           → 405 (not supported) or 204 (if supported in future)
GET    /v1/simulations/{job_id}/artifacts/output-json  → result dict
```

### 3. Contracts

#### Ripple Job Status Values

| Status | Meaning | XHS Action |
|--------|---------|------------|
| `running` | Simulation in progress | Poll or wait |
| `completed` | Simulation finished successfully | Fetch result |
| `failed` | Simulation errored out | Use fallback |
| `timed_out` | Simulation exceeded phase/job timeout (NEW) | Use fallback, job_id may be recoverable later |

#### Ripple Per-Phase Timeout Defaults (server-side)

| Phase | Timeout | Notes |
|-------|---------|-------|
| INIT | 60s | Setup phase |
| SEED | 30s | Initial seeding |
| RIPPLE | 1200s | Main propagation (max_waves controlled) |
| DELIBERATE | 600s | Tribunal evaluation |
| OBSERVE | 120s | Observation collection |
| SYNTHESIZE | 180s | Final result synthesis |
| **Job total** | **1800s** | Hard ceiling, marks `timed_out` on expiry |

#### Environment Variables (Ripple server)

| Key | Default | Purpose |
|-----|---------|---------|
| `RIPPLE_JOB_TIMEOUT` | 1800 | Overall job timeout in seconds |
| `RIPPLE_PHASE_TIMEOUTS_ENABLED` | true | Disable per-phase timeouts (backward compat) |
| `RIPPLE_SYNTHESIZE_MAX_SNAPSHOT_CHARS` | 20000 | Max chars for snapshot JSON in SYNTHESIZE prompt |
| `RIPPLE_SYNTHESIZE_MAX_OBS_CHARS` | 15000 | Max chars for observation JSON |
| `RIPPLE_SYNTHESIZE_MAX_INPUT_CHARS` | 5000 | Max chars for input JSON |

#### RecoveryStatus (XHS side)

```python
class RecoveryStatus(BaseModel):
    job_id: str
    status: str  # "completed" | "running" | "timed_out" | "failed" | "not_found"
    result: dict[str, Any] | None = None
    error: str = ""
```

#### cancel_simulation Response

```python
{"cancelled": bool, "job_id": str, "status": str}
# status: "cancelled" | "not_found" | "not_supported" | "error"
```

Currently Ripple API returns 405 on DELETE — `status="not_supported"`. Cancel is best-effort, never fatal.

### 4. Validation & Error Matrix

| Condition | Ripple Response | XHS Handling |
|-----------|-----------------|--------------|
| Job completes within XHS timeout | `completed` | Normal flow |
| Job exceeds XHS 900s timeout but Ripple still running | `running` | `RippleTimeoutError` → cancel_simulation → save job_id → fallback |
| Job exceeds Ripple phase timeout | `timed_out` | Fallback (no recovery possible) |
| Job exceeds Ripple job timeout (1800s) | `timed_out` | Fallback |
| LLM returns malformed JSON | Retried by Ripple with robust parser | Transparent to XHS |
| DELETE on running job | 405 `not_supported` | Log, continue with fallback |
| DELETE on completed/failed job | 404 `not_found` | Log, continue with fallback |

### 5. Good/Base/Bad Cases

- **Good**: Job completes in 600s, XHS gets result before 900s timeout
- **Base**: Job takes 1000s, XHS times out at 900s but saves job_id, later `recover_result` finds completed result
- **Bad**: Job hangs indefinitely (pre-fix: stuck at `running`; post-fix: timed_out at 1800s)

### 6. Tests Required

- XHS side: `test_ripple_timeout_saves_job_id`, `test_cancel_simulation_not_supported`, `test_recover_result_completed`, `test_recover_result_timed_out`
- Ripple side: `test_phase_timeout_exceeded`, `test_job_timeout_exceeded`, `test_timed_out_status`, `test_json_mode_chat_completions`, `test_truncate_json_over_limit`

### 7. Wrong vs Correct

#### Wrong: Assuming Ripple jobs always complete or fail

```python
# Assumes job is either running or completed
status = await service.get_status(job_id)
if status["status"] == "completed":
    return status["result"]
else:
    return None  # Misses timed_out case
```

#### Correct: Handle all status values including timed_out

```python
status = await service.get_status(job_id)
if status["status"] == "completed":
    return status["result"]
elif status["status"] == "timed_out":
    logger.warning(f"Ripple job {job_id} timed out on server side")
    return None
elif status["status"] == "running":
    # May be recoverable later
    return None
else:  # failed, not_found
    return None
```

## Design Decision: Optimistic Cancel with Graceful Fallback

**Context**: Ripple API does not reliably support DELETE on running simulations (returns 405).

**Options Considered**:
1. Always attempt DELETE, handle 405 gracefully
2. Skip cancel entirely, only save job_id for recovery
3. Add a cancel endpoint to Ripple API first

**Decision**: Option 1 — attempt DELETE optimistically. The 405 response is harmless, and if Ripple adds cancel support in the future, XHS code works without changes.

**Consequences**: One extra HTTP call on timeout path (non-blocking). Future-proof if cancel is added.

## Design Decision: Structured JSON Output (json_mode)

**Context**: LLM agents in Ripple sometimes return malformed JSON, causing cascade of retries.

**Decision**: Enable `json_mode` for all 4 agents (omniscient, star, sea, tribunal). Uses `response_format={"type": "json_object"}` for chat completions, prefill `"\n{"` for Anthropic. Also use `parse_json_from_llm()` robust parser as fallback.

**Consequences**: Reduces JSON parse failures significantly. Some models may not support `response_format` — fallback to robust parser handles those cases.

## Gotcha: XHS timeout vs Ripple timeout gap

> **Warning**: XHS times out at 900s, but Ripple's job timeout is 1800s. There's a 900s window where the Ripple job is still running after XHS has fallen back.
>
> In this window, `recover_result(job_id)` can be used to check if the job eventually completed. The `ripple_job_id` field in content_strategist result must be preserved for this recovery path.
>
> After 1800s, Ripple marks the job as `timed_out` — no recovery possible after that point.
