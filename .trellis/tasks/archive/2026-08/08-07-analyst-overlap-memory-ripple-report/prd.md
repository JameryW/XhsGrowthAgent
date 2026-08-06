# analyst: overlap memory recall with Ripple report fetch

## Goal

`backend/agents/analyst.py:49,54` runs 2 top-level calls **serially** in
`execute` on every analyst run (ANALYZING path: publisher → analyst):

```python
history = await self._recall_memory(store, account_id, ...)    # :49  Postgres asearch (fast)
ripple_report = await self._ripple_report(state)               # :54  Ripple job fetch (up to 120s timeout — long pole)
```

`_ripple_report` is the long pole (up to `_RIPPLE_REPORT_TIMEOUT=120`s
waiting on Ripple `get_report(job_id)`). `_recall_memory` is a fast Postgres
asearch. They run serially → memory RTT adds on top of the Ripple fetch.
Gather them → memory RTT fully overlaps with the Ripple fetch (hidden behind
the long pole when a job_id exists).

## What I already know

- **2 top-level calls, both independent.** Verified by reading `analyst.py:43-66`:
  - `_recall_memory` (`:49`) → `history` → `user_msg` (`:64`). Reads
    `content_history` namespace. No dependency on ripple_report.
  - `_ripple_report` (`:54`) → `ripple_report` → `ripple_context` (`:58-60`).
    Reads Ripple external service. No dependency on history.
  - `history` + `ripple_context` only concatenated in `user_msg` (`:63-66`)
    — after both done. Sequential consumption, fine.
- **Both swallow own exceptions:**
  - `_recall_memory` (base.py) wraps body in try/except, returns `[]`.
  - `_ripple_report` (`:203-242`): 3 except clauses (RippleTimeoutError,
    TimeoutError, Exception) all log + return None. **Plus an internal
    early-return-None guard** `:210-211` (`if not job_id: return None`) —
    returns immediately without any network call when no job_id. So calling
    it when job_id absent is NOT wasteful (no pointless lookup, unlike #507's
    `recall_benchmark("")` which did a DB lookup). No no-op wrapper needed.
  - Gather adds no new exception surface — same proof as #502/#503/#504/#505/#506/#507.
- **Return-value pattern** (no concurrent mutation): gather returns
  `(history, ripple_report)`, then build `ripple_context` + `user_msg`
  sequentially after. No shared mutable state during gather.
- `asyncio` already imported (`:5`).
- `_ripple_report` internally uses `asyncio.wait_for` (`:216`) — that's a
  different asyncio primitive, not a gather. Doesn't affect this change.
- `_ripple_report` early-return guard (`:210`) means when no ripple_job_id,
  it returns None immediately — calling it in the gather is safe + not
  wasteful. SIMPLER than #507 (which needed `_noop_benchmark` because
  `recall_benchmark("")` did a wasteful DB lookup). Here the guard is
  internal + zero-cost, so no wrapper.
- Test coverage: `tests/unit/agents/test_analyst.py` (verify exists + mock
  shape during implement). Existing tests mock `_recall_memory`/`_ripple_report`
  and assert analytics/result — gather keeps them green if return values
  consumed identically.
- **Precedent: PR #506** (trend_scout top-level gather of memory + slow
  external fetch). This is the same shape: fast memory recall + slow external
  service fetch, gathered at top level. Memory: `copywriter-parallel-memory-recalls`.

## Recommended approach (ponytail)

Gather the 2 independent top-level calls. Return-value pattern:

```python
# :48-54
history, ripple_report = await asyncio.gather(
    self._recall_memory(
        store, account_id, query="content performance",
        namespace="content_history", limit=10,
    ),
    self._ripple_report(state),
)

system_prompt = self._build_system_prompt(state)

ripple_context = ""
if ripple_report:
    ripple_context = f"\nRipple 传播预测报告：\n{ripple_report}\n"
```

~3 LOC net (gather replaces 2 serial awaits; asyncio already imported).
Behavior identical: same `history` + `ripple_report`, same downstream
`ripple_context` + `user_msg` + `_llm_ainvoke`.

**No `_safe_*` wrappers, no `_noop_*` needed:**
- Both calls already swallow own exceptions internally.
- `_ripple_report`'s job_id-absent guard is internal + zero-cost (early return
  None, no lookup) — unlike #507's `recall_benchmark("")` which did a wasteful
  DB lookup. So calling `_ripple_report` directly in the gather is safe and
  not wasteful in either case. SIMPLER than #507.

- Pros: ~1 fewer serial Postgres RTT on analyst (ANALYZING path); memory RTT
  fully hidden behind Ripple fetch (the long pole, up to 120s) when job_id
  exists. Exact #502-#507 exception-surface proof. Zero behavior change.
  Simpler than #507 (no no-op wrapper — internal guard is zero-cost).
- Cons: none.

**Rejected: also gather `_compare_prediction_vs_actual` / `store_insight`
loop.** `_compare_prediction_vs_actual` (`:86`) is sync + depends on
`analytics` (post-LLM). `store_insight` loop (`:110-112`) is post-LLM writes,
order-dependent. Out of scope.

**Rejected: also gather the 2 `store_insight`+`store_strategy_note` loops
(`:110-115`).** Both are writes (post-LLM). Writes harder to gather safely
(order, shared store). Investigator flagged analyst writes as not viable.
Out of scope.

## Requirements

- `_recall_memory` + `_ripple_report` run via `asyncio.gather` (concurrent)
  at the top level of `execute`.
- `ripple_context` + `user_msg` built from gathered values identically.
- No `_safe_*` / `_noop_*` wrappers (both calls already swallow; _ripple_report
  guard is internal + zero-cost).
- Zero behavior change (same `history`, `ripple_report`, downstream LLM call).

## Acceptance Criteria

- [ ] `analyst.execute` uses `asyncio.gather` for `_recall_memory` +
      `_ripple_report` (top-level).
- [ ] Existing `tests/unit/agents/test_analyst.py` passes unchanged.
- [ ] New non-vacuous test: assert top-level `_recall_memory` +
      `_ripple_report` run concurrently. Must FAIL if reverted to serial.
      Discriminator: verify how many gathers analyst module has after change.
      analyst already uses `asyncio.wait_for` (`:216`, not a gather) +
      `asyncio.create_task` (`:174`, not a gather). Check if any existing
      `asyncio.gather` — if module has 0 gathers before, the new one is the
      only one (filter by 2-awaitable, or just assert 1 gather call). If
      multiple, use __qualname__ coroutine-source discriminator (#506 pattern).
      Verify during implement.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- analyst.py top-level gather (~3 LOC, asyncio already imported)
- 1 non-vacuous concurrency test (discriminator handles module's gather count)
- Pre-push triple green
- PR off `origin/main`, separate branch `fix/analyst-overlap-memory-with-ripple-report`

## Out of Scope

- Gathering post-LLM writes (store_insight loop, store_strategy_note loop —
  writes, order-dependent, not safe to gather).
- Gathering `_compare_prediction_vs_actual` (sync, post-LLM, depends on analytics).
- Gathering content_history update (`:121-142`, read-then-write on same key,
  must stay serial).
- Other agents.

## Technical Notes

- File: `backend/agents/analyst.py` (`:48-54`) + test.
- `_recall_memory`: base.py (wraps try/except, returns `[]`).
- `_ripple_report`: `:203-242` (3 except clauses → None; internal early-return
  guard `:210` when no job_id — zero-cost, no wasteful lookup).
- Precedent: PR #506 (trend_scout top-level: fast memory + slow external
  fetch gathered). Memory: `copywriter-parallel-memory-recalls`. This is the
  7th gather-parallel example — same shape as #506 but simpler (no no-op
  wrapper: _ripple_report's guard is internal + zero-cost vs #507's
  recall_benchmark which needed _noop_benchmark).
- analyst is ANALYZING path (publisher → analyst → [orchestrator|END]).
- asyncio already imported (`:5`); module uses `asyncio.wait_for` (`:216`) +
  `asyncio.create_task` (`:174`) but verify no existing `asyncio.gather`.

## Decision (ADR-lite)

**Context**: analyst's `execute` runs `_recall_memory` (fast Postgres) then
`_ripple_report` (slow Ripple, up to 120s) serially. Memory RTT adds on top
of the Ripple long pole. Both independent, both swallow own exceptions.
`_ripple_report` has an internal zero-cost early-return guard (no job_id →
None, no lookup).
**Decision**: gather the 2 top-level calls; no `_safe_*`/`_noop_*` wrappers
(both swallow; _ripple_report guard is internal + zero-cost, unlike #507's
wasteful recall_benchmark("")). Return-value pattern.
**Consequences**: ~1 fewer serial Postgres RTT on analyst, fully hidden
behind Ripple fetch (when job_id exists). Zero behavior change. ~3 LOC + 1
non-vacuous test. 7th gather-parallel example, same shape as #506 but
simpler (no no-op wrapper). Low risk.
