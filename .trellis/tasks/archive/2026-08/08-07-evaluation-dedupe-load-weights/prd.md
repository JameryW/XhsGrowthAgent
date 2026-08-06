# dedupe load_weights in run_note_evaluation

## Goal

`backend/api/routes/evaluation.py:929,934` (`run_note_evaluation`) fetches the
same account weights **twice** in sequence on every manual `/evaluation/note`
POST (hot path):

```python
:928  try:
:929      await _evaluator._resolve_weights(account_id)        # calls load_weights(account_id) internally (evaluator.py:93)
:930      evaluator_fingerprint = _evaluator.evaluator_fingerprint()
:931  except Exception as exc:
:932      logger.debug("evaluator fingerprint resolution failed: %s", exc)
:933      evaluator_fingerprint = "rqgm:unknown"
:934  thresholds = await _score_thresholds(account_id)         # calls load_weights(account_id) AGAIN (evaluation.py:127)
```

`_resolve_weights` (evaluator.py:90) calls `load_weights(account_id)` → stores
`self._weights` → returns it. `_score_thresholds` (evaluation.py:106) calls
`load_weights(account_id)` **again** → reads only `pass_threshold` +
`reject_threshold`. Same DB row (evaluator_config table, account-scoped
overrides), two sequential awaits. Dedupe → 1 fetch.

## What I already know

- **`load_weights(account_id)`** (evaluator_config.py:189): fetches global +
  per-account overrides from `evaluator_config` table, returns
  `EvaluatorWeights` dataclass. Pure read, swallows own DB exc → returns
  defaults (`_fetch_overrides` :226-228 catches + returns `{}`).
- **`_resolve_weights(account_id)`** (evaluator.py:90): calls
  `load_weights(account_id)` (`:93`, try/except → defaults) **AND**
  `get_active_epoch()` (`:98`, separate DB row `evaluator_prompt_epochs`).
  Stores `self._weights` + `self._bias_severity`. Returns `self._weights`
  (`:103`). So `_resolve_weights` is heavier than just weights — it also
  fetches epoch. But the **weights portion is the duplicate** vs
  `_score_thresholds`.
- **`_score_thresholds(account_id)`** (evaluation.py:106): calls
  `load_weights(account_id)` (`:127`, try/except → defaults dict), returns
  `{"pass": weights.pass_threshold, "warn": weights.reject_threshold}`.
  Defaults from `DEFAULT_PASS_THRESHOLD`/`DEFAULT_REJECT_THRESHOLD` when pool
  not ready or fetch fails.
- **6 callers of `_score_thresholds`** (codegraph confirmed):
  `list_evaluated_workflows`, `get_evaluation_result`, `run_evaluation`,
  `run_note_evaluation`, `get_latest_note_evaluation`, `get_evaluator_trend`.
  **Cannot change `_score_thresholds` signature** — breaks 5 other callers.
- **`run_note_evaluation` is the ONLY caller that also calls `_resolve_weights`**
  (the others don't resolve weights — they just read thresholds for display).
  So dedupe is local to `run_note_evaluation`.
- **`_resolve_weights` return value currently discarded** at `:929`
  (`await _evaluator._resolve_weights(account_id)` — return not captured).
  It returns `self._weights` (`EvaluatorWeights`). The fingerprint at `:930`
  reads `self._weights` via `evaluator_fingerprint()`.
- **Both fetches swallow own exceptions** → defaults. Dedupe must preserve:
  fingerprint resolution failure → `"rqgm:unknown"` (`:931-933`); threshold
  resolution failure → defaults dict (`_score_thresholds` :128-130). These
  are **independent failure modes** (fingerprint also depends on
  `get_active_epoch`; thresholds don't). Must keep both try/except paths
  independent — do NOT merge into one try/except.

## Recommended approach (ponytail)

Capture the `EvaluatorWeights` from `_resolve_weights` and derive thresholds
from it directly — skip the second `load_weights` fetch inside
`_score_thresholds`. But `_score_thresholds` has 6 callers + its own
default-fallback logic (`is_pool_ready()` guard, DEFAULT_*_THRESHOLD). Don't
touch it. Instead:

**Add a tiny helper `_thresholds_from_weights(weights)`** that mirrors the
post-fetch body of `_score_thresholds` (`:131-134`):

```python
def _thresholds_from_weights(weights: EvaluatorWeights) -> dict[str, float]:
    return {
        "pass": float(weights.pass_threshold),
        "warn": float(weights.reject_threshold),
    }
```

Refactor `_score_thresholds` to use it (keeps 6 callers + default-fallback):

```python
async def _score_thresholds(account_id: str | None = None) -> dict[str, float]:
    defaults = {
        "pass": float(DEFAULT_PASS_THRESHOLD),
        "warn": float(DEFAULT_REJECT_THRESHOLD),
    }
    if not is_pool_ready():
        return defaults
    try:
        weights = await load_weights(account_id)
    except Exception:
        logger.exception(...)
        return defaults
    return _thresholds_from_weights(weights)
```

Then in `run_note_evaluation`, capture the resolved weights + derive
thresholds from them (no second fetch), keeping the two try/except paths
independent:

```python
:928  resolved_weights: EvaluatorWeights | None = None
      try:
          resolved_weights = await _evaluator._resolve_weights(account_id)
          evaluator_fingerprint = _evaluator.evaluator_fingerprint()
      except Exception as exc:
          logger.debug("evaluator fingerprint resolution failed: %s", exc)
          evaluator_fingerprint = "rqgm:unknown"
      if resolved_weights is not None:
          thresholds = _thresholds_from_weights(resolved_weights)
      else:
          thresholds = await _score_thresholds(account_id)
```

Wait — `_resolve_weights` swallows its own exceptions internally (evaluator.py
:94-96, :100-102) and **always returns** `self._weights` (never raises). So
the `except` at `:931` never fires from `_resolve_weights` itself... but
`evaluator_fingerprint()` (`:930`) could raise. So `resolved_weights` will
basically always be set after the try. But to be safe + keep the
fingerprint-failure path (`"rqgm:unknown"`) intact, the `if resolved_weights
is not None` guard handles the case where `_resolve_weights` itself raised
before assignment (defensive — currently can't happen but cheap).

Actually — simpler + correct: `_resolve_weights` always returns weights (swallows
internally). The only thing that can raise in the try is
`evaluator_fingerprint()`. So `resolved_weights` is always assigned. But keep
the guard for robustness (future-proof if `_resolve_weights` ever raises).
Thresholds then always derived from resolved weights — **zero second fetch**.

**Behavior preservation check:**
- Happy path: `_resolve_weights` fetches weights+epoch → fingerprint from
  weights. Thresholds from same weights. Same values as before (both fetched
  same row). ✅
- Fingerprint fails (`evaluator_fingerprint()` raises): `evaluator_fingerprint
  = "rqgm:unknown"`, `resolved_weights` still set (assigned before `:930`) →
  thresholds from resolved weights. **Before**: thresholds from
  `_score_thresholds` (re-fetch). Same values (same row) but 1 fewer fetch.
  ✅ (slightly different: before, if the re-fetch hit a DB error it'd return
  defaults; now thresholds come from the already-resolved weights which also
  fell back to defaults on DB error inside `_resolve_weights`. Net same
  default values, fewer round trips.)
- `_resolve_weights` DB error (can't happen — swallows internally): defensive
  guard → falls back to `_score_thresholds` re-fetch. ✅

**Net: ~1 fewer DB round trip per `/evaluation/note` POST.** ~6 LOC (helper +
capture + guard). Zero behavior change. Lowest-risk dedupe.

- Pros: 1 fewer DB RTT on hot manual-eval path; zero behavior change;
  `_score_thresholds` stays intact for 5 other callers; helper reused by
  `_score_thresholds` itself (DRY).
- Cons: tiny added helper (~3 LOC).

**Rejected: pass preloaded weights into `_score_thresholds`.** Would change
signature → break 5 other callers or require optional param + branching. More
invasive. Ponytail: local dedupe + shared helper is simpler.

**Rejected: merge the two try/except blocks.** They're independent failure
modes (fingerprint depends on epoch too; thresholds don't). Merging changes
behavior. Keep separate.

## Requirements

- `run_note_evaluation` fetches account weights **once** (via
  `_resolve_weights`), reuses for both fingerprint + thresholds.
- `_score_thresholds` unchanged for its 5 other callers (signature + behavior).
- New `_thresholds_from_weights` helper shared by `_score_thresholds` +
  `run_note_evaluation`.
- Fingerprint-failure path (`"rqgm:unknown"`) intact.
- Threshold default-fallback path intact (when `_resolve_weights` somehow
  returns None — defensive).
- Zero behavior change (same threshold values, same fingerprint).

## Acceptance Criteria

- [ ] `run_note_evaluation` calls `load_weights` (transitively) once, not twice.
- [ ] `_thresholds_from_weights` helper added; `_score_thresholds` refactored
      to use it (6 callers unaffected).
- [ ] Fingerprint-failure path + threshold-fallback path both intact.
- [ ] Existing evaluation tests pass unchanged.
- [ ] New non-vacuous test: assert `load_weights` called once (not twice) in
      `run_note_evaluation` happy path. Patch `load_weights`, assert
      call_count == 1. Must FAIL if reverted to 2 calls. Verify
      `test_evaluation_api.py` / `tests/integration/test_evaluation_api.py`
      coverage + mock shape during implement.
- [ ] `ruff format --check .` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- evaluation.py dedupe (~6 LOC: helper + capture + guard + `_score_thresholds` refactor)
- 1 non-vacuous dedupe test
- Pre-push triple green
- PR off `origin/main`, separate branch `perf/evaluation-dedupe-load-weights`

## Out of Scope

- Other `_score_thresholds` callers (they don't double-fetch — leave alone).
- `_resolve_weights` internal structure (epoch fetch is separate row, not
  duplicate — leave).
- ripple_service retry/poll config extraction (separate PR, bigger surface).
- public_showcase orphan-row serial writes (separate PR).

## Technical Notes

- File: `backend/api/routes/evaluation.py` (`:928-934` + `_score_thresholds`
  `:106-134` + new helper) + test.
- `backend/agents/evaluator.py:90` `_resolve_weights` (returns
  `EvaluatorWeights`, swallows own exc).
- `backend/db/evaluator_config.py:189` `load_weights` (the duplicate fetch).
- `EvaluatorWeights` has `pass_threshold` + `reject_threshold` fields
  (evaluator_config.py:90-91).
- `_score_thresholds` 6 callers (codegraph confirmed) — don't break signature.
- Precedent: dedupe pattern. No gather (these aren't independent — fingerprint
  depends on weights; can't parallelize). Pure dedupe: fetch once, reuse.
- `run_note_evaluation` is manual eval hot path (POST /evaluation/note).

## Decision (ADR-lite)

**Context**: `run_note_evaluation` fetches the same account weights twice
(fingerprint + thresholds) on every POST. `_score_thresholds` has 6 callers so
can't change signature. `_resolve_weights` already returns the weights but the
return value is discarded.
**Decision**: capture `_resolve_weights` return, derive thresholds via shared
`_thresholds_from_weights` helper (also used by `_score_thresholds` internally
for DRY). Keep both try/except paths independent (fingerprint vs thresholds
are independent failure modes). Defensive `if resolved_weights is not None`
guard falls back to `_score_thresholds` re-fetch.
**Consequences**: 1 fewer DB RTT per `/evaluation/note` POST. Zero behavior
change. ~6 LOC + 1 non-vacuous test. `_score_thresholds` 5 other callers
unaffected. Low risk.
