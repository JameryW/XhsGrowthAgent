# gather analyst serial store_insight + store_strategy_note writes

## Goal

`backend/agents/analyst.py:114-119` two serial loops write to memory store: `for insight: await mm.store_insight(...)` then `for rec: await mm.store_strategy_note(...)`. N+M sequential `store.aput` writes (UUID keys, independent, post-publish analyst node). Gather → N+M → 1 concurrent wave. **Write-gather variant** (extends #512) — `store_insight`/`store_strategy_note` are bare `store.aput` calls that do NOT swallow exc → need `_safe_*` wrapper for per-row isolation. Gather-parallel series #13.

## What I already know

- `analyst.py:114-116` `for insight in analytics.get("insights", []): await mm.store_insight(store, insight, {"source": "analyst", "post_id": post_id})` — serial per-insight write.
- `analyst.py:118-119` `for rec in analytics.get("recommendations", []): await mm.store_strategy_note(store, rec, {"source": "analyst"})` — serial per-rec write.
- `store_insight` (`backend/memory/store.py:69-74`): bare `await store.aput(self.insights_ns, key=str(uuid.uuid4()), value={...})` — NO try/except, raises propagate.
- `store_strategy_note` (`backend/memory/store.py:85-90`): bare `await store.aput(self.strategy_ns, key=str(uuid.uuid4()), value={...})` — NO try/except, raises propagate.
- Independent UUID keys (random uuid4 per write) → no key collision, order irrelevant.
- Both write to memory store (post-publish analyst node, once per workflow).
- **NOT hot poll** — analyst runs once post-publish. Impact 3.
- `post_id` computed at `:115` inside loop (same value each iter, from `publish_result.get("post_id", "")`) — hoist outside gather.
- `content_history` aget/update at `:121-134` is SEPARATE (order-dependent: aget then conditional update) — do NOT gather with the writes. Leave serial.
- `import asyncio` in analyst.py? Check.

## Write-gather wrapper rule (from #512)

`store_insight`/`store_strategy_note` are bare calls (no internal swallow). Current serial behavior: first write failure raises → remaining writes skipped (abort). 

**Two options:**
1. **Wrapper (resilience improvement, behavior change):** `_safe_store_insight`/`_safe_store_note` each with own try/except → warning log, swallow. Gather all. More writes succeed on partial failure (better than serial abort). BUT behavior change: serial aborted on first fail; gathered+wrapped continues. This is the #512 pattern (`_demote_one` wrapper).
2. **No wrapper, bare gather (behavior-equivalent):** gather bare calls → first exc propagates, rest may or may not complete (gather cancels on first exc). Behavior ~equivalent to serial first-failure-abort BUT partial writes may differ (gather may complete some before the failing one raises; serial commits in order up to failure).

**Decision: Option 1 (wrapper).** Rationale: #512 established write-gather with `_safe_*` wrapper for per-row isolation. Memory store writes are best-effort (insights/notes are non-critical post-publish telemetry — losing one shouldn't abort the rest). The wrapper makes partial failure non-fatal, which is the desired semantics for memory writes (mirror how `_recall_memory` swallows → `[]`). This is a deliberate resilience improvement, documented as behavior change (serial abort → gather-continue-on-partial-failure).

**Risk:** low. Memory writes are post-publish telemetry, not transactional. Wrapper logs failure (visibility preserved). If ALL writes fail, analyst still returns analytics result (writes are fire-and-forget side-effects, not return-value-affecting).

## Requirements

- Hoist `post_id = publish_result.get("post_id", "")` outside the gather (currently inside loop `:115`, same value each iter).
- Add `_safe_store_insight(mm, store, insight, post_id)` + `_safe_store_strategy_note(mm, store, rec)` helpers (module-level or inline closures) — each try/except → `logger.warning` (exc_info=True), swallow.
- `await asyncio.gather(*(_safe_store_insight(mm, store, insight, post_id) for insight in insights), *(_safe_store_strategy_note(mm, store, rec) for rec in recommendations))`.
- `content_history` aget/update (`:121-134`) stays serial (order-dependent, separate block).
- `import asyncio` present (add if missing).
- Behavior: partial write failure no longer aborts remaining writes (resilience improvement, documented).

## Acceptance Criteria

- [ ] `post_id` hoisted outside gather.
- [ ] `_safe_store_insight` + `_safe_store_strategy_note` wrappers (try/except → warning, swallow).
- [ ] `asyncio.gather` over all insight + rec writes.
- [ ] `content_history` block unchanged (serial).
- [ ] `import asyncio` present.
- [ ] Non-vacuous test: assert gather used + per-row failure isolation (one write fails, others still stored). Revert-then-fail.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest` green.

## Definition of Done

- Tests added (non-vacuous, revert-then-fail proven).
- Pre-push triple green.
- Behavior change documented (serial abort → gather continue-on-partial-failure).
- PR off `origin/main`, separate-PR-per-feature.

## Technical Approach

**`backend/agents/analyst.py` (`:110-119`):**

```python
        # 将洞察存入原有记忆（保持兼容）
        from backend.memory.store import MemoryManager

        mm = MemoryManager(account_id)
        post_id = publish_result.get("post_id", "")
        insights = analytics.get("insights", [])
        recommendations = analytics.get("recommendations", [])
        await asyncio.gather(
            *(_safe_store_insight(mm, store, insight, post_id) for insight in insights),
            *(_safe_store_strategy_note(mm, store, rec) for rec in recommendations),
        )
```

Module-level helpers (or inline async closures — prefer module-level for testability):

```python
async def _safe_store_insight(
    mm: MemoryManager, store: BaseStore, insight: str, post_id: str
) -> None:
    try:
        await mm.store_insight(store, insight, {"source": "analyst", "post_id": post_id})
    except Exception:
        logger.warning("store_insight failed", exc_info=True)


async def _safe_store_strategy_note(
    mm: MemoryManager, store: BaseStore, rec: str
) -> None:
    try:
        await mm.store_strategy_note(store, rec, {"source": "analyst"})
    except Exception:
        logger.warning("store_strategy_note failed", exc_info=True)
```

**Wrapper pattern (from #512 `_demote_one`):** per-row try/except → warning (exc_info=True for server logs), swallow. Gather first-exception propagation becomes no-op (none can raise to caller). All rows attempt; failures logged.

**`content_history` block (`:121-134`) unchanged** — order-dependent aget→update, separate concern.

**`import asyncio`:** check analyst.py — likely present (agents often). Add if missing.

## Test (non-vacuous, find existing analyst test file)

Check `tests/unit/agents/test_analyst*.py`. Add:

`test_stores_insights_and_notes_concurrently`:
- Patch `MemoryManager.store_insight` + `store_strategy_note` (or underlying `store.aput`).
- Use call-overlap discriminator (#519/#520 pattern): each mock records start/finish via `asyncio.get_event_loop().time()` + `asyncio.sleep(0)` yield. Assert overlap (concurrency). AVOID patching `asyncio.gather` globally (#515 shared-asyncio-module leak).
- Revert-then-fail: revert to serial loops → overlap absent → FAIL. Restore → PASS.

`test_partial_write_failure_does_not_abort_others`:
- Make `store_insight` raise on the 2nd call, others succeed.
- Assert remaining insights + all recs still stored (wrapper isolation).
- Revert-then-fail: revert to bare gather (no wrapper) → 2nd failure aborts rest → assert remaining stored FAILs. OR revert to serial → 2nd failure aborts loop → recs never run → FAIL. Either proves wrapper non-vacuous.

Mock `analytics` return: `{"insights": ["i1", "i2", "i3"], "recommendations": ["r1", "r2"]}`. Mock `publish_result`: `{"post_id": "p1"}`. Mock store (BaseStore) — `aput` async mock.

## Decision (ADR-lite)

**Context:** N+M serial memory writes in analyst (post-publish). Bare calls (no swallow). Write-gather series established (#512).

**Decision:** Gather with `_safe_*` wrapper (per-row try/except → warning, swallow). Resilience improvement: partial failure no longer aborts remaining writes. Mirror `_recall_memory` swallow semantics for write side.

**Consequences:** N+M → 1 concurrent wave. Partial write failures logged + skipped (better than serial abort). Memory writes are best-effort post-publish telemetry — non-transactional, safe to continue on partial failure. `content_history` block unchanged (order-dependent).

## Out of Scope

- `content_history` aget/update (`:121-134`) — order-dependent, separate.
- Other analyst internals.
- Caching/batching store writes (separate concern).

## Technical Notes

- Files: `backend/agents/analyst.py` (`:110-119` writes + new helpers), `backend/memory/store.py` (`:69`/`:85` — read only, no change).
- Test: `tests/unit/agents/test_analyst*.py` (find existing).
- Gather-parallel series: #502-#508, #510, #512, #515, #519, #520, this = #13.
- Write-gather wrapper rule (from [[copywriter-parallel-memory-recalls]] #512): bare call no swallow + write/db_update → `_safe_*`/`_demote_one` wrapper for per-row isolation. Read recall/fetch internally swallow → no wrapper.
- call-overlap discriminator (from #519/#520): timestamp windows + `asyncio.sleep(0)` yield, no global `asyncio.gather` patch.
- `post_id` hoist: currently inside loop `:115` (same value each iter) — hoist outside gather for clarity + avoid re-compute.
