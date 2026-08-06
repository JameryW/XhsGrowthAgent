# visual_designer: parallelize 2 creative-memory recalls

## Goal

`backend/agents/visual_designer.py:38-39` runs 2 creative-memory recalls
**serially** on every visual_designer execute (CREATING path:
content_strategist → copywriter → visual_designer → review_gate):

```python
styles = await cm.recall_style(query=plan.get("selected_topic", ""))      # :38
cover_materials = await cm.recall_materials(category="封面", limit=3)      # :39
```

Each recall does DB list + optional store asearch internally → up to 4
round trips serialized to 2 waves. Gather → ~1 concurrent wave, ~2 fewer
serial RTT before the VISUAL→astron LLM call.

## What I already know

- **2 calls, both independent.** Verified by reading `visual_designer.py:34-41`:
  - `recall_style(query=...)` (`:38`) → `styles` list → `style_dna` namespace.
  - `recall_materials(category="封面", limit=3)` (`:39`) → `cover_materials`
    list → `material_vault` namespace.
  - Disjoint namespaces, no data dependency (neither feeds the other's args).
  - `creative_ctx = cm.build_creative_context(styles, [], cover_materials)`
    (`:41`) consumes both after — sequential consumption, fine.
- **Both swallow own exceptions** (creative.py:84-90, 108-109 for
  recall_style; :214-225, 242-243 for recall_materials — each try/except
  logs warning, continues; recall_style returns `[]` or `_default_styles()`
  on total failure, recall_materials returns `[]`). Gather adds no new
  exception surface — same proof as #502/#503.
- **Return-value pattern** (no concurrent dict mutation): gather returns
  `(styles, cover_materials)`, then `build_creative_context` consumes them.
  No shared mutable state during the gather.
- `asyncio` import status in visual_designer — verify during implement; if
  not imported, add it. (File is 89 lines, currently no asyncio import.)
- `build_creative_context` (`:41`) takes `(styles, [], cover_materials)` —
  middle arg is empty plays list (visual_designer doesn't recall plays).
  Untouched.
- Test coverage: `tests/unit/agents/test_visual_designer.py` (verify exists
  + mock shape during implement). Existing tests mock CreativeMemory recalls
  and assert `visual_plan`/`creative_ctx` — gather keeps them green if
  return values are consumed identically.
- **Precedent: PR #502 (copywriter), #503 (content_strategist), #504
  (trend_scout)** — gather-parallel series, exact same idiom. #502/#503
  gathered 4 memory recalls; this is the smaller 2-recall variant (like
  #504's 2-call gather). Memory: `copywriter-parallel-memory-recalls`.

## Recommended approach (ponytail)

Gather the 2 independent recalls. Return-value pattern:

```python
import asyncio  # if not already imported

# :34-39
from backend.memory.creative import CreativeMemory

cm = CreativeMemory(account_id, store=store)
styles, cover_materials = await asyncio.gather(
    cm.recall_style(query=plan.get("selected_topic", "")),
    cm.recall_materials(category="封面", limit=3),
)

creative_ctx = cm.build_creative_context(styles, [], cover_materials)
```

~3 LOC net (gather replaces 2 serial awaits; add asyncio import). Behavior
identical: same 2 values, same `creative_ctx`, same downstream LLM call.

**No `_safe_*` wrappers needed** (unlike #504): `recall_style`/`recall_materials`
already swallow internally — call them directly in the gather. The gather's
first-exception propagation is a no-op because neither can raise to caller.

- Pros: ~2 fewer serial RTT on visual_designer (CREATING hot path) before
  VISUAL→astron; exact #502/#503 exception-surface proof; zero behavior
  change; smallest diff in the gather-parallel series.
- Cons: none. Smaller than #502/#503/#504.

**Rejected: also gather `build_creative_context` / `deposit_style`.**
`build_creative_context` is sync (not async, takes already-gathered values).
`deposit_style` (`:79`) is a write that runs AFTER the LLM call, depends on
`visual_plan` result — can't gather with the pre-LLM recalls. Out of scope.

## Requirements

- `recall_style` + `recall_materials` run via `asyncio.gather` (concurrent).
- `build_creative_context` consumes the gathered values identically.
- No `_safe_*` wrappers (recalls already swallow own exceptions).
- Zero behavior change (same `creative_ctx`, same downstream).

## Acceptance Criteria

- [ ] `visual_designer.execute` uses `asyncio.gather` for `recall_style` +
      `recall_materials`.
- [ ] Existing `tests/unit/agents/test_visual_designer.py` passes unchanged.
- [ ] New non-vacuous test: assert `recall_style` + `recall_materials` run
      concurrently (patch `asyncio.gather`, assert called once with 2
      awaitables — mirror #502/#503/#504 pattern). Must fail if reverted to
      serial. Note: if visual_designer has OTHER gathers, filter to the
      2-awaitable one (likely only 1 gather in this 89-line file).
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- visual_designer.py gather refactor (~3 LOC + asyncio import)
- 1 non-vacuous concurrency test (mirror #502/#503/#504)
- Pre-push triple green
- PR off `origin/main`, separate branch `fix/visual-designer-parallel-memory-recalls`

## Out of Scope

- Gathering `deposit_style` (post-LLM write, depends on result).
- Gathering `build_creative_context` (sync, consumes gathered values).
- Other agents (brief_analyzer `:46-47` recall_style + recall_benchmark —
  separate PR; `recall_benchmark` has a `niche` truthy guard making it
  trickier, defer).
- Other visual_designer awaits (single `_llm_ainvoke`, nothing to gather).

## Technical Notes

- File: `backend/agents/visual_designer.py` (`:34-41`) + test.
- Memory: `backend/memory/creative.py` — `recall_style` (:73),
  `recall_materials` (:203), both swallow own exceptions.
- Precedent: PR #502 (copywriter 4-recall), #503 (content_strategist
  4-recall), #504 (trend_scout 2-of-3 XHS partial-gather). Memory:
  `copywriter-parallel-memory-recalls`. This is the 4th gather-parallel
  example, simplest (2 independent recalls, no wrappers, no dependency).
- visual_designer is CREATING hot path (content_strategist → copywriter →
  visual_designer → review_gate); every workflow run hits this.
- XHS API RTT > Postgres store RTT, but these are store/DB recalls (like
  #502/#503), so ~2 fewer serial store/DB RTT (each recall = DB list +
  optional store asearch).

## Decision (ADR-lite)

**Context**: visual_designer's `execute` runs 2 creative-memory recalls
serially on the CREATING hot path. Both are independent (disjoint
namespaces), both swallow own exceptions.
**Decision**: gather the 2 recalls; no `_safe_*` wrappers (recalls already
swallow). Return-value pattern.
**Consequences**: ~2 fewer serial store/DB RTT before VISUAL→astron LLM.
Zero behavior change. ~3 LOC + 1 non-vacuous test. Simplest gather-parallel
example (#502/#503/#504 series). Low risk.
