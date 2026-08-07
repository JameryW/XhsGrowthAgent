# throttle public_telemetry prune DELETE per beacon

## Goal

`backend/db/public_telemetry.py:145-148` `record_event` runs a `DELETE FROM public_ux_events WHERE received_at < now - 30 days` on EVERY telemetry beacon (frontend `sendBeacon` from Dashboard/Analytics/Evaluation interactions). The prune DELETE scans `received_at` on each INSERT — redundant per-event write-load. Throttle to periodic (module-level timestamp gate) so DELETE runs at most once per N minutes, not per beacon. Saves 1 DELETE RT per beacon (most beacons skip).

## What I already know

- `record_event` (`:89`) — runs per beacon: INSERT (`:102`) + DELETE prune (`:145-148`). Pool-guarded (`is_pool_ready()` `:97`).
- DELETE: `DELETE FROM public_ux_events WHERE received_at < CURRENT_TIMESTAMP - INTERVAL '30 days'` (`:146-147`). Idempotent — running it 0 or N times in a window is equivalent (prune is best-effort cleanup).
- Frontend `sendBeacon` fires on Dashboard/Analytics/Evaluation interactions — moderate volume.
- Prune is best-effort telemetry cleanup — delaying prune from "exact 30 days" to "~30 days + up to N min" is acceptable (no correctness contract; table bounded by prune eventually running).
- `time.monotonic()` — use for throttle timestamp (clock-drift safe, monotonic). NOT `time.time()` (wall clock can jump backwards).
- Module-level mutable timestamp `_last_prune_ts: float = 0.0` — process-wide, safe for best-effort throttle (no cross-process coordination needed; multi-worker: each worker prunes at low freq, fine).
- Single db function, isolated, NOT shared graph path. Impact 3.

## Requirements

- Add module-level `_last_prune_ts: float = 0.0` + `_PRUNE_INTERVAL_S: float = 300.0` (5 min — configurable constant, NOT extracted to Settings per dead-config-extraction series being done; keep module constant Ponytail).
- In `record_event`, after INSERT: `now = time.monotonic()`; `if now - _last_prune_ts >= _PRUNE_INTERVAL_S:` → run DELETE + `_last_prune_ts = now`. Else skip DELETE.
- INSERT always runs (per beacon, required). Only DELETE throttled.
- Thread-safety: module-level float assignment is atomic in CPython (GIL); no lock needed for best-effort throttle (worst case: 2 workers prune same window = idempotent DELETE, harmless).
- Behavior: prune now runs ≤ once per 5 min instead of per beacon. Table bounded slightly less precisely (~30d + up to 5min retention), acceptable for best-effort telemetry.

## Acceptance Criteria

- [ ] `_last_prune_ts` + `_PRUNE_INTERVAL_S` module constants.
- [ ] `record_event` DELETE gated by `time.monotonic() - _last_prune_ts >= _PRUNE_INTERVAL_S`.
- [ ] INSERT always runs (per beacon).
- [ ] `time.monotonic()` used (not `time.time()`).
- [ ] Non-vacuous test: assert DELETE skipped on rapid successive beacons within interval, runs once when interval elapsed. Revert-then-fail.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest` green.

## Definition of Done

- Tests added (non-vacuous, revert-then-fail proven).
- Pre-push triple green.
- Behavior change documented (prune per-beacon → ≤ once per 5 min).
- PR off `origin/main`, separate-PR-per-feature.

## Technical Approach

**`backend/db/public_telemetry.py`:**

Add module constants (near top, after imports):
```python
import time

# Best-effort prune throttle: run the 30-day DELETE at most once per
# interval, not on every beacon. Idempotent DELETE; delaying prune by
# up to the interval is fine for best-effort telemetry cleanup.
_PRUNE_INTERVAL_S: float = 300.0
_last_prune_ts: float = 0.0
```
(Check if `time` already imported — likely yes.)

In `record_event` (`:145-148`), replace unconditional DELETE:
```python
        global _last_prune_ts
        now = time.monotonic()
        if now - _last_prune_ts >= _PRUNE_INTERVAL_S:
            await conn.execute(
                "DELETE FROM public_ux_events "
                "WHERE received_at < CURRENT_TIMESTAMP - INTERVAL '30 days'"
            )
            _last_prune_ts = now
```

`global` declaration needed to assign module-level `_last_prune_ts` inside function.

**Ponytail:** module constant `_PRUNE_INTERVAL_S=300.0` kept (NOT extracted to Settings — dead-config series done, this is a throttle tuning knob, low churn, Ponytail keeps module constant). `# ponytail: module-level float assign atomic under GIL; no lock for best-effort throttle` comment.

**Behavior change (documented):** prune per-beacon → ≤ once per 5 min. Table retention ~30d + up to 5min (was exactly 30d). Acceptable for best-effort telemetry (no correctness contract on exact retention).

## Test (non-vacuous, find existing telemetry test file)

Check `tests/unit/db/test_public_telemetry*.py` or `tests/unit/test_public_telemetry*.py`. Add:

`test_record_event_prune_throttled`:
- Mock `is_pool_ready` → True, mock pool/connection/execute.
- Call `record_event` twice rapidly (within `_PRUNE_INTERVAL_S`).
- Assert INSERT executed twice (per beacon) but DELETE executed ONCE (throttled on 2nd).
- Reset `_last_prune_ts` to 0 between test variants (or set `_last_prune_ts = time.monotonic() - _PRUNE_INTERVAL_S - 1` to force elapsed).
- `test_record_event_prune_runs_after_interval`: set `_last_prune_ts` far in past, call `record_event`, assert DELETE ran + `_last_prune_ts` updated.
- Revert-then-fail: remove throttle (restore unconditional DELETE) → `test_record_event_prune_throttled` FAILs (DELETE runs twice). Restore → PASS.

Mock `conn.execute` (AsyncMock) — track call_count + SQL match (INSERT vs DELETE by SQL string contains).

**MagicMock-TypeError trap:** N/A — `time.monotonic()` real, no Settings.

## Decision (ADR-lite)

**Context:** Per-beacon prune DELETE is redundant write-load. Prune is idempotent + best-effort.

**Decision:** Throttle DELETE to ≤ once per 5 min via module-level `time.monotonic()` gate. INSERT always per beacon. Ponytail module constant (no Settings extraction).

**Consequences:** Saves 1 DELETE RT per beacon (most skip). Table retention ~30d + up to 5min (acceptable for best-effort telemetry). Module-level float atomic under GIL (no lock). Multi-worker: each prunes low-freq, idempotent, harmless.

## Out of Scope

- Moving prune to scheduler (overkill Ponytail; throttle sufficient).
- Extracting `_PRUNE_INTERVAL_S` to Settings (dead-config series done; throttle knob low-churn, keep module constant).
- Other telemetry functions (`summarize_events`).
- Changing 30-day retention window.

## Technical Notes

- Files: `backend/db/public_telemetry.py` (`:89` `record_event`, `:145-148` DELETE).
- Test: `tests/unit/db/test_public_telemetry*.py` (find existing).
- `time.monotonic()` (not `time.time()`) — clock-drift safe.
- Module-level float atomic under GIL — no lock for best-effort throttle.
- `global` declaration to assign module-level var inside function.
- Re-evaluation (from #517 cdp_session_lock lesson): verified `record_event` is a real prod path (frontend sendBeacon → API → `record_event`), not dead code. Prune DELETE runs per beacon (not 0-caller dead default).
