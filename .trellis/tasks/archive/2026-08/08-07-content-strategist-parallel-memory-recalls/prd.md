# content_strategist serial memory recalls → asyncio.gather

## Goal

`backend/agents/content_strategist.py:40-47` runs 4 independent memory recalls
**serially** before the main LLM call (`:105`), on every workflow run:

```python
niche = state.get("niche", "母婴")                                   # :39
styles = await cm.recall_style(query=f"content strategy {niche}")     # :40
plays = await cm.recall_plays(condition="content strategy", niche=niche)  # :41
benchmark = await cm.recall_benchmark(niche)                          # :42
insights = await self._recall_memory(                                 # :45-47
    store, account_id, query="content strategy",
    namespace="performance_insights", limit=5,
)
```

Each recall does 1-2 network round-trips (durable DB list + LangGraph store
`asearch` against Postgres — same shape as copywriter's recalls, PR #502).
Serialized = up to ~8 RTTs on the content_strategist critical path before the
WRITING→astron LLM call. content_strategist is the **costliest node** (~352s
prod per memory; the 2 serial astron calls dominate, but these 4 recalls are
avoidable serial RTTs before them).

Gather collapses 4 serial waves → 1 concurrent wave. Exact PR #502 precedent
(copywriter parallel memory recalls), same idiom already used at
content_strategist:210 (`asyncio.gather(_predict(), _validate_pmf())`).

## What I already know

- **Verified independence** (read all 4 recall bodies):
  - `recall_style` (`memory/creative.py:73`) — reads DB `list_styles` + store
    `asearch(self.style_dna_ns, ...)`, swallows own exceptions, returns list.
  - `recall_plays` (`memory/creative.py:145`) — wraps body in try/except,
    returns list on failure.
  - `recall_benchmark` (`memory/creative.py:262`) — wraps DB + store in
    try/except, returns `None` on failure.
  - `_recall_memory` (`agents/base.py:120`) — early-returns `[]` if store None,
    wraps body in try/except returning `[]`.
  - **None can raise to the caller** → gather adds no new exception surface
    (same proof as #502). Disjoint namespaces (`style_dna`,
    `conversion_playbook`, `benchmarks`, `performance_insights`).
- `niche` computed at `:39` before all 4; `account_id` from `:31`-ish. No data
  dependency between the 4 recalls — `recall_style`/`recall_plays`/`recall_benchmark`
  all take `niche` (or a query derived from it), `_recall_memory` takes a fixed
  query string. None consumes another's result.
- Post-gather consumption: `insights` used at `:48-52` (builds memory_context),
  `styles/plays/benchmark` used at `:55` (`build_creative_context(styles, plays,
  [], benchmark)`). Order of completion doesn't matter — gather preserves
  result order by input order, so `styles, plays, benchmark, insights = await
  asyncio.gather(...)` is a drop-in.
- `asyncio` already imported in content_strategist (used at `:210` gather).
  No new import needed.
- Test coverage: `tests/unit/agents/test_content_strategist.py` — verify mock
  shape during implement. Existing tests likely assert output (content_plan),
  not recall call-order — so gather keeps them green.
- **Precedent: PR #502** (copywriter) — exact same refactor, same file family,
  same memory recall pattern, same exception-swallowing proof, same
  non-vacuous test approach. Memory: `copywriter-parallel-memory-recalls`.

## Recommended approach (ponytail)

Replace the 4 serial `await` assignments with one `asyncio.gather`:

```python
# :40-47 becomes:
styles, plays, benchmark, insights = await asyncio.gather(
    cm.recall_style(query=f"content strategy {niche}"),
    cm.recall_plays(condition="content strategy", niche=niche),
    cm.recall_benchmark(niche),
    self._recall_memory(
        store, account_id, query="content strategy",
        namespace="performance_insights", limit=5,
    ),
)
```

Leave `:63` (`build_mode_creative_context` try/except) and `:85`
(`_score_trend_topics`) sequential — same "keep simple" directive as #502.
`:63` is resilience-isolated (creator_stats optional); `:85` is a loop over
topic_scorer, harder to gather cleanly. The 4 memory recalls are the win.

~8 LOC net (gather block replaces 4 awaits; `asyncio` already imported).
Behavior identical: same 4 values, same names, consumed identically below.

- Pros: ~3-4 fewer serial RTTs on the costliest node's path before its LLM
  call; exact #502 precedent; zero behavior change; existing output-asserting
  tests stay green.
- Cons: none. Same exception-surface proof as #502.

**Rejected: also gather `build_mode_creative_context` (`:63`) and
`_score_trend_topics` (`:85`).** `:63` is resilience-isolated (separate
try/except, creator_stats optional). `:85` is a loop over topic_scorer (each
topic a separate ainvoke) — gathering it would restructure the loop. Both
marginal vs the 4-recall gather. Keep narrow, match #502 scope exactly.

## Requirements

- `content_strategist.py:40-47` 4 serial memory recalls run via `asyncio.gather`.
- `build_mode_creative_context` (`:60-67`) and `_score_trend_topics` (`:85`)
  stay sequential.
- Return values + downstream `memory_context` + `build_creative_context`
  construction unchanged.
- `asyncio` already imported — no new import.

## Acceptance Criteria

- [ ] `content_strategist.py` uses `asyncio.gather` for the 4 recalls; no 4
      serial `await` assignments remain at `:40-47`.
- [ ] `:60-67` (build_mode_creative_context try/except) + `:85`
      (_score_trend_topics) untouched.
- [ ] Existing `tests/unit/agents/test_content_strategist.py` passes unchanged.
- [ ] New non-vacuous test: assert the 4 recalls run concurrently (patch
      `asyncio.gather`, assert called once with 4 awaitables — mirror #502's
      `test_execute_recalls_memory_concurrently`). Must fail if reverted to
      serial awaits.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- content_strategist.py gather refactor (~8 LOC, no new import)
- 1 non-vacuous concurrency test (mirror #502)
- Pre-push triple green
- PR off `origin/main`, separate branch (no conflict with anything merged)

## Out of Scope

- Gathering `build_mode_creative_context` (`:63`) — resilience try/except.
- Gathering/restructuring `_score_trend_topics` (`:85`) — topic_scorer loop.
- The 2 serial astron LLM calls (data-dependent, can't parallelize — already
  evaluated and excluded in prior loop).
- Other agents' recall patterns (separate audits).

## Technical Notes

- File: `backend/agents/content_strategist.py` (`:40-47` gather target,
  `:60-67` + `:85` leave-alone) + test.
- Recall impls: `backend/memory/creative.py:73` (recall_style), `:145`
  (recall_plays), `:262` (recall_benchmark); `backend/agents/base.py:120`
  (_recall_memory). All read-only, disjoint namespaces, swallow own exceptions.
- Precedent: PR #502 (copywriter) — exact same refactor. PR content_strategist
  already uses `asyncio.gather` at `:210` (ripple predict+pmf). Memory:
  `copywriter-parallel-memory-recalls`.
- content_strategist is the costliest node (352s prod, 2× serial astron).
  These 4 recalls are before the first astron call; gather saves ~3-4 serial
  RTTs. Doesn't fix the 352s (astron calls dominate) but removes avoidable
  serial latency.

## Decision (ADR-lite)

**Context**: content_strategist runs 4 independent read-only memory recalls
serially on the costliest node's path before its LLM call, each 1-2 DB/store
round-trips. No data dependency, disjoint namespaces, all swallow own
exceptions. Exact PR #502 (copywriter) pattern; content_strategist:210 already
uses gather.
**Decision**: gather the 4 recalls into one `asyncio.gather`. Leave
resilience-isolated `build_mode_creative_context` and the `_score_trend_topics`
loop sequential.
**Consequences**: ~3-4 fewer serial RTTs on content_strategist's path before
its LLM call. Zero behavior change. ~8 LOC (asyncio already imported) + 1
non-vacuous concurrency test mirroring #502. Low risk.
