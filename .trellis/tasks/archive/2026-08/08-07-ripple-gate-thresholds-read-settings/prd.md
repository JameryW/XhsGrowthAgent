# Ripple-gate hardcoded thresholds → Settings (ripple_gate + ripple_finalize)

## Goal

`backend/agents/nodes/ripple_gate.py:16-18` and
`backend/agents/nodes/ripple_finalize.py:27-29` hardcode the same three Ripple
quality thresholds as module constants:

```python
_VIRAL_PROB_THRESHOLD = 0.4   # viral_probability below → suboptimal
_PMF_SCORE_THRESHOLD = 0.5    # pmf_score below → suboptimal
_MAX_RESELECT_COUNT = 2       # interrupt-at-most N times then auto-accept
```

These gate the human-in-the-loop `interrupt()` reselect loop: when Ripple
results are suboptimal AND `reselect_count < _MAX_RESELECT_COUNT`, the gate
interrupts for a user accept/reangle/retopic decision. Crossing 0.4 viral or
0.5 pmf fires the interrupt; the strategist's regen gate (#499,
`low_viral_threshold=0.3`) is a *separate, looser* cutoff on a *different*
decision (auto-regen vs HITL).

Extract all three to `RippleSettings` (default values = byte-identical), exact
same pattern as #465/#499. Operators can then tune how aggressive the HITL
gate is without a redeploy (`RIPPLE_GATE_VIRAL_THRESHOLD` etc.).

**Note:** `ripple_late_recheck.py:27` already imports `_MAX_RESELECT_COUNT`
and `_is_suboptimal` from `ripple_finalize` — so the late-recheck node picks
up the extraction transitively. Only `ripple_gate` redefines its own copy.

## What I already know

- Sites (verified by reading both files in full):
  - `ripple_gate.py:16-18` — 3 constants; consumed at `:33` (`_is_ripple_suboptimal`),
    `:64` (`reselect_count >= _MAX_RESELECT_COUNT`), `:89` (`max_reselect` in
    interrupt payload).
  - `ripple_finalize.py:27-29` — 3 constants; consumed at `:35`
    (`_is_suboptimal`), `:91`, `:107`.
- **Do NOT dedup the predicates.** `ripple_gate._is_ripple_suboptimal(state)`
  and `ripple_finalize._is_suboptimal(prediction, pmf)` are DIFFERENT:
  - gate version takes `state`, reads prediction/pmf from state, AND has a
    `ripple_reason in ("timeout","unreachable")` early-return-False guard
    (`:27`) — no caller pre-filters those reasons for the gate.
  - finalize version takes `(prediction, pmf)` dicts, has NO reason guard —
    because its caller pre-filters `reason in ("timeout","unreachable","pending")`
    at `:77` and returns before reaching `_is_suboptimal` (`:87`).
  - Both are correct in their own context. Merging would either drop the
    gate's guard (regression: gate would interrupt on timeout results) or add
    a redundant guard to finalize. The investigator's "near-dup, dedup"
    suggestion is WRONG — out of scope, rejected.
- `RippleSettings` (`backend/config/settings.py:77-86`) gained
  `low_viral_threshold: float = 0.3` in #499. Add 3 more fields here.
  `env_prefix="RIPPLE_"` → env vars `RIPPLE_GATE_VIRAL_THRESHOLD`,
  `RIPPLE_GATE_PMF_THRESHOLD`, `RIPPLE_MAX_RESELECT_COUNT`.
- `low_viral_threshold` is NOT in `system_config` SYSTEM_KEYS whitelist →
  env-only. These new fields same: env-only (matches #465/#499 ripple fields).
- `Settings()` per-call instantiation; matches existing usage in both files
  (`ripple_finalize` already imports `Settings`? — verify; `ripple_late_recheck`
  does at `:28`). `ripple_gate` does NOT currently import Settings — needs add.
- Test coverage:
  - `tests/unit/agents/nodes/test_ripple_finalize.py` — covers accept
    (0.8/0.7), suboptimal-interrupts, suboptimal-at-limit-accepts,
    timeout-reason-passes-through. At default 0.4/0.5/2 these stay green.
  - `tests/unit/agents/nodes/test_ripple_late_recheck.py` — suboptimal
    interrupt cases. Stays green at default.
  - **No `test_ripple_gate.py`** — the gate node's `_is_ripple_suboptimal`
    (with its timeout guard) is UNTESTED. Threshold extraction doesn't touch
    the predicate, so untested-ness isn't worsened, but note it.
- #499 precedent: `content_strategist.py:283` `< 0.3` →
  `Settings().ripple.low_viral_threshold`. Same file/family. Memory:
  `viral-gate-read-settings`, `ripple-sim-params-read-settings`.

## Recommended approach (ponytail)

Narrow threshold extraction only. No predicate dedup.

```python
# settings.py — RippleSettings (after low_viral_threshold, ~line 86):
gate_viral_threshold: float = 0.4  # ripple_gate/finalize: 传播概率低于此值触发 HITL reselect
gate_pmf_threshold: float = 0.5    # ripple_gate/finalize: PMF 分数低于此值触发 HITL reselect
max_reselect_count: int = 2        # ripple_gate/finalize: HITL reselect 上限，超出自动 accept

# ripple_gate.py:
# - add: from backend.config.settings import Settings
# - delete _VIRAL_PROB_THRESHOLD/_PMF_SCORE_THRESHOLD/_MAX_RESELECT_COUNT (:16-18)
# - in _is_ripple_suboptimal: read Settings().ripple.gate_viral_threshold /
#   gate_pmf_threshold (cache cfg = Settings().ripple once if multiple reads)
# - :64 and :89: Settings().ripple.max_reselect_count

# ripple_finalize.py:
# - delete the 3 constants (:27-29)
# - _is_suboptimal: read Settings().ripple.gate_viral_threshold/gate_pmf_threshold
# - :91, :107: Settings().ripple.max_reselect_count
# - (ripple_late_recheck imports these symbols from finalize → picks up change)
```

~3 fields + ~6 read-site changes across 2 files. Default values 0.4/0.5/2 =
byte-identical behavior.

- Pros: makes the HITL gate thresholds tunable at deploy (loosen = fewer
  interrupts on noisy Ripple data; tighten = more human oversight); closes 3
  hardcoded magic numbers; exact #465/#499 precedent; default = no behavior
  change. `ripple_late_recheck` benefits transitively.
- Cons: weak-ish benefit (HITL interrupt is rare + human-driven by design,
  vs #499 which gated an automatic 3rd LLM call on the costliest node). But
  real — closes a hardcoded-config class, consistent with the campaign.

**Rejected: dedup `_is_ripple_suboptimal` with `_is_suboptimal`.** Different
signatures, different reason-guard semantics. See "Do NOT dedup" above.

**Rejected: add `test_ripple_gate.py`.** Scope-creep for a config-extraction
PR. The predicate is unchanged; existing finalize/late_recheck tests cover the
shared thresholds via those nodes. Note gate-untested as out-of-scope.

## Requirements

- `RippleSettings` gains `gate_viral_threshold: float = 0.4`,
  `gate_pmf_threshold: float = 0.5`, `max_reselect_count: int = 2`.
- `ripple_gate.py` reads all three from `Settings().ripple.<field>` (no module
  constants).
- `ripple_finalize.py` reads all three from `Settings().ripple.<field>` (no
  module constants). `ripple_late_recheck` imports `_is_suboptimal` +
  `_MAX_RESELECT_COUNT` from finalize — but those symbols change: `_MAX_RESELECT_COUNT`
  is removed. late_recheck must read `Settings().ripple.max_reselect_count`
  directly OR finalize must re-export the value. **Decide: late_recheck
  currently imports `_MAX_RESELECT_COUNT`** — after removal it breaks. Either
  (a) keep a module-level `_MAX_RESELECT_COUNT = Settings().ripple.max_reselect_count`
  alias in finalize for back-compat, or (b) update late_recheck to read
  Settings directly. Prefer (b) — no stale alias, single source of truth.
- Default behavior unchanged (0.4/0.5/2 → same gate/finalize/recheck decisions).

## Acceptance Criteria

- [ ] `RippleSettings` has the 3 new fields with defaults 0.4/0.5/2.
- [ ] `ripple_gate.py` and `ripple_finalize.py` have no hardcoded
      `_VIRAL_PROB_THRESHOLD`/`_PMF_SCORE_THRESHOLD`/`_MAX_RESELECT_COUNT`
      module constants (grep clean).
- [ ] `ripple_late_recheck.py` updated (no broken import of `_MAX_RESELECT_COUNT`
      from finalize — reads Settings directly or finalize re-exports).
- [ ] `tests/unit/agents/nodes/test_ripple_finalize.py` +
      `test_ripple_late_recheck.py` pass unchanged at default thresholds.
- [ ] New non-vacuous test: patch `Settings().ripple.gate_viral_threshold` to
      e.g. 0.9 and assert a previously-acceptable result (viral 0.8) now
      triggers the finalize interrupt (proves the setting is read, not
      hardcoded). Mirror `test_content_strategist_ripple_settings.py` (#499).
      Fails if hardcoded 0.4 stays.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- settings.py 3-field add
- ripple_gate.py + ripple_finalize.py + ripple_late_recheck.py read-site changes
- 1 non-vacuous test proving env var read
- Pre-push triple green
- PR off `origin/main`, separate branch (no conflict with anything merged)

## Out of Scope

- Dedup `_is_ripple_suboptimal` / `_is_suboptimal` predicates (different
  semantics — would regress the gate's timeout guard).
- Add `test_ripple_gate.py` coverage for the gate node.
- Tune the threshold values (default stays 0.4/0.5/2; ops tunes via env).
- `routers.py:124` `_MAX_REVISION_COUNT = 2` (separate evaluator-revise system,
  just shares the value 2 via a comment — not a ripple threshold).
- The 0.3-vs-0.4 strategist/gate difference is intentional (different
  decisions); do NOT unify.

## Technical Notes

- Files: `backend/config/settings.py` (RippleSettings, ~line 86) +
  `backend/agents/nodes/ripple_gate.py` (:16-18, :33, :64, :89) +
  `backend/agents/nodes/ripple_finalize.py` (:27-29, :35, :91, :107) +
  `backend/agents/nodes/ripple_late_recheck.py` (:27 import) + test.
- Precedent: #465 `ripple-sim-params-read-settings`, #499
  `viral-gate-read-settings` — same Settings().ripple extraction pattern,
  same env_prefix. Memories: `ripple-sim-params-read-settings`,
  `viral-gate-read-settings`.
- `Settings()` per-call instantiation; matches existing :145/:165/:531/:582
  usage in content_strategist. No caching concern.
- ripple_late_recheck already imports Settings (`:28`); ripple_gate does NOT
  currently import Settings — must add the import.
- Investigator (`caveman:cavecrew-investigator`) flagged this candidate but
  ALSO suggested predicate dedup — that part is REJECTED (wrong, would
  regress). Threshold extraction only.

## Decision (ADR-lite)

**Context**: ripple_gate + ripple_finalize hardcode 3 shared thresholds
(0.4/0.5/2) as duplicated module constants, gating the HITL reselect loop.
Same dead-config class as #465/#499. Investigator suggested also deduping the
near-identical predicates — rejected: the predicates differ (gate has a
timeout/unreachable guard, finalize's caller pre-filters).
**Decision**: extract the 3 thresholds to `RippleSettings` (defaults
0.4/0.5/2, env `RIPPLE_GATE_VIRAL_THRESHOLD` / `RIPPLE_GATE_PMF_THRESHOLD` /
`RIPPLE_MAX_RESELECT_COUNT`). No predicate dedup. Update late_recheck's import.
**Consequences**: HITL gate thresholds tunable at deploy without redeploy.
Default = byte-identical. ~3 fields + ~6 read sites + late_recheck import
update + 1 non-vacuous test. Low risk. Predicate semantics untouched.
