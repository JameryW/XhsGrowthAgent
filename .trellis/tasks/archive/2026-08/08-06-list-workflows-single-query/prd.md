# Collapse list_workflows 2 queries → 1 via COUNT window function

## Goal

`list_workflows` (backend/db/workflows.py:260) runs **2 sequential round-trip queries**: `SELECT COUNT(*)` + `SELECT * ... LIMIT`. Prod instrumentation (PR #483, XHS_LATENCY_LOG=1) shows `/list` cold 28ms = db 28ms — 2 round-trips on a 2-row indexed table means the round-trips dominate, not query cost. Collapse to 1 query via `COUNT(*) OVER()` window function → halve round-trips, correct total always.

## Evidence (prod, post-deploy 2026-08-06)

```
/list cold: total_ms 29.6 = db_ms 28.2 + serialize_ms 1.4
/list warm: total_ms 1.3-6.5, db dominates every call
```
db_ms >> serialize_ms. 2 queries = 2 round-trips. Window fn = 1.

## Requirements

- Replace 2-query COUNT+SELECT with single `SELECT *, COUNT(*) OVER() AS full_count FROM workflows WHERE ... ORDER BY ... LIMIT ... OFFSET ...`
- `total` derived from `full_count` of first row (0 if no rows)
- Preserve exact same return contract: `(list[WorkflowRow], int)`
- Preserve all filters (account_id, status, showcase_visibility), order_by, limit/offset
- No behavior change — same rows, same total, same ordering

## Acceptance Criteria

- [ ] list_workflows uses 1 query (window fn) not 2
- [ ] total correct for: 0 rows, rows < limit, rows == limit (pagination), with filters
- [ ] existing tests pass + new test covering total-with-pagination boundary
- [ ] ruff check + format --check + mypy backend green
- [ ] full pytest green

## Out of Scope

- Other db.* query helpers (only list_workflows this PR)
- /status aget_state path (separate concern)
- Index changes (already indexed on account_id/status/created_at)

## Technical Notes

- psycopg3 dict_row cursor, `get_pool().connection()` async context
- `_row_from_dict` builds WorkflowRow from dict — extra `full_count` key ignored by it (verify)
- `COUNT(*) OVER()` returns total matching rows (pre-LIMIT) per row — same as old COUNT query
- Postgres window fns well-supported, no new deps
