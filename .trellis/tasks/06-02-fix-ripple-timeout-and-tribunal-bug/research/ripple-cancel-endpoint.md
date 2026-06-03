# Research: Ripple CAS Cancel/Abort Endpoint

- **Query**: Does Ripple CAS simulation API have a cancel/abort/delete endpoint for running simulations?
- **Scope**: Internal (codebase search) + External (web search for similar APIs)
- **Date**: 2026-06-03

## Findings

### Internal Search Results

#### Files Found

| File Path | Description |
|---|---|
| `backend/tools/ripple/client.py` | LangChain tools wrapping Ripple HTTP API |
| `backend/services/ripple_service.py` | Service layer with retry, health check, fallback |
| `backend/tools/ripple/integration.py` | High-level async functions for agents |
| `backend/config/settings.py:69-80` | RippleSettings configuration class |
| `backend/agents/content_strategist.py:55-104` | Consumer of Ripple API with timeout handling |
| `tests/unit/tools/test_ripple.py` | Ripple tool tests |
| `tests/unit/services/test_ripple_service.py` | RippleService tests |

#### Known Ripple API Endpoints (from codebase)

From `backend/tools/ripple/client.py` and `backend/services/ripple_service.py`:

| Endpoint | Method | Purpose | Implementation |
|---|---|---|---|
| `/v1/simulations` | POST | Submit simulation | `ripple_predict_content_spread`, `ripple_validate_pmf`, `submit_simulation` |
| `/v1/simulations/{job_id}` | GET | Get status | `ripple_get_simulation_status`, `get_simulation_status` |
| `/v1/simulations/{job_id}/artifacts/output-json` | GET | Get result | `ripple_get_simulation_result`, `get_result` |
| `/v1/simulations/{job_id}/artifacts/compact-log` | GET | Get log | `ripple_get_simulation_log` |
| `/v1/simulations/{job_id}/report` | POST | Generate report | `ripple_generate_report`, `get_report` |
| `/healthz` | GET | Health check | `health_check` |

#### Cancel/Abort/Delete Search Results

**No cancel, abort, or delete endpoint references found in Ripple-related code.**

Searched patterns:
- `cancel`, `abort`, `delete`, `stop`, `kill` in `backend/tools/ripple/` and `backend/services/ripple_service.py`
- Result: No matches found

#### Current Timeout Handling (from `ripple_service.py:372-408`)

```python
async def wait_for_completion(
    self,
    job_id: str,
    poll_interval: float = 10.0,
    max_wait: float = 1800.0,
) -> dict[str, Any]:
    """Poll until simulation completes or timeout."""
    elapsed = 0.0
    while elapsed < max_wait:
        status = await self.get_simulation_status(job_id)
        state = status.get("status", "").lower()
        if state in ("completed", "done", "finished"):
            return status
        if state in ("failed", "error"):
            raise RuntimeError(f"Ripple simulation {job_id} failed")
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    raise TimeoutError(f"Ripple simulation {job_id} did not complete within {max_wait}s")
```

**Key observation**: When `TimeoutError` is raised, the job continues running on the Ripple server. No cleanup is performed.

#### Consumer Code (from `content_strategist.py:68-86`)

```python
async def _predict():
    try:
        return await asyncio.wait_for(
            self._ripple_predict(content_plan, max_wait=ripple_timeout),
            timeout=ripple_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Ripple spread prediction timed out after {ripple_timeout}s, skipping")
        return None  # Job continues on server, job_id not saved
```

**Key observation**: On timeout, the job_id is not saved. No cancel attempt is made.

### External Search Results

#### Ripple CAS Documentation

- No public documentation found at:
  - `https://ripple-cas.readthedocs.io` (404)
  - GitHub search for "ripple CAS simulation" found unrelated projects
- Ripple is not a pip package; it's an external HTTP service deployed at configurable `RIPPLE_BASE_URL`
- The Ripple service code lives in a separate repo (per PRD: `/app/ripple/agents/tribunal.py`)

#### Common Patterns for Simulation/Async Job Cancellation

| Pattern | Used By | Notes |
|---|---|---|
| `DELETE /jobs/{job_id}` | Kubernetes, AWS Batch, GCP Batch, Azure Batch | Most common RESTful pattern |
| `POST /jobs/{job_id}/cancel` | Ray, Dask, Celery, Airflow | Action-based, job may transition to "cancelling" state |
| `POST /simulations/{id}/stop` | VANTAGE CAS, AnyLogic Cloud | Explicit stop action |
| `PATCH /jobs/{job_id}` with `status="cancelled"` | Some REST-pure APIs | Less common, race condition issues |

#### Simulation Platform Examples

| Platform | Cancel Endpoint | Notes |
|---|---|---|
| VANTAGE CAS | `POST /simulations/{id}/stop`, `DELETE /simulations/{id}` | Both stop and delete |
| AnyLogic Cloud | `POST /api/experiments/{id}/stop` | No explicit delete, auto-expire |
| Simio | `POST /experiments/{id}/cancel`, `DELETE /experiments/{id}` | Both cancel and delete |
| NetLogo/BehaviorSpace | N/A (headless mode uses process signals) | No REST API |

### Best Practices for Client-Side Handling (When Cancel Endpoint Unknown)

1. **Timeout + Abandon**: Set client-side timeout, abandon job tracking
   - Job continues on server, but client stops waiting
   - Server should have TTL/auto-cleanup for orphaned jobs

2. **Job ID Tracking**: Store job_id with timeout timestamp
   - Background cleanup task can query old jobs later
   - If cancel endpoint exists, call it; otherwise mark as abandoned

3. **Graceful Degradation**: If cancel endpoint doesn't exist
   - Log warning, continue with fallback
   - Don't block user workflow on cleanup failure

4. **Health Check**: Before submitting new job, check if server is healthy
   - Reduces orphaned jobs from connection failures

## Caveats / Not Found

1. **No definitive answer on Ripple cancel endpoint**: The Ripple service API documentation is not publicly accessible. The codebase shows no evidence of a cancel endpoint being used or documented.

2. **Ripple service repo location unknown**: PRD mentions `/app/ripple/agents/tribunal.py` but the actual repository URL is not in the codebase.

3. **Recommendation**: Need to either:
   - Check Ripple service source code directly (if accessible)
   - Contact Ripple service maintainers
   - Test `DELETE /v1/simulations/{job_id}` and `POST /v1/simulations/{job_id}/cancel` endpoints empirically
   - Assume no cancel endpoint exists and implement client-side mitigation (job_id tracking, async recovery)

## Related Specs

- None found in `.trellis/spec/` (no Ripple-related specs exist)

## Recommendations for Implementation

Based on research findings, the PRD assumption "Ripple server exposes a cancel endpoint" is **unverified**. Implementation should:

1. **Add `cancel_simulation(job_id)` method** that attempts `DELETE /v1/simulations/{job_id}` with graceful fallback if 404/405
2. **Save `ripple_job_id` on timeout** even if cancel fails, for potential async recovery
3. **Add `recover_result(job_id)` method** to check if a timed-out job completed later
4. **Log all cancel attempts** with endpoint and response status for debugging
5. **Document that Ripple server should have TTL** for abandoned jobs (server-side requirement)
