# Free agent: publish mock vs real next-step hint

## Problem

`omp_bridge._execute_xhs_host_tool` renders `xhs_free_publish` results as
plain text (~line 1354-1369): `Post ID`, `URL`, `Status`. On a dry-run
(`status == "mock_published"`, `post_id == "mock_<session>"`), the render
shows `Status: mock_published` but gives the agent **no cue** that:
- this is a simulated publish (no real XHS post was created),
- the `mock_*` post_id is synthetic, so `xhs_free_analytics` will 400.

The agent may see "published" and call `xhs_free_analytics` → 400 ("no real
post_id"). The TUI side already distinguishes this (#223: `post_id.startsWith('mock_')`
→ mock hint; real post_id → analytics hint), but the agent-side render — the
path free-mode users hit by default — does not.

Secondary, symmetric gap: on a **real** successful publish (`status == "published"`,
real post_id), the render gives no `next:` cue → `xhs_free_analytics` (the
post-publish feedback loop). #234 just added a `next:` cue pattern to the
evaluate render; publish is the natural next application — and it resolves
both gaps in one branch: real publish → analytics cue; mock publish → mock
cue (no analytics).

## Fix

In the `xhs_free_publish` render, after the existing lines, add a conditional
next-step cue (hardcoded English — the rest of the render is hardcoded):

- If `status == "published"` AND `post_id` is non-empty and does NOT start
  with `mock_`: append `next: call xhs_free_analytics(<draft_id>) to check
  post-publish engagement.`
- Else if `status == "mock_published"` (or `post_id` starts with `mock_`):
  append `note: dry-run mock publish (no real XHS post) — analytics not
  available; re-run xhs_free_publish without dry-run for a real post.`
- Else (failed / unknown status): no cue (the route already surfaces failure
  via the response/error path).

Mirror the `_PUBLISH_SUCCESS_STATUSES` split already used by the route
(`backend/api/routes/free.py`): `published` is real, `mock_published` is dry-run.

No backend route change. No frontend change (TUI #223 already handles it).
No i18n (omp renders are hardcoded English).

## Scope

- `backend/services/omp_bridge.py` — publish render cue (~3-6 lines).
- `.trellis/spec/backend/free-creation.md` — note the agent-side publish
  render distinguishes real/mock (align with the TUI #223 note + the #234
  evaluate cue pattern).
- `tests/unit/services/test_omp_bridge.py` — extend `test_free_publish` to
  assert the real-publish analytics cue; add a mock-publish case asserting
  the mock cue (and that analytics is not suggested).

## Verification

- `ruff check .` + `ruff format --check .` clean.
- `mypy backend` clean.
- full `pytest` (per pre-push memory — shared code path).
