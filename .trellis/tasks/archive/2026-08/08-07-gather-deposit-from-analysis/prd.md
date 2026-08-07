# gather deposit_from_analysis serial creative-memory writes

## Goal

`backend/services/creator_stats/analyze.py:deposit_from_analysis` (`:330-439`) runs up to 12 serial creative-memory writes on the creator-center sync path: 1 `deposit_style` + 1 `deposit_play` + ≤10 `deposit_material` (≤5 top notes × 2 entries each: title + hook). Each write is an independent DB upsert-by-key (+ optional store dual-write), no cross-write read dependency. Collapse the serial awaits into one `asyncio.gather` so the writes run concurrently. Saves up to 11 round-trips on the sync path.

## What I already know

- `deposit_from_analysis` (`:330`) — prod path: `pipeline.py:482 run_analysis` → `sync_creator_stats` route. Writes durable creative memory (style DNA / play / materials) after analyzing top notes.
- Serial writes: `deposit_style` (`:365`), `deposit_play` (`:396`), `deposit_material` ×≤10 (`:418`, `:433`).
- Counters (`styles`/`materials`/`plays`) computed from LOCAL iteration, NOT deposit return values. `styles=1` after building style, `plays=1` after building play, `materials += 1` per loop iter when entry built (title non-empty → +1, snippet non-empty → +1). Deposit returns None; counter increments regardless of deposit success (exceptions swallowed inside deposit).
- Each `deposit_*` (`creative.py:288/315/326`) wraps its body in `try/except Exception → logger.warning`, swallows ALL exceptions, returns None. → gather cannot drop errors (no raise propagates), no `_safe_*` wrapper needed (deposit self-isolates).
- Writes are independent upsert-by-key: `deposit_style` upserts by style_id (1 style, merge-lock scoped to account/tone/visual — only 1 style so no self-conflict), `deposit_play` by play_id (1 play), `deposit_material` by distinct material_id (`creator_title_{note_id}` / `creator_hook_{note_id}`). No cross-write read dependency. gather-safe.
- `deposit_style` uses `get_style_merge_lock(account_id, tone, visual)` async ctx mgr — but only 1 style deposit, no concurrent same-lock contention.
- Existing tests: `tests/unit/memory/test_creative_memory.py` covers per-deposit isolation; `tests/unit/services/creator_stats/test_resilience_and_wiring.py:47` mocks `run_analysis` upstream (deposit loop untested directly).

## Requirements

- Build all deposit coroutines into a list (style + play + ≤10 materials), `await asyncio.gather(*coros)` instead of awaiting each serially.
- Counters (`styles`/`materials`/`plays`) MUST be computed during coro-list construction (local iteration), BEFORE gather — same values as serial version (deposit success doesn't affect counters since exceptions are swallowed).
- `analysis.styles_deposited`/`materials_deposited`/`plays_deposited` assigned after gather (or before — values are pre-computed; assign before gather is fine since they're local ints).
- `import asyncio` at top of analyze.py (check if already present).
- No `_safe_*` wrapper — deposit methods self-isolate (try/except swallow + log). Bare `cm.deposit_*` calls in gather. (Per gather-parallel wrapper rule: callee swallows own exc → no wrapper.)
- Behavior-preserving: same writes happen, same counters, same return. Only timing changes (serial → concurrent).

## Acceptance Criteria

- [ ] `deposit_from_analysis` uses single `asyncio.gather` for all deposit writes.
- [ ] Counters computed during coro-list construction (not from deposit returns).
- [ ] No `_safe_*` wrapper (deposit self-isolates — verified deposit_style/play/material each have outer try/except swallowing all exc).
- [ ] `import asyncio` present.
- [ ] Behavior-preserving: cold-start early-return (`:347-352`) unchanged; counters identical for same input.
- [ ] Non-vacuous test: assert gather called (call-overlap discriminator or gather-count assertion) for the deposit path. Revert-then-fail (restore serial → test FAILs).
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest` green.

## Definition of Done

- Tests added (non-vacuous, revert-then-fail proven).
- Pre-push triple green.
- Behavior change documented (serial writes → concurrent gather; same writes, same counters, faster).
- PR off `origin/main`, separate-PR-per-feature.

## Technical Approach

**`backend/services/creator_stats/analyze.py`:**

Add `import asyncio` (if missing).

In `deposit_from_analysis`, replace serial awaits. Build coro list as entries are constructed (preserving counter logic), then one gather:

```python
cm = CreativeMemory(analysis.account_id, store=store)
styles = 0
materials = 0
plays = 0
coros = []

tone_finding = next((f for f in analysis.findings if f.finding_type == "tone"), None)
top = sorted(notes, key=lambda n: n.engagement_rate, reverse=True)[:5]
top_snippets = [s for n in top if (s := _note_content_snippet(n))]

style = _style_from_finding(tone_finding, analysis.avg_engagement_rate, top_snippets)
coros.append(cm.deposit_style(style))
styles = 1

# ... build play (same as now) ...
coros.append(cm.deposit_play(play))
plays = 1

for n in top:
    snippet = _note_content_snippet(n)
    if not snippet:
        continue
    rate = as_fraction_engagement_rate(n.engagement_rate)
    title = (n.title or "").strip()
    if title:
        entry = MaterialEntry(...)  # same as now
        coros.append(cm.deposit_material(entry))
        materials += 1
    body_entry = MaterialEntry(...)  # same as now
    coros.append(cm.deposit_material(body_entry))
    materials += 1

await asyncio.gather(*coros)

analysis.styles_deposited = styles
analysis.materials_deposited = materials
analysis.plays_deposited = plays
return analysis
```

Counter values identical to serial version: `styles=1`, `plays=1`, `materials` = (count of title entries) + (count of snippet entries), computed during construction — same as serial (serial also `+= 1` after building entry, before/after await — await swallows exc so no difference).

**Wrapper rule (no wrapper):** `deposit_style`/`deposit_play`/`deposit_material` each have outer `try/except Exception → logger.warning` swallowing all exceptions (verified `creative.py:290-313`, `:317-324`, `:328-337`). gather cannot propagate a first-exc because none raise. No `_safe_*` wrapper needed. Per gather-parallel series wrapper rule (#502 et al.): callee swallows own exc → bare call in gather, no wrapper.

## Test (non-vacuous)

Find existing test: `tests/unit/services/creator_stats/test_resilience_and_wiring.py` or `tests/unit/services/creator_stats/test_client_and_analysis.py`. Add:

`test_deposit_from_analysis_gathers_writes`:
- Call `deposit_from_analysis` with a small analysis + notes (≥2 top notes with title+snippet → ≥4 material coros + style + play = ≥6 coros).
- Discriminator: patch `CreativeMemory.deposit_style`/`deposit_play`/`deposit_material` (or the `cm` instance methods) to record call timestamps + `asyncio.sleep(0)` yield. Assert ≥2 deposits overlap (call-overlap discriminator — start of one < finish of another). OR assert `asyncio.gather` called once with N coros (gather-count assertion via patching `asyncio.gather` on the module — but module-level `asyncio` patch leaks; prefer call-overlap discriminator per #519/#520 lesson).
- Assert counters correct: `styles_deposited=1`, `plays_deposited=1`, `materials_deposited` = expected count.
- Revert-then-fail: restore serial awaits → call-overlap assertion FAILs (no overlap, serial).

**shared-asyncio-module patch leak trap (#515):** `analyze.py` will `import asyncio` — patching `asyncio.gather` is global. Use call-overlap discriminator (start/finish timestamps + `asyncio.sleep(0)` yield) instead of patching gather. Patch the `cm.deposit_*` bound methods (instance-level, not module asyncio).

**MagicMock-TypeError trap:** N/A — no Settings, no `>=`/`range()` on mocked values. Counters are real ints from local iteration.

## Decision (ADR-lite)

**Context:** Up to 12 serial DB+store writes on creator-center sync path. Each is independent upsert-by-key, self-isolating (try/except swallow).

**Decision:** Single `asyncio.gather` over all deposit coroutines. No wrapper (deposit self-isolates). Counters pre-computed during coro construction.

**Consequences:** Up to 11 RTs saved (serial → concurrent). Same writes, same counters (deposit success doesn't affect counters). gather-safe (independent keys, no cross-write read dep, deposit_style merge-lock has no same-lock concurrent contention — only 1 style). Multi-write best-effort non-transactional (already true serially — one deposit failing doesn't roll back others).

## Out of Scope

- copywriter 2-deposit gather (copywriter.py:192,206) — separate PR, smaller win (2 calls). Investigator ranked #2.
- evaluation double get_account — med risk (shared security helper), defer.
- analytics get_dashboard serial — med complexity (cache semantics), defer.
- Transactional deposit (all-or-nothing) — out of scope, best-effort by design.
- Changing deposit_* signatures or return values.

## Technical Notes

- Files: `backend/services/creator_stats/analyze.py` (`:330-439` `deposit_from_analysis`).
- Test: `tests/unit/services/creator_stats/test_*.py` (find existing deposit_from_analysis coverage).
- gather-parallel series #14 (after #521): no-wrapper variant (deposit self-isolates), call-overlap discriminator test (avoid asyncio.gather module patch leak #515).
- `pipeline.py:482 run_analysis` → `sync_creator_stats` route = prod path (verified).
- Counters local-iteration-computed → gather behavior-preserving.
