# Ripple Service Integration Spec

Cross-layer contracts between XHS workflows and Ripple CAS simulation service.

## Scenario: Ripple Simulation Lifecycle

### 1. Scope / Trigger

XHS agents (`content_strategist`, `analyst`) call Ripple for content spread prediction and PMF validation. The simulation lifecycle now has server-side hard timeouts, structured JSON output, and prompt truncation that affect how XHS should handle results.

### 2. Signatures

```python
# XHS side (RippleService)
async def submit_and_wait(simulation_input: dict, max_wait: float = 1800) -> dict
async def cancel_simulation(job_id: str) -> dict[str, Any]
async def recover_result(job_id: str) -> RecoveryStatus

# Ripple side (API)
POST   /v1/simulations                    → {"job_id": str, "status": "running"}
GET    /v1/simulations/{job_id}           → {"job_id": str, "status": str, ...}
POST   /v1/simulations/{job_id}/cancel-request → {"cancel_token": str}
POST   /v1/simulations/{job_id}/cancel-confirm → {"status": "cancelling" | ...}
DELETE /v1/simulations/{job_id}           → legacy fallback only
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

#### Environment Variables (XHS side)

| Key | Default | Purpose |
|-----|---------|---------|
| `RIPPLE_REQUEST_TIMEOUT` | 300 | HTTP request timeout for individual Ripple calls |
| `RIPPLE_WORKFLOW_TIMEOUT` | 1800 | Max wait for a submitted Ripple simulation inside XHS workflows |

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
# status: "cancelled" | "cancelling" | "not_found" | "not_supported" | "not_cancellable" | "error"
```

XHS should use the current two-step cancel protocol first:
1. `POST /cancel-request` to receive a `cancel_token`
2. `POST /cancel-confirm` with that token

If `cancel-request` returns 405, XHS may fall back to legacy `DELETE`. Cancel is best-effort, never fatal.

#### output-json Result Shapes

XHS must parse both the legacy metrics shape and the current Ripple artifact shape.

Legacy shape:

```python
{
    "job_id": "job_...",
    "output": {
        "metrics": {
            "estimated_reach": 5000,
            "total_engagement": 800,
            "viral_probability": 0.35,
            "confidence": 0.85,
        },
        "phase_analysis": {"phase": "growth", "spread_path": [...]},
    },
}
```

Current shape:

```python
{
    "job_id": "job_...",
    "prediction": {
        "impact": "...",
        "relative_estimate": {
            "views_relative": "+15%~+30%",
            "engagements_relative": "+25%~+45%",
            "confidence": "medium",
        },
        "verdict": "growth",
    },
    "timeline": [...],
    "observation": {"phase_vector": {"heat": "growth", ...}},
    "bifurcation_points": [...],
    "agent_insights": {...},
}
```

When absolute reach/engagement metrics are absent, XHS should not synthesize `estimated_reach = 0` or `estimated_engagement = 0`. Preserve relative fields (`views_relative`, `engagements_relative`, etc.), `prediction_summary`, `verdict`, `phase_vector`, `total_waves`, and mark derived numeric scores with `score_source = "derived_from_verdict"`.

### 4. Validation & Error Matrix

| Condition | Ripple Response | XHS Handling |
|-----------|-----------------|--------------|
| Job completes within XHS timeout | `completed` | Normal flow |
| Job exceeds configured XHS wait timeout but Ripple still running | `running` | `RippleTimeoutError` → cancel_simulation → save job_id → fallback |
| Job completes with current relative-estimate output | `completed` + `prediction.relative_estimate` | Parse relative fields; do not treat missing absolute metrics as fallback |
| Job exceeds Ripple phase timeout | `timed_out` | Fallback (no recovery possible) |
| Job exceeds Ripple job timeout (1800s) | `timed_out` | Fallback |
| LLM returns malformed JSON | Retried by Ripple with robust parser | Transparent to XHS |
| cancel-request on running job | `cancel_token` | confirm cancellation, log result, continue with fallback |
| cancel-request on completed/failed/missing job | 404/409 | Log, continue with fallback |
| cancel-request unsupported by legacy Ripple | 405 | Try legacy DELETE, then continue with fallback |

### 5. Good/Base/Bad Cases

- **Good**: Job completes within `RIPPLE_WORKFLOW_TIMEOUT`, XHS gets result before fallback
- **Base**: XHS is configured with a shorter wait timeout, saves `job_id` on timeout, and later `recover_result` finds completed result
- **Bad**: Job hangs indefinitely (pre-fix: stuck at `running`; post-fix: timed_out at 1800s)

### 6. Tests Required

- XHS side: `test_ripple_timeout_saves_job_id`, `test_cancel_simulation_success`, `test_cancel_simulation_legacy_delete_success`, `test_cancel_simulation_not_supported`, `test_recover_result_completed`, `test_recover_result_timed_out`, `test_parse_spread_result_current_ripple_shape`, `test_parse_pmf_result_current_ripple_shape`
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

## Design Decision: Two-Step Cancel with Graceful Fallback

**Context**: Current Ripple API uses a two-step cancellation handshake. Older Ripple builds may only expose or reject the legacy DELETE route.

**Options Considered**:
1. Use `cancel-request` + `cancel-confirm`, falling back to DELETE only when the new endpoint returns 405
2. Skip cancel entirely, only save job_id for recovery
3. Always attempt DELETE and handle 405 gracefully

**Decision**: Option 1 — prefer the current Ripple protocol, keep DELETE as compatibility fallback.

**Consequences**: Timeout cleanup sends two HTTP calls on the successful cancel path. Cancellation remains best-effort and does not block fallback content generation.

## Design Decision: Structured JSON Output (json_mode)

**Context**: LLM agents in Ripple sometimes return malformed JSON, causing cascade of retries.

**Decision**: Enable `json_mode` for all 4 agents (omniscient, star, sea, tribunal). Uses `response_format={"type": "json_object"}` for chat completions, prefill `"\n{"` for Anthropic. Also use `parse_json_from_llm()` robust parser as fallback.

**Consequences**: Reduces JSON parse failures significantly. Some models may not support `response_format` — fallback to robust parser handles those cases.

## Gotcha: XHS timeout vs Ripple timeout gap

> **Warning**: Keep `RIPPLE_WORKFLOW_TIMEOUT` aligned with Ripple's job timeout unless there is a deliberate product reason to fall back earlier. A shorter XHS timeout creates a window where the Ripple job may still be running after XHS has fallen back.
>
> In this window, `recover_result(job_id)` can be used to check if the job eventually completed. The `ripple_job_id` field in content_strategist result must be preserved for this recovery path.
>
> After 1800s, Ripple marks the job as `timed_out` — no recovery possible after that point.

## Gotcha: Result parser contract drift

Ripple's current `output-json` may return qualitative and relative estimates instead of legacy absolute metrics. If XHS reads only `output.metrics`, completed jobs will appear as all-zero predictions and users will see a false "Ripple unavailable" state.

Correct behavior:
- Treat `prediction.relative_estimate` + `prediction.verdict` as valid completed data
- Derive display-only numeric scores from `verdict` when absolute probabilities are absent
- Keep `score_source = "derived_from_verdict"` so callers know the numeric field is not a raw Ripple metric
- Frontend fallback detection must check `ripple_reason`/relative fields, not only `viral_probability == 0`
