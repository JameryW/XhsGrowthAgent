# Free agent: publish render — surface failure cause (error/error_type)

## Problem

`omp_bridge._execute_xhs_host_tool` renders `xhs_free_publish` results
(~line 1340+) as `Post ID / URL / Status` + (#235's) real/mock next-step cue.
On a **failed** publish (`status == "failed"` / `"auth_expired"`), the render
shows only `Status: failed` — it does NOT surface the `error`, `error_type`,
or `recovery` fields that `run_publish` returns.

`run_publish` (`backend/agents/publisher.py`) populates a rich failure payload:
- `error`: human message (e.g. "账号 X 已停用，无法发布")
- `error_type`: `account_inactive` / `auth_expired` / etc.
- `recovery`: `{message, action, action_label, hint}` — a recovery path
  (reconfigure / re-login / ...).

Free publish only ever calls `run_publish` (free.py `_build_publish_state` →
`run_publish`, not `PublisherAgent.execute`), and `run_publish` returns
`failed`/`auth_expired` on account-inactive / no-CDP / XHS-rejection — never
`mock_published` (that's `execute`'s dry-run branch, which free doesn't hit).

So when a free publish fails, the omp agent (free mode's default driver) sees
`Status: failed` with no cause and no recovery hint — it can't tell the user
*why* or *what to do*. It would have to inspect the structured `details`
(`publish_result`) itself, which a weaker agent may not do. The TUI publish
render isn't the comparison here (TUI free publish goes via the agent); the gap
is that the agent-facing text render drops the failure context that the route
already provides.

## Fix

In the `xhs_free_publish` render, when `status` indicates failure (not
`published` / `mock_published`), append the `error` (and `error_type` if
present) + the `recovery.message` / `recovery.hint` if present. Hardcoded
English labels (the rest of the render is hardcoded English).

- `error` → `  Error: <error>`
- `error_type` → `  Error Type: <error_type>` (only if present)
- `recovery.message` → `  Recovery: <message>` (only if present)
- `recovery.hint` → `  Hint: <hint>` (only if present)

Keep #235's real/mock cues as-is (they already gate on `published` /
`mock_published`; failures fall through to the new error block).

No backend route change (`run_publish` already returns these fields). No
frontend change. No i18n (omp renders are hardcoded English).

## Scope

- `backend/services/omp_bridge.py` — publish render error block (~4-6 lines).
- `.trellis/spec/backend/free-creation.md` — note the agent-side publish render
  surfaces failure cause + recovery (align with the #235 cue pattern).
- `tests/unit/services/test_omp_bridge.py` — add a failed-publish case asserting
  `Error` / `Error Type` / `Recovery` lines render.

## Verification

- `ruff check .` + `ruff format --check .` clean.
- `mypy backend` clean.
- full `pytest`.
