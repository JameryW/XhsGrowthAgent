# trend_scout: overlap memory recall with XHS API fetch

## Goal

`backend/agents/trend_scout.py:116,126` runs 2 top-level calls **serially** in
`execute` on every trend_scout run (trend_scout is the workflow entry node:
START → orchestrator → trend_scout):

```python
insights = await self._recall_memory(store, account_id, ...)   # :116  Postgres asearch (fast)
# ... build memory_context ...
real_data = await self._fetch_real_data(niche, ...)             # :126  XHS API (slow: trending+competitor gather + serial keyword_monitor)
```

`_fetch_real_data` is the long pole (3 XHS API RTTs: trending + competitor
gathered per #504, then serial keyword_monitor). `_recall_memory` is a fast
Postgres asearch. They run serially → memory RTT adds on top of the XHS
fetch. Gather them → memory RTT fully overlaps with the XHS fetch (hidden
behind the long pole).

## What I already know

- **2 top-level calls, both independent.** Verified by reading `trend_scout.py:106-169`:
  - `_recall_memory` (`:116`) → `insights` → `memory_context` string. Reads
    `performance_insights` namespace. No dependency on real_data.
  - `_fetch_real_data` (`:126`) → `real_data` dict → `data_context` string.
    Reads XHS API. No dependency on insights.
  - `memory_context` + `data_context` only concatenated at `:168`
    (`_build_system_prompt`) — after both done. Sequential consumption, fine.
- **Both swallow own exceptions:**
  - `_recall_memory` (base.py) wraps body in try/except, returns `[]`.
  - `_fetch_real_data` (`:59-104`): xhs_trending + competitor via `_safe_*`
    wrappers (swallow, return `[]`); keyword_monitor in try/except (`:101`).
    Returns `data` dict (possibly partial/empty). Never raises to caller.
  - Gather adds no new exception surface — same proof as #502/#503/#504/#505.
- **Return-value pattern** (no concurrent mutation): gather returns
  `(insights, real_data)`, then build `memory_context` + `data_context`
  sequentially after. No shared mutable state during gather.
- `asyncio` already imported (`:5`, added by #504).
- `_fetch_real_data` is already async and self-contained (no shared self state
  mutated during its run — it builds a local `data` dict and returns it).
  Safe to run concurrently with `_recall_memory`.
- Test coverage: `tests/unit/agents/test_trend_scout.py` (has #504's
  `test_fetch_real_data_gathers_independent_xhs_calls` filtering to
  2-awaitable gather inside `_fetch_real_data`). New test must filter to the
  **top-level** gather (also 2-awaitable) — module now has 2 gathers (#504's
  internal + this new top-level). Filter by awaitable count alone won't
  disambiguate (both are 2). Need a different discriminator: patch gather,
  record ALL calls, assert >=1 gather with 2 awaitables where one awaitable
  is the `_recall_memory` coroutine (or assert 2 total gather calls — one
  internal to _fetch_real_data, one top-level). Verify exact gather count
  during implement.
- **Precedent: PR #504** (trend_scout internal gather) — this is the
  **outer** gather wrapping `_recall_memory` + `_fetch_real_data`. Memory:
  `copywriter-parallel-memory-recalls` (4-example gather-parallel series).

## Recommended approach (ponytail)

Gather the 2 independent top-level calls. Return-value pattern:

```python
# :115-126
insights, real_data = await asyncio.gather(
    self._recall_memory(
        store, account_id, query="trend insights",
        namespace="performance_insights", limit=3,
    ),
    self._fetch_real_data(niche, account_id=account_id, user_topic=user_topic),
)

memory_context = ""
if insights:
    memory_context = "\n历史趋势洞察：\n"
    for i in insights:
        memory_context += f"- {i.get('insight', '')}\n"
```

~3 LOC net (gather replaces 2 serial awaits; asyncio already imported).
Behavior identical: same `insights` + `real_data`, same downstream
`memory_context` + `data_context` + `_llm_ainvoke`.

**No `_safe_*` wrappers needed** (both calls already swallow own exceptions
internally — `_recall_memory` via base.py try/except, `_fetch_real_data` via
its internal `_safe_*` + keyword_monitor try/except). Same as #505 (no
wrappers when calls already swallow).

- Pros: ~1 fewer serial Postgres RTT on trend_scout (workflow entry node);
  memory RTT fully hidden behind XHS fetch (the long pole). Exact
  #502/#503/#504/#505 exception-surface proof. Zero behavior change.
- Cons: test discriminator trickier (module has 2 gathers after this change,
  both 2-awaitable — must distinguish top-level from #504's internal). See
  test section.

**Rejected: also gather `store_insight` (`:212`).** That's a post-LLM write
depending on `trend_data` result — can't gather with pre-LLM reads. Out of
scope.

**Rejected: flatten _fetch_real_data into execute + gather all 4 XHS+memory.**
Would break #504's encapsulation (keyword_monitor depends on trending, must
stay inside _fetch_real_data's gather-then-serial structure). Keep
_fetch_real_data as one unit; gather it whole with _recall_memory.

## Requirements

- `_recall_memory` + `_fetch_real_data` run via `asyncio.gather` (concurrent)
  at the top level of `execute`.
- `memory_context` + `data_context` built from gathered values identically.
- No `_safe_*` wrappers (both calls already swallow own exceptions).
- Zero behavior change (same `insights`, `real_data`, downstream LLM call).

## Acceptance Criteria

- [ ] `trend_scout.execute` uses `asyncio.gather` for `_recall_memory` +
      `_fetch_real_data` (top-level).
- [ ] Existing `tests/unit/agents/test_trend_scout.py` passes unchanged
      (incl. #504's `test_fetch_real_data_gathers_independent_xhs_calls`).
- [ ] New non-vacuous test: assert top-level `_recall_memory` +
      `_fetch_real_data` run concurrently. Must FAIL if reverted to serial.
      Discriminator: module has 2 gathers after change (both 2-awaitable) —
      #504's internal + this new top-level. Distinguish by asserting the
      total gather call count (should be 2: one inside _fetch_real_data, one
      top-level), OR by inspecting which coroutines are in the gather args
      (top-level gather contains the `_recall_memory` coroutine). Verify
      exact approach during implement. Must not break #504's existing test.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- trend_scout.py top-level gather (~3 LOC, asyncio already imported)
- 1 non-vacuous concurrency test (discriminator handles 2-gather module)
- Pre-push triple green
- PR off `origin/main`, separate branch `fix/trend-scout-overlap-memory-with-xhs-fetch`

## Out of Scope

- Gathering `store_insight` (post-LLM write, depends on result).
- Flattening `_fetch_real_data` (breaks #504 encapsulation).
- Other agents (brief_analyzer `:46-47`, analyst `:49+54` — separate PRs).

## Technical Notes

- File: `backend/agents/trend_scout.py` (`:115-126`) + test.
- `_recall_memory`: base.py (wraps try/except, returns `[]`).
- `_fetch_real_data`: `:59-104` (internal #504 gather + serial keyword_monitor,
  all swallow own exceptions, returns `data` dict).
- Precedent: PR #504 (trend_scout internal gather), #502/#503/#505 (series).
  Memory: `copywriter-parallel-memory-recalls`. This is the 5th gather-parallel
  example — first to nest a gather call inside another gather
  (`_fetch_real_data` itself gathers internally).
- trend_scout is workflow entry node (START→orchestrator→trend_scout); every
  workflow run hits this. XHS fetch is the long pole; memory RTT hidden behind it.
- Test nuance: after this change, module has 2 gathers (both 2-awaitable).
  #504's test filters to the internal 2-awaitable gather. New test must
  target the top-level gather without colliding — likely assert total gather
  count == 2, or inspect coroutine identity in gather args.

## Decision (ADR-lite)

**Context**: trend_scout's `execute` runs `_recall_memory` (fast Postgres)
then `_fetch_real_data` (slow XHS, 3 RTTs) serially. Memory RTT adds on top
of the XHS long pole. Both independent, both swallow own exceptions.
**Decision**: gather the 2 top-level calls; no `_safe_*` wrappers (both
already swallow). Return-value pattern. `_fetch_real_data` stays as one unit
(itself gathers internally per #504).
**Consequences**: ~1 fewer serial Postgres RTT on trend_scout (entry node),
fully hidden behind XHS fetch. Zero behavior change. ~3 LOC + 1 non-vacuous
test. First nested-gather example (gather containing a gather). Test must
handle 2-gather module. Low risk.
