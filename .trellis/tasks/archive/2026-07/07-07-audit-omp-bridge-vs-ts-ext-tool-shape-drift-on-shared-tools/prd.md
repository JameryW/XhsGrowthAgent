# Complete all omp fixes: optimization_draft echo + pre-existing mypy debt

## Problem

Drift audit (`research/drift-audit.md`) found 1 latent bug. Separately, 3
pre-existing mypy errors on `main` HEAD break the CI mypy gate. Both must be
fixed so "all tests pass" (user goal: 完成所有修复).

## Findings

### F1 — `optimization_draft` route doesn't echo submitted draft (backend)

`POST /optimization/draft/{thread_id}` (`backend/api/routes/optimization.py:29`
`submit_draft`) returns only `{thread_id, status, [next_phase]}`. Both the TS
tool (`optimization_draft.ts:32-43`) and Python bridge
(`omp_bridge.py:764-777`) read `draft_content` + `optimization_analysis` from
the response to render an inline title/body preview — but those fields are
absent, so the preview is permanently empty. No crash (both null-guard), but
the tool is degraded: agent + user never see what was just submitted.

The tool's designed value is the inline preview (matches `review_pending`
returning `copy_content`). Fix on the backend: echo back the submitted
`draft_content` + current `optimization_analysis` in the route response.

### F2 — 3 pre-existing mypy errors (CI gate red on main)

`mypy backend` reports 3 errors on `main` HEAD (confirmed via stash, not
introduced by prior omp task):
- `backend/services/xhs_publisher.py:412` — `ElementHandle | None` has no
  `set_input_files` (union-attr).
- `backend/services/xhs_engagement.py:81` — `add_cookies` expects
  `Sequence[SetCookieParam]`, got `list[dict[str, str]]` (arg-type).
- `backend/services/xhs_engagement.py:114` — `ElementHandle | None` has no
  `query_selector` (union-attr).

CI runs `mypy backend` unconditionally (per ci-github-actions-setup memory),
so main is currently red on the mypy job.

## Scope (MVP)

- **F1**: in `optimization.py:submit_draft`, echo `draft_content` (the
  `draft_data` already built) + `optimization_analysis` (from state values) in
  BOTH return branches (resumed + draft_submitted). No tool-side change needed
  (both already read these fields safely).
- **F2**: fix the 3 mypy errors with minimal guards:
  - `xhs_publisher.py:412`: null-check the `ElementHandle` before
    `set_input_files` (the handle came from `query_selector` which can return None).
  - `xhs_engagement.py:81`: type the cookies list as `Sequence[SetCookieParam]`
    or construct via typed dicts so `add_cookies` accepts it.
  - `xhs_engagement.py:114`: null-check the `ElementHandle` before
    `query_selector`.

Out of scope: system_health render divergence (cosmetic, intentional — both
pass full data blob as `details`).

## Acceptance

- `mypy backend` clean (0 errors).
- `pytest` full suite green (incl. any optimization/draft + publisher/engagement tests).
- `ruff check .` clean.
- `npm run typecheck` in `backend/omp/extensions/xhsagent-ext` still clean.
- Add/extend a test asserting `optimization_draft` route echoes `draft_content`.
