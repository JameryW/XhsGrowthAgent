# free route: parallelize 3 creative-memory recalls

## Goal

`backend/api/routes/free.py:278-282` runs 3 creative-memory recalls
**serially** on every free-draft create (hot user-facing path — POST creates
a draft + attaches creative context):

```python
styles = await cm.recall_style(query=f"free draft {niche}".strip())       # :278
plays = await cm.recall_plays(condition="free creation", niche=niche)     # :279
materials = await cm.recall_materials(category="文案片段", tags=[...])     # :280-282
```

Each recall does DB list + optional store asearch → up to 6 round trips
serialized. Gather → ~1 concurrent wave, fewer serial RTT on the draft-create
path. First gather-parallel in an **API route** (agents all done in
#502-#508).

## What I already know

- **3 calls, all independent.** Verified by reading `free.py:273-283`:
  - `recall_style(query=...)` (`:278`) → `styles` list → `style_dna` ns.
  - `recall_plays(condition, niche)` (`:279`) → `plays` list →
    `conversion_playbook` ns.
  - `recall_materials(category, tags)` (`:280-282`) → `materials` list →
    `material_vault` ns.
  - Disjoint namespaces, no data dependency (`niche` built from `record` at
    `:277` before the recalls; none feeds another's args).
  - `creative_context = cm.build_creative_context(styles, plays, materials)`
    (`:283`) consumes all 3 after — sequential consumption, fine.
- **All 3 swallow own exceptions internally** (creative.py: recall_style
  :84-90/:108-109 → []/_default_styles(); recall_plays :167-168/:186-187 → [];
  recall_materials :224-225/:242-243 → []). Gather adds no new exception
  surface — same proof as #502-#508.
- **Outer try/except wraps the whole block** (`:273-285`): `try: ... except
  Exception as e: logger.debug("free draft creative_context skipped: %s", e)`.
  This outer try is a safety net — but since all 3 recalls swallow internally,
  it never actually fires (same as agent pattern). After gather, the outer
  try stays as-is (still a valid safety net, behavior unchanged).
- **No niche-guard wrinkle** (unlike #507): `recall_plays(condition, niche)`
  handles empty niche internally (creative.py:161-165 falls back to all plays
  when niche empty). No outer `if niche else None` guard to preserve. Direct
  gather, no `_noop_*` wrapper. Same as #508 (internal zero-cost handling).
- `asyncio` NOT imported in free.py (verified — only logging, uuid, datetime,
  typing, fastapi, pydantic, backend.*). Must add `import asyncio`.
- `build_creative_context` (`:283`) takes `(styles, plays, materials)` — all
  3 gathered values. Untouched.
- Test coverage: `tests/unit/api/routes/test_free*.py` or
  `tests/unit/routes/test_free*.py` (verify exists + mock shape during
  implement). Existing tests mock CreativeMemory recalls and assert
  `creative_context` — gather keeps them green if return values consumed
  identically.
- **Precedent: PR #502/#503** (3-4 recall gather in agents). This is the same
  idiom but in an API route — 8th gather-parallel example, first non-agent.

## Recommended approach (ponytail)

Gather the 3 independent recalls. Return-value pattern:

```python
import asyncio  # add to imports

# :276-283
cm = CreativeMemory(account_id, store=store)
niche = str(record.get("niche") or "")
styles, plays, materials = await asyncio.gather(
    cm.recall_style(query=f"free draft {niche}".strip()),
    cm.recall_plays(condition="free creation", niche=niche),
    cm.recall_materials(category="文案片段", tags=["高转化", "爆款标题", "开头"]),
)
creative_context = cm.build_creative_context(styles, plays, materials)
```

~4 LOC net (gather replaces 3 serial awaits + `import asyncio`). Behavior
identical: same 3 values, same `creative_context`, same response.

**No `_safe_*`/`_noop_*` wrappers** (all 3 recalls swallow own exceptions
internally; recall_plays handles empty niche internally — no outer guard to
preserve). Same as #508. Outer try/except stays as safety net.

- Pros: ~2 fewer serial RTT on free-draft create (hot user-facing path);
  exact #502-#508 exception-surface proof; zero behavior change; first
  gather-parallel in API route (extends series beyond agents).
- Cons: none.

**Rejected: also gather `get_suggestions_for_mode` (`:269`).** That's a
separate try/except block (`:266-272`) for `creative_suggestions` (different
data, different service). Could gather it with the recalls, but it's a
different code path (creator_stats service, not CreativeMemory) + its own
try/except. Mixing complicates exception surface. Keep separate. Ponytail:
gather the 3 CreativeMemory recalls only.

## Requirements

- `recall_style` + `recall_plays` + `recall_materials` run via
  `asyncio.gather` (concurrent).
- `build_creative_context` consumes gathered values identically.
- No `_safe_*`/`_noop_*` wrappers (recalls already swallow; recall_plays
  handles empty niche internally).
- Outer try/except (`:273-285`) stays as safety net.
- Zero behavior change (same `styles`, `plays`, `materials`, `creative_context`).

## Acceptance Criteria

- [ ] `free.py` create-draft path uses `asyncio.gather` for the 3 recalls.
- [ ] `import asyncio` added.
- [ ] Existing free-route tests pass unchanged.
- [ ] New non-vacuous test: assert the 3 recalls run concurrently (patch
      `asyncio.gather`, assert called once with 3 awaitables). Must FAIL if
      reverted to serial. Note: verify how many gathers free.py module has
      after change (likely only 1 — filter by 3-awaitable, or assert 1 call).
      If multiple, use __qualname__ discriminator (#506 pattern).
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- free.py gather refactor (~4 LOC + `import asyncio`)
- 1 non-vacuous concurrency test (mirror #502/#503/#508 pattern)
- Pre-push triple green
- PR off `origin/main`, separate branch `fix/free-route-parallel-creative-recalls`

## Out of Scope

- Gathering `get_suggestions_for_mode` (separate service + try/except).
- Other free-route awaits.
- Other API routes (separate audits — evaluation.py #3/#4 from investigator
  are dedupe/N+1 patterns, different idiom, separate PRs).

## Technical Notes

- File: `backend/api/routes/free.py` (`:276-283`) + test.
- Memory: `backend/memory/creative.py` — recall_style (:73), recall_plays
  (:145), recall_materials (:203), all swallow own exceptions.
- Precedent: PR #502 (copywriter 4-recall), #503 (content_strategist 4-recall),
  #505 (visual_designer 2-recall), #507 (brief_analyzer 2-recall + guard),
  #508 (analyst 2-recall). Memory: `copywriter-parallel-memory-recalls`.
  This is the 8th gather-parallel example — first in an API route (non-agent).
- free-draft create is hot user-facing path (POST /free/drafts).
- asyncio NOT imported in free.py — add it.

## Decision (ADR-lite)

**Context**: free-draft create runs 3 creative-memory recalls serially on the
hot user-facing path. All independent (disjoint namespaces), all swallow own
exceptions internally, recall_plays handles empty niche internally (no outer
guard).
**Decision**: gather the 3 recalls; no `_safe_*`/`_noop_*` wrappers (all
swallow; recall_plays internal handling is zero-cost). Return-value pattern.
Outer try/except stays as safety net.
**Consequences**: ~2 fewer serial RTT on free-draft create. Zero behavior
change. ~4 LOC + 1 non-vacuous test. 8th gather-parallel example, first in
API route (extends series beyond agents). Low risk.
