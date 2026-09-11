# Evaluate: free draft list ordering determinism

Status: **evaluation only**. No code change is authorized by this document; it
exists to pick between two fixes, one of which is far more expensive than it
looks.

## Observed

`tests/unit/api/test_free_routes.py::TestListDrafts::test_list_sorted_newest_first_by_updated_at`
fails intermittently on a coarse-resolution Windows host: twice in roughly five
full `pytest tests` runs, and never when run in isolation. It passed 5/5 in
isolation while failing 2/~5 in the full suite, which is the signature of a
clock-tie dependency rather than a logic error.

Mechanism, read from the code rather than inferred:

- `backend/api/routes/free.py:580` — `drafts.sort(key=lambda d: d.get("updated_at") or "", reverse=True)`
  is a single-key sort with no tie-break. Python's sort is stable, so records
  with equal `updated_at` keep whatever order `alist` yielded.
- The test seeds two drafts with back-to-back `POST /api/free/draft` calls and
  then asserts `drafts[0]["title"] == "new"`. Its own comment concedes the
  assumption: *"second is newer (created after, so updated_at >= first)"* — the
  assertion needs `>`, the code only guarantees `>=`.
- `updated_at` comes from `_now_iso()`/`now` per write, and on Windows the clock
  advances in ~15.6 ms steps, so two sequential writes inside one request burst
  share a timestamp.

This is the third instance of one defect family in this codebase: the OpenAPI
contract fixture codec, the quality-run `max()`/`ORDER BY` tie, and here. The
first two were fixed; the difference is what each one *has to work with*.

## Why this is not a replay of the quality-run fix

`quality_evaluation_runs` lives in a Postgres table, so a deterministic order was
obtainable directly from the database: `CREATE SEQUENCE` plus an appended
`seq` column, one `ORDER BY ... DESC, seq DESC` per query, and a memory fallback
that mirrors the same key. That fix is now enforced by CI on a real server.

Free drafts do not live in a table. They are LangGraph `BaseStore` records keyed
by namespace, and `BaseStore` exposes no atomic counter, no `RETURNING`, and no
ordering guarantee for a tie. So "just add a seq column" has no equivalent, and
the candidate fixes are genuinely different in cost.

## Options

### A. Make the test assert what the API actually guarantees

Give the two seeded drafts explicit, different `updated_at` values, so the test
checks the documented behavior — newest `updated_at` first — instead of relying
on the host clock to separate two writes.

- Cost: one test function. Zero production risk.
- Honest limitation it leaves in place: for drafts saved within one clock tick,
  the API's returned order among them is not specified. Anyone who needs stable
  order across pages or sessions must not depend on this list alone.

### B. Give drafts a real, durable insertion order

Options inside B, in escalating cost:

1. **Process-monotonic timestamps**: ensure each issued `updated_at` is strictly
   greater than the previous one. Small change, but it fabricates time and
   silently breaks with more than one worker — the same account edited by two
   processes can still tie or invert. It also makes `updated_at` unsuitable for
   displaying "when did I edit this".
2. **A per-draft sequence field** written on creation (e.g. `revision` or
   `created_seq`). Requires a source of monotonic values that survives restarts
   and multiple workers; `BaseStore` offers no atomic increment, so it means
   either a table-backed counter (new persistence for a feature that deliberately
   has none) or `get`-then-`put` (races, which is exactly the failure mode being
   fixed).
3. **Secondary sort key on `draft_id`**: deterministic and free, but `draft_id`
   is a random UUID, so "latest" would mean "lexicographically largest id among
   ties" — stable, meaningless, and a worse contract than the one it replaces.

- Real cost of a correct B: a new durable coordination point for the free-draft
  store, or accepting a scheme that is only correct on a single process.

## What actually consumes the order

Searched, with no consumer found: no `findIndex`/position/prev-next derivation in
`frontend/src`, and none in `backend/omp/extensions/xhsagent-ext/src`. The API
returns the sorted list; the visible consequence today is list display order in
the drafts panel.

**Open question that decides this**: the archived journal entries describe a
continuous draft-review queue with position and previous/next navigation. If that
surface derives its index from this list's order, an unspecified tie becomes a
jumping queue position, which is a user-visible defect and moves the call from A
to B. Confirm where that navigation reads its ordering before choosing B, and
note it may live outside this repository.

## Recommendation

**A now, B only if the review-queue question resolves to "order is load-bearing".**

Reasoning: today the only demonstrable harm is a test that asserts an
unstated guarantee, and A removes the flake honestly by asserting the documented
behavior. B's cheap variants (1 and 3) replace an ambiguity with a false
guarantee, which is worse than the bug; B's correct form needs durable
coordination the free-draft store deliberately lacks. Deciding B on the basis of
one UI list would be over-building — but if the review queue depends on this
order, the requirement changes and the right answer is a real sequence, not a
timestamp trick.

If B is chosen, the first step is a separate design note for the counter's
durability and multi-worker behavior, not an implementation.

## Decision needed

1. Does the draft-review queue (or any other surface) index into this list's
   order? If yes → B with a designed sequence. If no → A.
2. Should the produced ordering guarantee be written into
   `.trellis/spec/backend/` as a rule — "any list ordered by a caller-supplied
   timestamp must define a tie-break or document that ties are unordered" — so
   the fourth instance of this family is prevented rather than rediscovered?

## Out of scope here

Changing `quality_evaluation_runs` behavior (shipped in #574), and general
free-draft pagination design.

## Decided: A

Option A taken. `test_list_sorted_newest_first_by_updated_at` now seeds two
drafts with explicit, distinct `updated_at` values and asserts the property the
route guarantees (strict descending order), instead of asking the host clock to
separate two sequential POSTs. Ties are asserted nothing, because the API
promises nothing about them; the test says so in its docstring so a future edit
cannot quietly turn that back into an accidental guarantee.

Evidence after the change: three consecutive full runs all `2315 passed,
3 skipped` (the skips are the opt-in Postgres suites), against roughly two
failures in five runs before it. Negative control: removing the route's
`drafts.sort(...)` makes the test fail, and restoring it makes the test pass, so
the rewrite still guards ordering rather than being a tautology over fixed data.

No production semantics changed.

## Still open

- The load-bearing question from this document was never answered: does the
  draft-review queue index into this list's order? If it does, ties are a
  user-visible jumping position and option B (a real durable sequence, not a
  timestamp trick) belongs on the roadmap. Nothing in this repository was found
  to depend on it, which is why A was safe — absence of a found consumer is not
  proof none exists.
- ~~Whether to record the general rule in `.trellis/spec/backend/`~~ **Done**:
  `quality-guidelines.md` §11.4 now states the three cases (load-bearing → real
  tie-break used identically in both branches; not guaranteed → document it and
  assert nothing about ties; tie-break unavailable → record the ambiguity rather
  than invent one), plus review-checklist and forbidden-pattern entries covering
  clock-inferred concurrency assertions and re-sorting already-ordered rows.
