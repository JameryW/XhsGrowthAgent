# Deterministic ordering and timing-based test reliability

Two tests pass on Linux CI and fail on a coarse-resolution Windows clock. They
look like one problem ("timestamp flakiness") and are two different defects: one
is test instrumentation using strict timestamp inequality as proof of
concurrency, the other is a real product ambiguity where "latest" has no
deterministic definition and the two storage backends can disagree.

Neither is caused by the encoding or `fcntl` work in #572 and the
Windows-portability change; both were masked behind those failures and became
visible once the rest of the suite could run.

## Failure 1 — concurrency proven by timestamp comparison

`tests/unit/api/test_analytics_creator_analysis.py::test_get_creator_analysis_gathers_reads_concurrently`

```
AssertionError: not concurrent: list=[161430.14,161430.14] account_start=161430.14
assert list_start < account_start < list_finish
```

The mocks record `asyncio.get_event_loop().time()` at start and finish. That is
already a monotonic clock, so the bug is not wall-clock drift: on Windows the
event-loop clock advances in ticks of roughly 15.6 ms, and the mocked fetches
contain only `await`-yield points with no real work, so all three samples land
in one tick and collapse to the same value. Strict `<` then cannot hold even
though the code genuinely ran concurrently.

The assertion is testing the wrong observable. Overlap is a property of
*ordering of awaits*, and the test measures it with a clock that is too coarse
to see it.

### Direction

Make the mocks publish ordering explicitly instead of inferring it from time —
the standard deterministic shape: each fetch awaits an event that the other
raises once it has started, so serial execution deadlocks/times out and
concurrent execution proceeds. Concretely: `list_note_stats` awaits a
`asyncio.Event` set by `get_account_stats` and vice versa, with a short
`asyncio.wait_for` so a serial regression fails fast with a clear message rather
than hanging. This passes on every platform with any clock granularity, still
fails if someone replaces `gather` with sequential awaits, and asserts the thing
we actually care about: neither fetch can complete before the other has started.

Keep the invocation-count assertions (`len(timeline["list"]) == 2`) as the
"both ran" evidence; they are clock-independent already.

## Failure 2 — "latest" is undefined for same-timestamp rows

`tests/unit/api/test_quality_consistency_backend.py::test_quality_run_cache_is_idempotent_and_force_keeps_versions`

```
AssertionError: assert 'eval_b837871f...' == 'eval_e7de1c9c...'
# expected the second-created run, got the first
```

`quality_evaluation_runs.created_at` is a TEXT ISO timestamp, and two
`new_run()` + `create_run()` calls in one test tick produce identical strings.
The two read paths then diverge *by construction*:

- memory adapter: `max(candidates, key=lambda run: run.created_at)` returns the
  first maximal element, i.e. insertion order decides;
- Postgres: `ORDER BY created_at DESC LIMIT 1` has no tie-break, so the planner
  picks arbitrarily.

This is a product defect, not a test defect. Two rows sharing a timestamp make
`get_latest_for_subject` return whichever row the backend happens to like, and
the same application state can answer differently on the memory fallback than on
Postgres — which also breaks the adapter-parity guarantee the rest of the
codebase maintains. The coarse Windows clock only makes it reproducible.

### Direction

Give "latest" a definition that survives equal timestamps and is identical in
both backends. The ordering key must be monotonic per insertion, so the natural
form is a server-assigned sequence:

- add a `seq BIGSERIAL` (or equivalent) column to `quality_evaluation_runs`,
  included in the existing subject index;
- order by `created_at DESC, seq DESC` in Postgres, and carry the same `seq`
  into the in-memory rows so the memory comparator sorts
  `(created_at, seq)` descending rather than relying on `max()` first-wins;
- `new_run()` stays sequence-free (sequence is assigned at insert), and
  `create_run()` returns the stored row so callers see the assigned order.

A cheaper alternative is `ORDER BY created_at DESC, evaluation_id DESC` plus the
same tie-break in memory: fully deterministic and cross-backend consistent, but
it makes "latest" mean "lexicographically largest random id among equal
timestamps", which is stable yet meaningless. Recommended only if a schema
change is judged too invasive; if taken, the test must be reworded to assert
"deterministic and backend-consistent" rather than "most recently created".

Either way, add a regression test that pins the real requirement without relying
on clock resolution: insert two rows forced to the same `created_at`, then
assert the one created second is returned, on both the memory and Postgres
branches (the Creator Agent parity harness pattern from
`tests/integration/test_creator_agent_backend_parity.py` is the model).

## Related, deliberately out of scope

`get_cached` and `get_latest_for_subject` are not the only `created_at`-ordered
reads in this module. If the sequence approach is taken, audit the sibling
adapters that sort by `created_at` alone and either adopt the same tie-break or
record why they do not need it. Do not bundle that sweep into the first change.

## Acceptance criteria

- Both named tests pass on a coarse-grained clock without sleeps, `xfail`, or
  platform skips, and still fail when the behavior they guard is reverted
  (concurrency test fails under sequential `await`; ordering test fails when the
  tie-break is removed).
- The concurrency assertion no longer reads a clock to infer interleaving.
- `get_latest_for_subject` is deterministic for equal `created_at` values and
  returns the later-created row on both the memory and Postgres branches.
- Any schema addition is created idempotently by `ensure_tables` and does not
  rewrite existing rows' meaning.
- Full `pytest tests` result is compared against the recorded baseline, and the
  remaining failure count decreases by exactly two with no new failures.
- Ruff, Mypy and the OpenAPI/contract checks stay green.

## Executed findings

The diagnosis above held, with one addition found while verifying against a real
server: the Postgres trend branch re-sorted its projected rows by `created_at`
alone *after* a query that had already applied the `seq` tie-break, so two
same-tick runs came back ascending from the memory fallback and descending from
Postgres. That divergence was invisible to memory-only tests and is exactly why
`tests/integration/test_quality_evaluation_backend_parity.py` exists: with the
old trend logic restored, only the cross-backend test fails.

Also corrected: `fetch_trend_points` must order the durable runs, not the
projected trend rows, because `seq` exists on the run only and the trend row
flattens `completed_at or created_at` into `created_at`.

Verified against PostgreSQL 16.2: `CREATE SEQUENCE` + `ALTER TABLE ... ADD COLUMN
IF NOT EXISTS seq` upgrade an existing table, legacy rows keep `seq = 0`, and
`nextval` assigns distinct increasing values on consecutive inserts.
