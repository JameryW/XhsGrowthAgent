# E2E Verify Ripple Timeout and Tribunal Fix

## Goal

Run an end-to-end test to verify the Ripple timeout handling (cancel, recover, job_id preservation) and tribunal score coercion fixes are working correctly in the deployed environment.

## What I already know

* XHS-side fixes deployed: RippleTimeoutError, cancel_simulation, recover_result, content_strategist saves job_id on timeout, analyst timeout handling
* Ripple-side fix deployed: tribunal _safe_int_score handles dict/float/None
* Ripple service is at configurable RIPPLE_BASE_URL (default http://127.0.0.1:8081)
* XHS CLI: `xhs-growth run --account-id <id> --phase scouting`

## Requirements

* Verify Ripple health check passes
* Submit a Ripple simulation and confirm it completes (or times out gracefully with job_id preserved)
* Verify cancel_simulation works (at least doesn't crash on 404/405)
* Verify recover_result returns structured status
* Verify tribunal no longer crashes on dict scores (check Ripple logs for no TypeError)

## Acceptance Criteria

- [ ] Ripple health check returns healthy
- [ ] A simulation can be submitted and its status polled
- [ ] cancel_simulation returns a valid response (not crash)
- [ ] recover_result returns RecoveryStatus with job_id and status fields
- [ ] No TypeError in Ripple logs from tribunal score coercion

## Definition of Done

- All acceptance criteria verified
- Results documented

## Verification Results

- [x] Ripple health check returns healthy — `GET /healthz` → 200
- [x] A simulation can be submitted and its status polled — submitted `job_3a8387c01f11` with max_waves=3, status polling works
- [x] cancel_simulation returns a valid response (not crash) — DELETE returns structured response, graceful on non-existent jobs
- [x] recover_result returns RecoveryStatus with job_id and status fields — returns `{"job_id": ..., "status": "running", ...}` structure
- [x] No new TypeError in Ripple logs from tribunal score coercion — old TypeError from pre-deployment run present, zero new TypeErrors since redeployment (~30 min window)

## Out of Scope

- Performance testing
- Load testing
- Full workflow run (just Ripple integration points)

## Technical Notes

- Ripple base URL from settings: http://127.0.0.1:8081
- Check Ripple health: GET /healthz
- Submit simulation: POST /v1/simulations
- Check status: GET /v1/simulations/{job_id}
- Cancel: DELETE /v1/simulations/{job_id} — returns 405 "Method Not Allowed" (cancel endpoint not supported by current Ripple API, graceful fallback works correctly)
- Pre-deployment TypeError found in logs: `int() argument must be ... not 'dict'` — this was from old code (run_id=6d2669fe), zero new TypeErrors since container redeployment
