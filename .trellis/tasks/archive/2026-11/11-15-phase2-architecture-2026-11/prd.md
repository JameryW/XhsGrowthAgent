# Phase 2 architecture hardening (ledger proposals 7-12)

## Goal

Turn the 2026-11 second-phase ledger proposals into deterministic, testable
modules without re-doing the six phase-1 upgrades.

## Scope

1. **Security drift + indirect prompt injection**
   - Sync `docs/security.md` keys (MAGPIE/XIAOMIMIMO), Ripple port 8080, and
     the deterministic compliance invariants.
   - Tool Gateway external-content envelope: mark trending/keyword/competitor/
     search/topic tools, sanitize payloads, expose `ToolResult.untrusted`.

2. **Age-calibrated collect-first outcome learning**
   - `outcome_learning.py`: 48h maturity gate, recent-10 median baseline,
     `log1p(collects)` advantage, minimum 3 mature notes, Spearman helper.
   - `creator_stats.analyze_notes` exposes `outcome_learning`; `AnalysisResult`
     carries it without changing existing fields.

3. **Judge identity + calibration**
   - Record `judge_model_id` on every RQGM result; per-model z-score
     calibration over the last 50 scores.

4. **Stable context prefix**
   - `CompiledPrompt.cache_prefix/cache_tail/cache_prefix_token_cost` and
     opt-in `render_with_cache_breakpoint()`; `render()` byte-identical.

5. **DM qualification gate**
   - Five-slot FSM + outbound checks; `send_dm` refuses before the effect
     ledger; `dm_handler` accepts optional state/prices.

6. **Weekly bandit**
   - Sliding-window UCB/Wilson ranking and canary decision; `ab_test_manager`
     returns the decision but never promotes automatically.

## Acceptance

- New unit tests cover each pure module and the service/tool wiring.
- Existing creator stats, engagement, evaluator, context, and tool-runtime
  tests remain green.
- `ruff check`, `ruff format --check`, `mypy --python-version 3.12 backend`,
  and the full `pytest` suite pass.
- New behavior is opt-in or additive; no existing DTO field or tool return
  key is removed.
- README documents the phase-2 modules and their approximation boundaries.
