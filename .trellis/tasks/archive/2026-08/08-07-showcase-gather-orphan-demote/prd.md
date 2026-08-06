# gather orphaned showcase row demotions

## Goal

`backend/api/routes/public_showcase.py:580-618` `_demote_orphaned_public_rows`
runs `await db_update(row.thread_id, ...)` **serially inside a for-loop** —
one DB round trip per orphaned public row (rows whose account was deleted).
Called on every public showcase listing when accounts have been deleted
(`list_public_cases` → `_demote_orphaned_public_rows`). Gather → 1 concurrent
wave, N serial DB writes → ~1 wave.

```python
:591  kept: list[WorkflowRow] = []
:592  for row in rows:
:593      if _account_still_exists(row, existing):
:594          kept.append(row)
:595          continue
:596      if _visibility(row) not in _PUBLIC_VISIBILITIES:
:597          continue
:598      try:
:599          await db_update(row.thread_id, ...)   # serial DB write per orphan
:600          row.showcase_visibility = "private"
:601          row.showcase_featured = False
:602          row.featured_rank = None
:603      except Exception:
:604          ...warning...
:617  return kept
```

## What I already know

- **Per-row work is independent.** Each `db_update(row.thread_id, ...)` writes
  a distinct row (distinct `thread_id`). No data dependency between rows.
  Order irrelevant — demoting to private is idempotent.
- **Each row has its own try/except** (`:598-617`) — logs per-row failure +
  continues. **Per-row exception isolation must be preserved.** One row's
  `db_update` failure must not abort the others. Gather first-exception
  propagation would break this — so wrap each row's work in a
  `_demote_one(row)` coroutine with its own try/except (matches `:955`
  `_backfill` pattern in same module).
- **`kept` construction is filter logic, not parallel work.** Current loop:
  account-exists → `kept.append` + continue; orphaned-non-public → `continue`
  (not kept, not demoted); orphaned-public → demote (not kept). So `kept` =
  account-exists rows only. **Partition first** (serial, cheap — pure
  in-memory filter), then **gather-demote the orphaned-public subset**.
- **Row mutation is per-row** (`:600-602` sets `row.showcase_visibility` etc.
  on the row's own object). Return-value pattern — no concurrent shared-state
  mutation. Gather-safe.
- **`_existing_account_ids()` already fetched once** (`:584`) before the loop
  — not in the loop. Good, no N+1 there.
- **Established module idiom**: `:955` `await asyncio.gather(*(_backfill(row)
  for row in pending))` — each `_backfill` wraps single-row work + own
  try/except. Same shape. `:1037` similar. This loop predates/misses the
  pattern (investigator note confirmed).
- **No covering tests** (codegraph: `_demote_orphaned_public_rows` ⚠️ no
  covering tests). Need new test file `tests/unit/api/test_public_showcase_demote.py`
  (or extend `tests/unit/api/test_public_showcase.py` if it exists — verify).
- **`asyncio` already imported** in public_showcase.py (`:955` uses
  `asyncio.gather`, `:59` uses `asyncio.Task`). No import needed.
- **`db_update` signature**: `db_update(thread_id, **fields)` — verify exact
  import + signature during implement (used at `:599`).

## Recommended approach (ponytail)

Partition rows into `kept` (account-exists) vs `to_demote` (orphaned-public),
then gather-demote `to_demote` via per-row `_demote_one` wrapper. Mirror
`:955` `_backfill` shape exactly.

```python
async def _demote_one(row: WorkflowRow) -> None:
    """Demote a single orphaned public row to private; swallow per-row failure."""
    try:
        await db_update(
            row.thread_id,
            showcase_visibility="private",
            showcase_featured=False,
            featured_rank=None,
            approved_at=None,
            approved_by=None,
        )
        row.showcase_visibility = "private"
        row.showcase_featured = False
        row.featured_rank = None
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "failed to demote orphaned public showcase %s",
            row.thread_id,
            exc_info=True,
        )


async def _demote_orphaned_public_rows(rows: list[WorkflowRow]) -> list[WorkflowRow]:
    """Hide + persist private for public/unlisted rows whose account was deleted."""
    if not rows:
        return rows
    existing = await _existing_account_ids()
    if not existing:
        pass  # (keep existing comment re: fail-open on empty accounts table)
    kept: list[WorkflowRow] = []
    to_demote: list[WorkflowRow] = []
    for row in rows:
        if _account_still_exists(row, existing):
            kept.append(row)
            continue
        if _visibility(row) in _PUBLIC_VISIBILITIES:
            to_demote.append(row)
    if to_demote:
        await asyncio.gather(*(_demote_one(row) for row in to_demote))
    return kept
```

~+12 LOC (wrapper) / -8 LOC (loop simplified) ≈ net +4 LOC + 1 test.

**Behavior preservation:**
- `kept` = account-exists rows (same as before — orphaned rows never kept,
  whether demoted or skipped-non-public).
- Orphaned-public rows demoted via gather (same `db_update` call, same row
  mutation, same per-row try/except → warning). One row's failure doesn't
  abort others (each `_demote_one` swallows).
- Orphaned-non-public rows: skipped (not in `kept`, not in `to_demote`) —
  same as before (`:596-597` continue).
- Empty `existing` set: `to_demote` would include all orphaned-public rows
  (since `_account_still_exists` returns False for all when existing is empty
  + row has account_id). **Same as before** — current loop also demotes all
  when existing is empty (per `:586-590` comment: "filter by empty → demote
  all which is safer than leaking"). Preserved.

**Edge case — row with no account_id**: `_account_still_exists` (`:571-577`)
returns False for empty `aid`. So no-account-id public rows → orphaned →
demoted. **Same as before** (current loop hits the same `_account_still_exists`
check). Preserved.

- Pros: N serial DB writes → 1 concurrent wave on orphan-demotion path;
  matches established `:955`/`:1037` module idiom; per-row exception
  isolation preserved via `_demote_one` wrapper; zero behavior change.
- Cons: none. Slightly more LOC (wrapper) but matches module convention.

**Rejected: gather inside the existing single loop.** Can't — `kept.append`
(filter) interleaves with demote (parallel work). Partition-then-gather is
cleaner + matches `:955` (which also partitions `pending` then gathers).

**Rejected: batch UPDATE (single SQL `WHERE thread_id IN (...)`).** `db_update`
is the existing abstraction (used everywhere). A bespoke batch SQL diverges
from convention + needs separate test surface. Ponytail: use the existing
`db_update` + gather, matching `:955`.

## Requirements

- Orphaned-public row demotions run via `asyncio.gather` (concurrent), not
  serial for-loop.
- Per-row exception isolation preserved (`_demote_one` wrapper, own try/except
  → warning, continues).
- `kept` filter logic unchanged (account-exists rows only).
- Orphaned-non-public rows still skipped (not kept, not demoted).
- Empty `existing` set behavior preserved (demote all orphaned-public).
- Zero behavior change (same rows demoted, same `kept` returned, same
  per-row mutation, same warnings).

## Acceptance Criteria

- [ ] `_demote_orphaned_public_rows` partitions `kept` vs `to_demote`, gathers
      `to_demote` via `_demote_one` wrapper.
- [ ] `_demote_one` has own try/except → warning, swallows per-row failure.
- [ ] `kept` returned = account-exists rows (unchanged).
- [ ] New non-vacuous test: assert `db_update` calls run concurrently (patch
      `asyncio.gather`, assert called once with N awaitables where N =
      orphaned-public count). Must FAIL if reverted to serial loop
      (revert-then-fail). Also assert `kept` = account-exists rows only +
      orphaned-public rows mutated to private. Since no existing test
      coverage, may need new test file + fixtures (mock `db_list`/rows,
      `_existing_account_ids`, `db_update`).
- [ ] `ruff format --check .` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- public_showcase.py gather refactor (~+4 LOC net + `_demote_one` wrapper)
- 1 non-vacuous concurrency + correctness test (new — no existing coverage)
- Pre-push triple green
- PR off `origin/main`, separate branch `perf/showcase-gather-orphan-demote`

## Out of Scope

- `db_update` batch SQL rewrite (use existing abstraction + gather).
- Other public_showcase paths (`:955`/`:1037` already gathered).
- `_resolve_case` / `_resolve_any_case` (separate paths).
- ripple_service config extraction (separate PR).

## Technical Notes

- File: `backend/api/routes/public_showcase.py` (`:580-618` + new `_demote_one`).
- `asyncio` already imported (`:955` uses gather).
- Established idiom: `:955` `asyncio.gather(*(_backfill(row) for row in pending))`.
- `db_update(thread_id, **fields)` — verify exact import/signature during implement.
- `_existing_account_ids` (`:558`), `_account_still_exists` (`:571`),
  `_visibility` (`:123`), `_PUBLIC_VISIBILITIES` (`:72`) — all unchanged.
- Caller: `list_public_cases` (`:580` 1 caller per codegraph) — public listing
  read path.
- No existing test coverage (codegraph ⚠️) — new test file likely needed.
- Precedent: #450 (list N+1 gather), #502-#510 (gather-parallel series).
  Memory: `copywriter-parallel-memory-recalls`, `concurrent-checkpoint-reads-list-endpoints`.
- This is a **write** gather (db_update), not read — but same idiom: independent
  per-row work, each swallows own exc, order irrelevant. `:955` backfill is
  also a write-ish gather (mutates + persists). Safe.

## Decision (ADR-lite)

**Context**: `_demote_orphaned_public_rows` demotes orphaned public rows
serially in a for-loop (N serial DB writes on the public listing path when
accounts deleted). Each row's work is independent (distinct thread_id, own
try/except, order irrelevant). Module already has the gather idiom at `:955`
/`:1037` — this loop missed it.
**Decision**: partition `kept` (account-exists) vs `to_demote` (orphaned-
public), gather-demote `to_demote` via `_demote_one` wrapper (own try/except,
mirrors `:955` `_backfill`). `kept` filter logic unchanged.
**Consequences**: N serial DB writes → 1 concurrent wave on orphan-demotion.
Zero behavior change (same rows demoted, same `kept`, same per-row mutation +
warnings, same empty-existing-set demote-all). ~+4 LOC + 1 non-vacuous test.
Low risk — matches established module convention.
