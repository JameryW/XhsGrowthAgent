# Free agent: draft list render — status badges + count/truncated

## Problem

`omp_bridge._execute_xhs_host_tool` renders `xhs_free_draft_list` results
(~line 1398-1408) as `draft_id: title` per line — no published flag, no
evaluation score/decision, no count, no truncated hint. The agent listing its
drafts cannot see which are published, which are evaluated (and their verdict),
or how many there are / whether the 100-cap truncated older drafts.

The TUI `/drafts` (frontend) renders the full picture (#216/#226/#227):
published badge, eval badge `[score decision]`, count header, truncated dim
hint. The agent-side render — the path free-mode users hit by default — is the
minimal `id: title` form. Same TUI-vs-agent asymmetry class as #234/#235.

Without status, the agent can't decide next steps from the list: an
unevaluated draft → evaluate; a needs_revision draft → revise; a published
draft with real post_id → analytics. It would have to call `xhs_free_draft`
(draft detail) per draft to learn each one's state — N round-trips.

## Fix

Align the agent-side `xhs_free_draft_list` render with the TUI `/drafts` shape
(hardcoded English — omp renders aren't localized). Per draft, append:
- published marker when `published` is true: `[published]`
- eval badge when `last_evaluation` present + `decision`: `[<score> <decision>]`
  (score N/A if absent)

Plus a header line with `count` (filtered count from the route), and a
truncated note when `truncated` is true (the route's 100-cap heuristic —
older drafts beyond the cap aren't visible).

The route already returns `drafts[].published`, `drafts[].last_evaluation`
(`{overall_score, decision, revision_hints}`), `count`, `truncated` (see
`/drafts/{account_id}` signature, free-creation.md line 30). No backend
change — the data is already there; only the render omits it.

## Scope

- `backend/services/omp_bridge.py` — `xhs_free_draft_list` render (~8-12 lines).
- `.trellis/spec/backend/free-creation.md` — note the agent-side list render
  surfaces published/eval badges + count/truncated (align with TUI `/drafts`).
- `tests/unit/services/test_omp_bridge.py` — extend `test_free_draft_list` to
  assert the published marker + eval badge + count header on a multi-draft
  fixture with mixed states.

## Verification

- `ruff check .` + `ruff format --check .` clean.
- `mypy backend` clean.
- full `pytest`.
