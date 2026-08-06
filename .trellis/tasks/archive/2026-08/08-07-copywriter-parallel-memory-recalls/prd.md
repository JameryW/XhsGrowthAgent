# Copywriter serial memory recalls → asyncio.gather

## Goal

`backend/agents/copywriter.py:41-61` runs 4 independent memory recalls **serially**
before the LLM call, on every workflow run (copywriter → visual_designer →
review_gate is the hot path):

```python
recall_query = plan.get("selected_topic", "") or brief.get("product_name", "")
styles = await cm.recall_style(query=recall_query)                    # :41
materials = await cm.recall_materials(category="文案片段", tags=[...]) # :42
past_content = await self._recall_memory(store, account_id, query=recall_query,
    namespace="content_history", limit=3)                              # :45-51
audience_prefs = await self._recall_memory(store, account_id, query=...,
    namespace="audience_preferences", limit=3)                         # :52-61
```

Each recall does 1-2 network round-trips (durable DB list + LangGraph store
`asearch` against Postgres — see `recall_style` at `memory/creative.py:73`,
which does `cm_db.list_styles` THEN `self._store.asearch`). Serialized = up to
~8 RTTs on the copywriter critical path before the LLM call. These 4 are
independent read-only recalls with **disjoint namespaces** (`style_dna`,
`material_vault`, `content_history`, `audience_preferences`) and **no data
dependency** between them — `recall_query` is computed once at `:40` before
all four.

Gather collapses 4 serial waves → 1 concurrent wave. Real latency win on a
hot path, not a fake optimization.

## What I already know

- **Verified independence** (read all 4 recall bodies):
  - `recall_style` (`memory/creative.py:73`) — reads DB `list_styles` + store
    `asearch(self.style_dna_ns, ...)`, writes only local `results` list.
  - `recall_materials` (`memory/creative.py:203`) — same shape, `vault_ns`.
  - `_recall_memory` (`agents/base.py:120`) — store `asearch` on the passed
    `namespace` (here `content_history` / `audience_preferences`).
  - Disjoint namespaces → no shared store key. No cross-call mutation. Safe
    to run concurrently.
- `recall_query` computed at `:40`, used by `:41` and `:45` — both just read
  it, neither mutates. The `audience_prefs` query string (`:55-58`) is built
  inline from `plan`/`brief`, independent of the other 3 results.
- **5th call NOT gathered:** `:89` `build_mode_creative_context` is in its own
  `try/except` (`:82-93`) for resilience (creator_stats import may fail on
  accounts without it). Per investigator's "keep simple" recommendation +
  ponytail, leave `:82-93` sequential — gathering it would require
  restructuring the try/except around the gather result, more diff, marginal
  gain (it's 1 call). The 4 memory recalls are the win.
- Post-gather, the results are consumed in order (`:64-79` builds
  `memory_context` from `past_content`, `audience_prefs`, then
  `build_creative_context(styles, [], materials)` at `:77`). Order of
  *completion* doesn't matter — only that all 4 return before `:64`. Gather
  preserves result order by input order, so `styles, materials, past_content,
  audience_prefs = await asyncio.gather(...)` is a drop-in.
- `asyncio` not yet imported in copywriter.py — needs `import asyncio`.
- Test coverage: `tests/unit/agents/test_copywriter.py` mocks the recalls
  (verify exact mock shape during implement). Existing tests assert output
  (memory_context content), not call order — so swapping serial→gather keeps
  them green as long as return values are unchanged.
- Precedent: content_strategist already uses `asyncio.gather` for ripple
  predict+pmf (`:210`). Same idiom in the same codebase.

## Recommended approach (ponytail)

Replace the 4 serial `await` assignments with one `asyncio.gather`:

```python
import asyncio  # add to imports

# :40-61 becomes:
recall_query = plan.get("selected_topic", "") or brief.get("product_name", "")
styles, materials, past_content, audience_prefs = await asyncio.gather(
    cm.recall_style(query=recall_query),
    cm.recall_materials(category="文案片段", tags=["高转化", "爆款标题"]),
    self._recall_memory(
        store, account_id, query=recall_query,
        namespace="content_history", limit=3,
    ),
    self._recall_memory(
        store, account_id,
        query=(
            f"audience preference for"
            f" {plan.get('content_type', 'note') or brief.get('style_requirements', 'note')}"
        ),
        namespace="audience_preferences", limit=3,
    ),
)
```

Leave `:82-93` (build_mode_creative_context try/except) untouched.

~10 LOC net (gather block replaces 4 awaits, +1 import). Behavior identical:
same 4 values assigned to same names, consumed identically below.

- Pros: ~3-4 fewer serial RTTs on the copywriter hot path per run; exact
  precedent (content_strategist:210 gather); zero behavior change; existing
  output-asserting tests stay green.
- Cons: one subtlety — if any one recall raises, `gather` propagates the
  first exception. But each recall already swallows its own exceptions
  internally (`recall_style` wraps DB+store in try/except, returns `[]` on
  failure; `_recall_memory` similarly). So no new exception surface. Verify
  during implement that none of the 4 can raise to the caller.

**Rejected: also gather `build_mode_creative_context` (`:89`).** Its separate
try/except is intentional resilience (creator_stats optional). Folding into
the gather means wrapping the whole gather in try/except or losing that
isolation. Marginal gain (1 call). Keep separate. Note for later if needed.

## Requirements

- `copywriter.py:41-61` 4 serial memory recalls run via `asyncio.gather`.
- `build_mode_creative_context` (`:82-93`) stays in its own try/except,
  sequential.
- Return values + downstream `memory_context` construction unchanged.
- `asyncio` imported.

## Acceptance Criteria

- [ ] `copywriter.py` uses `asyncio.gather` for the 4 recalls; no 4 serial
      `await` assignments remain at `:41-61`.
- [ ] `build_mode_creative_context` try/except block untouched.
- [ ] Existing `tests/unit/agents/test_copywriter.py` passes unchanged
      (output-based assertions, not call-order).
- [ ] New non-vacuous test: assert the 4 recalls run concurrently (e.g.
      patch `asyncio.gather` and assert it's called once with 4 coroutines,
      OR use AsyncMock side_effects with an asyncio.Event proving overlap).
      Must fail if reverted to serial awaits. Verify the existing tests still
      assert memory_context content (equivalence) so the gather doesn't
      silently change output.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- copywriter.py gather refactor (~10 LOC)
- 1 non-vacuous concurrency test
- Pre-push triple green
- PR off `origin/main`, separate branch

## Out of Scope

- Gathering `build_mode_creative_context` (separate resilience try/except).
- Refactoring the memory_context string construction.
- Other agents' recall patterns (audit separately if needed).
- The 4 dead LLM tools deletion (investigator rank #2, separate PR — larger
  diff, maintenance not latency, coordinate timing with #480).

## Technical Notes

- File: `backend/agents/copywriter.py` (`:41-61` gather target, `:82-93`
  leave-alone) + test.
- Recall impls: `backend/memory/creative.py:73` (recall_style), `:203`
  (recall_materials); `backend/agents/base.py:120` (_recall_memory). All
  read-only, disjoint namespaces, swallow own exceptions.
- Precedent: `backend/agents/content_strategist.py:210`
  `asyncio.gather(_predict(), _validate_pmf())` — same idiom.
- Investigator (`caveman:cavecrew-investigator`) ranked this #1: measurable
  latency on hot path, <15 LOC. Rank #2 (dead-tool deletion) deferred.
- Latency context: copywriter runs every workflow before the WRITING→astron
  LLM call. 4 serial recalls × (DB list + store asearch) RTT → 1 concurrent
  wave. Exact RTT saving depends on Postgres latency but structurally ~3-4
  fewer serial round-trips.

## Decision (ADR-lite)

**Context**: copywriter runs 4 independent read-only memory recalls serially
on the hot path before its LLM call, each 1-2 DB/store round-trips. No data
dependency, disjoint namespaces. Same gather idiom already used in
content_strategist:210.
**Decision**: gather the 4 recalls into one `asyncio.gather`. Leave the
resilience-isolated `build_mode_creative_context` try/except sequential.
**Consequences**: ~3-4 fewer serial RTTs on the copywriter critical path per
run. Zero behavior change (same values, same consumption). ~10 LOC + 1
non-vacuous concurrency test. Low risk — recalls already swallow own
exceptions so gather adds no new exception surface.
