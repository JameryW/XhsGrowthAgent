# brief_analyzer: parallelize style + benchmark recalls

## Goal

`backend/agents/brief_analyzer.py:46-47` runs 2 creative-memory recalls
**serially** on every brief_analyzer execute (BRIEFING path, gated by
`raw_text` present):

```python
styles = await cm.recall_style(query="商单 brief 风格")                    # :46
benchmark = await cm.recall_benchmark(niche) if niche else None           # :47
```

Each recall does DB lookup + optional store asearch. Gather → ~1 concurrent
wave, fewer serial RTT before the BRIEF_ANALYSIS→astron LLM call.

## What I already know

- **2 calls, both independent.** Verified by reading `brief_analyzer.py:42-49`:
  - `recall_style(query=...)` (`:46`) → `styles` list → `style_dna` namespace.
  - `recall_benchmark(niche)` (`:47`) → `benchmark` dict|None → `benchmarks`
    namespace.
  - Disjoint namespaces, no data dependency (neither feeds the other's args).
  - `creative_ctx = cm.build_creative_context(styles, [], [], benchmark)`
    (`:49`) consumes both after — sequential consumption, fine.
- **Both swallow own exceptions** (creative.py: recall_style :84-90/:108-109
  try/except → `[]`/`_default_styles()`; recall_benchmark :264-284 try/except
  → None). Gather adds no new exception surface — same proof as
  #502/#503/#504/#505/#506.
- **The niche guard is the wrinkle.** Original `:47`:
  `benchmark = await cm.recall_benchmark(niche) if niche else None`.
  When `niche` is empty, the original SKIPS the call entirely (returns None)
  — intentional, avoids a pointless `get_benchmark("")` DB lookup. Must
  preserve this guard in the gather.
- **recall_benchmark("") would be safe but wasteful** (creative.py:262-284
  handles empty niche without raising — `get_benchmark("")` returns None,
  then `if not self._has_store: return None`, then asearch). But the
  original guard exists to avoid that wasted lookup. Honor it.
- `asyncio` import status in brief_analyzer — verify during implement; file
  is 167 lines, currently no asyncio import (only logging, typing). Add it.
- `build_creative_context` (`:49`) takes `(styles, [], [], benchmark)` —
  middle args are empty (plays, materials) — brief_analyzer only recalls
  style + benchmark. Untouched.
- Test coverage: `tests/unit/agents/test_brief_analyzer.py` (verify exists
  + mock shape during implement). Existing tests mock CreativeMemory recalls
  and assert `brief_result`/`creative_ctx` — gather keeps them green if
  return values consumed identically.
- **Precedent: PR #502/#503/#505** (memory-recall gather, no wrappers when
  recalls swallow internally). This is the 6th gather-parallel example.

## Recommended approach (ponytail)

Gather the 2 independent recalls. Preserve the niche guard via a no-op
coroutine (return None) so the guard semantics hold byte-for-byte:

```python
import asyncio  # add to imports

# :42-49
from backend.memory.creative import CreativeMemory

cm = CreativeMemory(account_id, store=store)
styles, benchmark = await asyncio.gather(
    cm.recall_style(query="商单 brief 风格"),
    cm.recall_benchmark(niche) if niche else _noop_benchmark(),
)

creative_ctx = cm.build_creative_context(styles, [], [], benchmark)
```

Where `_noop_benchmark` is a tiny module-level (or inline) coroutine:

```python
async def _noop_benchmark() -> None:
    """Return None without a lookup — preserves the `if niche else None` guard
    inside a gather (avoids a pointless recall_benchmark("") DB call)."""
    return None
```

~5 LOC net (gather + `import asyncio` + `_noop_benchmark` helper). Behavior
identical: when niche truthy → both recalled concurrently; when niche empty
→ styles recalled, benchmark None (no pointless lookup). Same `creative_ctx`,
same downstream LLM call.

**No `_safe_*` wrappers needed** (both recalls already swallow own exceptions
internally, proven above — same as #505/#506). The `_noop_benchmark` is not
a safety wrapper; it's the guard preservation.

- Pros: ~1 fewer serial RTT on brief_analyzer (BRIEFING path) before
  BRIEF_ANALYSIS→astron; exact #502/#503/#505 exception-surface proof; zero
  behavior change; niche guard preserved byte-for-byte.
- Cons: `_noop_benchmark` helper is ~3 LOC overhead vs a plain gather (the
  guard forces it). Acceptable — the guard is intentional, can't drop it
  without a wasted DB lookup on empty-niche runs.

**Rejected: drop the guard, always call recall_benchmark(niche).** Would add
a pointless `get_benchmark("")` + asearch on every empty-niche run (wasteful,
opposite of optimization). Keep the guard.

**Rejected: branch on niche (gather when truthy, serial when empty).** Two
code paths for the same outcome — more LOC, no benefit. The no-op coroutine
unifies into one gather. Ponytail: one path.

**Rejected: inline `asyncio.sleep(0)`-style no-op.** A named `_noop_benchmark`
with a docstring explains WHY (guard preservation) — reads as intent, not
trickery. Matches ponytail "simple reads as intent" rule.

## Requirements

- `recall_style` + `recall_benchmark` run via `asyncio.gather` (concurrent)
  when niche is truthy.
- When niche is empty: `recall_style` runs, `benchmark` is None (NO
  `recall_benchmark("")` call) — guard preserved via `_noop_benchmark`.
- `build_creative_context` consumes gathered values identically.
- No `_safe_*` wrappers (recalls already swallow own exceptions).
- Zero behavior change (same `styles`, `benchmark`, `creative_ctx`, downstream).

## Acceptance Criteria

- [ ] `brief_analyzer.execute` uses `asyncio.gather` for `recall_style` +
      `recall_benchmark` (with `_noop_benchmark` when niche empty).
- [ ] Niche-empty case: `recall_benchmark` NOT called (guard preserved) —
      verify via test (mock recall_benchmark, assert not called when niche="").
- [ ] Niche-truthy case: both called concurrently.
- [ ] Existing `tests/unit/agents/test_brief_analyzer.py` passes unchanged.
- [ ] New non-vacuous test: assert `recall_style` + `recall_benchmark` run
      concurrently when niche truthy (patch `asyncio.gather`, assert called
      once with 2 awaitables). Must FAIL if reverted to serial. Note: if
      brief_analyzer has OTHER gathers, filter (likely only 1 gather in this
      file — verify).
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- brief_analyzer.py gather refactor (~5 LOC + `import asyncio` + `_noop_benchmark`)
- 1 non-vacuous concurrency test (mirror #502/#503/#505/#506 pattern)
- 1 test asserting niche-empty guard (recall_benchmark not called)
- Pre-push triple green
- PR off `origin/main`, separate branch `fix/brief-analyzer-parallel-memory-recalls`

## Out of Scope

- Gathering `deposit_style` (post-LLM write, depends on result).
- Gathering `build_creative_context` (sync, consumes gathered values).
- Gathering `_generate_clarification` (conditional post-LLM, depends on confidence).
- Other agents (analyst `:49+54` — separate PR).

## Technical Notes

- File: `backend/agents/brief_analyzer.py` (`:42-49`) + test.
- Memory: `backend/memory/creative.py` — `recall_style` (:73),
  `recall_benchmark` (:262), both swallow own exceptions.
- Precedent: PR #502 (copywriter), #503 (content_strategist), #505
  (visual_designer), #506 (trend_scout top-level). Memory:
  `copywriter-parallel-memory-recalls`. This is the 6th gather-parallel
  example — first with a conditional-call guard (no-op coroutine pattern).
- brief_analyzer is BRIEFING path (gated by raw_text present); runs on
  commercial-brief workflows.
- The `_noop_benchmark` no-op-coroutine pattern is reusable for any gather
  where one call is conditionally skipped — preserves guard + unifies into
  one gather (no branch duplication).

## Decision (ADR-lite)

**Context**: brief_analyzer's `execute` runs 2 creative-memory recalls
serially. Both independent, both swallow own exceptions. But `recall_benchmark`
is guard-skipped when niche empty (avoids pointless lookup).
**Decision**: gather the 2 recalls; preserve the niche guard via a
`_noop_benchmark` coroutine (returns None, no lookup) so the gather has 2
awaitables in both cases. No `_safe_*` wrappers (recalls already swallow).
Return-value pattern.
**Consequences**: ~1 fewer serial RTT before BRIEF_ANALYSIS→astron. Zero
behavior change (guard preserved byte-for-byte). ~5 LOC + 1 non-vacuous test
+ 1 guard test. 6th gather-parallel example, first with conditional-call
guard. Low risk.
