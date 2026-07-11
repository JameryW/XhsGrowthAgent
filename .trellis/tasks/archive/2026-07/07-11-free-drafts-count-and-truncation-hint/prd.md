# free drafts: list shows count + truncation hint

## Goal

`/drafts` lists free drafts but shows no count in the header, and the backend
`list_drafts` caps at `store.asearch(..., limit=100)` — if an account has
>100 drafts, the oldest silently vanish and the TUI reads as "all covered".
Per the ponytail no-silent-caps convention, surface the count and warn when
the cap is hit. Two small gaps:

1. No header count — user sees a list, doesn't know how many drafts exist.
2. Silent truncation at 100 — a heavy creator loses visibility of old drafts
   with no indication more exist.

## What I already know

- `backend/api/routes/free.py:list_drafts` (~300): `store.asearch(ns, query="",
  limit=100)` → builds draft list, sorts by updated_at desc. Returns
  `{account_id, drafts}`. No count field, no truncation flag.
- `handleDrafts` (AgentTUI.vue ~1030): renders `draftsListTitle` header then
  one line per draft. No count shown. No awareness of a cap.
- Spec `free-creation.md` "list_drafts surface + sort" section documents the
  response fields + sort, but no count/truncation contract.
- `asearch` `limit` is page size; on `BaseStore` there's no portable total-
  count API. Detection: if returned items == limit, likely more exist
  (heuristic — exact count needs a second query, YAGNI).
- omp host tool `xhs_free_draft_list` returns the same `{account_id, drafts}`;
  the agent text-result already includes the list. Count helps the agent too.

## Requirements

- `list_drafts`: return a `count` field (len of drafts returned) +
  `truncated: true` when `len(items) >= limit` (heuristic: likely more). Log
  a warning when truncated (so it's not silent server-side either).
- `handleDrafts`: render the count in the header (e.g. "Drafts (N):" or
  `draftsListTitle` with count). When `truncated`, append a dim line:
  "showing first 100 — older drafts hidden".
- i18n: `draftsCount` (header with count) + `draftsTruncated` (warning line)
  (en + zh-CN).
- Spec: add `count` + `truncated` to the list_drafts response contract +
  "list_drafts surface + sort" section note.

## Acceptance Criteria

- [ ] `GET /free/drafts/{account_id}` response includes `count` + `truncated`.
- [ ] `truncated` is true only when returned items hit the limit (heuristic).
- [ ] TUI header shows the count; truncated → dim warning line.
- [ ] Existing list tests still pass + new test for count/truncated (seed
      >limit drafts or assert fields present).
- [ ] `pytest` green; `ruff`+`mypy` clean; `vue-tsc` clean; CI green.
- [ ] Spec: count + truncated fields documented.

## Out of Scope

- True total count (second asearch/scan — YAGNI; heuristic suffices).
- Pagination (`/drafts?offset=` — terminal list isn't paged; sort newest-first
  means the visible 100 are the most relevant anyway).
- Filter by status (`/drafts published` — separate PR if needed).
- Raising the limit (100 is fine for the common case; the hint covers the edge).

## Technical Notes

- `list_drafts` (free.py): after building `drafts`, add to response:
  `count=len(drafts)`, `truncated=(len(items) >= 100)`. `items` is the asearch
  result before filtering non-dict values — use `len(items)` for the heuristic
  (a non-dict item still counts toward the page). Log warning if truncated.
- `handleDrafts`: header already uses `draftsListTitle` with `{accountId}`.
  Add count: render `draftsListTitle` then `(N)` — or new key `draftsCount`
  with `{count}`. Truncated → `writeLineColored(t('tui.draftsTruncated'), DIM)`.
- Tests: `test_free_routes.py` TestListDrafts — assert `count` field +
  `truncated` field present; seed 101 drafts → assert `truncated` true.
- Spec "list_drafts surface + sort" section: add `count` + `truncated` to the
  response field list + a note on the 100-cap heuristic.
- Frontend gate = vue-tsc; backend gate = pytest + ruff + mypy.
