# fix telemetry prune test monotonic CI flake

## Goal

`tests/unit/db/test_public_telemetry.py::test_record_event_prune_throttled` flakes on CI (`assert 0 == 1`, deletes=0). Root cause: the throttle test relies on the REAL `time.monotonic()` absolute value — `record_event` gate is `now - _last_prune_ts >= _PRUNE_INTERVAL_S` where `_last_prune_ts=0.0` after reset, so the gate is `now >= 300.0`. On CI runners where the process/container `time.monotonic()` can return < 300 (fresh sandbox/short uptime), the gate is False → DELETE never runs → deletes=0 → assertion fails.

Reproduced locally: mocking `time.monotonic` to return 250/251 → deletes=0 (CI failure).

This blocks PR #523 (CI inherits the flaky test from main).

## What I already know

- `record_event` (`backend/db/public_telemetry.py:156-163`): `global _last_prune_ts; now = time.monotonic(); if now - _last_prune_ts >= _PRUNE_INTERVAL_S: DELETE; _last_prune_ts = now`.
- `_PRUNE_INTERVAL_S = 300.0` module constant.
- Test `test_record_event_prune_throttled` (`test_public_telemetry.py:92`): resets `mod._last_prune_ts = 0.0`, calls `record_event` twice, asserts INSERT×2 + DELETE×1. First call gate: `now - 0 >= 300` → depends on real `time.monotonic()` ≥ 300. CI < 300 → gate False → no DELETE.
- Test `test_record_event_prune_runs_after_interval` (`:124`): sets `_last_prune_ts = time.monotonic() - _PRUNE_INTERVAL_S - 1.0`, asserts DELETE runs. This one is MORE robust (forces elapsed via the offset), but `record_event` still calls real `time.monotonic()` internally — if CI monotonic is tiny, `now - (_last_prune_ts)` could behave unexpectedly. Patching monotonic makes both deterministic.
- Local `time.monotonic()` ~7517450 (>>300) → always passes locally. CI runner may differ.

## Requirements

- Patch `time.monotonic` (via `backend.db.public_telemetry.time.monotonic`) in BOTH throttle tests so they do NOT depend on the real clock absolute value.
- `test_record_event_prune_throttled`: control the monotonic sequence so the first call elapses (gate True → DELETE + timestamp set) and the second call is within interval (gate False → skip). E.g. monotonic returns `[1000.0, 1000.1]` (or use a list pop side_effect): first `1000 - 0 >= 300` True, second `1000.1 - 1000 >= 300` False. Assert INSERT×2 + DELETE×1.
- `test_record_event_prune_runs_after_interval`: set `_last_prune_ts` to a fixed past value relative to a controlled `now`, e.g. patch monotonic to return `1000.0`, set `_last_prune_ts = 1000.0 - _PRUNE_INTERVAL_S - 1.0` (=699), call once → `1000 - 699 >= 300` True → DELETE + `_last_prune_ts = 1000`. Assert DELETE×1 + timestamp advanced.
- Keep `_last_prune_ts` reset at test start (module-state hygiene) — reset to 0.0 or the controlled past value.
- Production code (`record_event`) UNCHANGED — only test fix.
- Non-vacuous preserved: revert-then-fail still works (restore unconditional DELETE → throttled test asserts DELETE×2 not ×1).

## Acceptance Criteria

- [ ] Both throttle tests patch `backend.db.public_telemetry.time.monotonic` (no real-clock dependency).
- [ ] `test_record_event_prune_throttled` passes deterministically regardless of real monotonic value.
- [ ] `test_record_event_prune_runs_after_interval` passes deterministically.
- [ ] Revert-then-fail: restore unconditional DELETE → `test_record_event_prune_throttled` FAILs (DELETE×2). Restore throttle → PASS.
- [ ] Reproduce CI condition locally (mock monotonic < 300) — fixed tests still PASS (proves fix addresses root cause).
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest` green.
- [ ] Production `record_event` unchanged.

## Definition of Done

- Tests deterministic (no real-clock absolute-value dependency).
- Pre-push triple green.
- Revert-then-fail proven.
- PR off `origin/main`, separate-PR-per-feature.

## Technical Approach

**`tests/unit/db/test_public_telemetry.py`:**

`test_record_event_prune_throttled`:
```python
import backend.db.public_telemetry as mod

conn = MagicMock()
conn.execute = AsyncMock()
mod._last_prune_ts = 0.0

# Control the clock so the test does not depend on the real time.monotonic()
# absolute value (CI runners may return < _PRUNE_INTERVAL_S at process start).
clock = iter([1000.0, 1000.1])

event = {"event": "replay_select_to_render"}
with (
    patch("backend.db.public_telemetry.is_pool_ready", return_value=True),
    patch("backend.db.public_telemetry.get_pool", return_value=_mock_pool(conn)),
    patch("backend.db.public_telemetry.time.monotonic", side_effect=lambda: next(clock)),
):
    await mod.record_event(event)  # 1000 - 0 >= 300 → DELETE + ts=1000
    await mod.record_event(event)  # 1000.1 - 1000 < 300 → skip

executed = [call.args[0] for call in conn.execute.await_args_list]
inserts = [sql for sql in executed if "INSERT INTO public_ux_events" in sql]
deletes = [sql for sql in executed if "DELETE FROM public_ux_events" in sql]
assert len(inserts) == 2
assert len(deletes) == 1
```

`test_record_event_prune_runs_after_interval`:
```python
import backend.db.public_telemetry as mod

conn = MagicMock()
conn.execute = AsyncMock()

# Fixed clock; force elapsed by setting last prune one interval+1 in the past.
clock = iter([1000.0])
mod._last_prune_ts = 1000.0 - mod._PRUNE_INTERVAL_S - 1.0  # =699
before = mod._last_prune_ts

event = {"event": "replay_select_to_render"}
with (
    patch("backend.db.public_telemetry.is_pool_ready", return_value=True),
    patch("backend.db.public_telemetry.get_pool", return_value=_mock_pool(conn)),
    patch("backend.db.public_telemetry.time.monotonic", side_effect=lambda: next(clock)),
):
    await mod.record_event(event)  # 1000 - 699 >= 300 → DELETE + ts=1000

executed = [call.args[0] for call in conn.execute.await_args_list]
deletes = [sql for sql in executed if "DELETE FROM public_ux_events" in sql]
assert len(deletes) == 1
assert mod._last_prune_ts > before
```

**Ponytail:** `iter([...])` + `lambda: next(clock)` is the shortest deterministic clock. No new helpers.

## Test (non-vacuous)

Revert-then-fail (trellis-check independently re-proves):
- Restore unconditional DELETE in `record_event` (remove throttle gate) → `test_record_event_prune_throttled` asserts `len(deletes) == 1` but gets 2 (both calls DELETE) → FAIL.
- Restore throttle → PASS.

Also verify the fix addresses root cause: with the OLD test (no monotonic patch) + mocked monotonic < 300, test FAILs. With NEW test (monotonic patched to 1000) + same mocked-monotonic environment, test PASSes. (Implicit — the patched test no longer reads real clock.)

## Decision (ADR-lite)

**Context:** Throttle test depended on real `time.monotonic()` ≥ 300. CI runners can return < 300 (fresh sandbox) → gate False → flaky fail.

**Decision:** Patch `time.monotonic` in both throttle tests to control the clock deterministically. Production code unchanged.

**Consequences:** Tests deterministic across environments. No production behavior change. Revert-then-fail still valid (throttle gate presence/absence is what the test checks, independent of clock source).

## Out of Scope

- Changing `record_event` production logic (throttle correct).
- Extracting `_PRUNE_INTERVAL_S` to Settings (Ponytail module constant, per #522).
- Other telemetry tests (summary/ensure_tables — no clock dependency).

## Technical Notes

- File: `tests/unit/db/test_public_telemetry.py` (`:92` throttled, `:124` runs_after_interval).
- Repro: `time.monotonic` mocked to 250/251 → `record_event` gate `250 - 0 >= 300` False → deletes=0 (CI failure reproduced locally).
- Patch target: `backend.db.public_telemetry.time.monotonic` (module-level `time` import in public_telemetry.py).
- Blocks PR #523 (CI inherits flaky test from main).
