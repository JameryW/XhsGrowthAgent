# Free draft: persist + render last publish outcome (cross-stack)

## Problem

Free-mode publish failures leave **no durable trace** on the draft record.
`publish_draft` (`backend/api/routes/free.py`) only mutates the draft on success
(writes `published`/`post_id`/`post_url`/`updated_at`); on failure
(`status ∈ {failed, auth_expired}`) it writes nothing (comment lines 291-292:
"Failures ... do NOT mutate the draft").

Consequence: the agent-side publish render (#239) surfaces `error`/`error_type`/
`recovery` for the single tool call that failed, but once that turn passes the
failure is gone — there is no persisted state. A user (or the omp agent) opening
`/draft <id>` later, or scanning `/drafts`, sees no record that a publish was
attempted and why it failed. They have to re-attempt publish blind.

The TUI `/draft <id>` detail already shows `last_evaluation`, `published`,
`post_url` + analytics/mock hints (#216/#223) — but nothing about a failed
publish. The agent-side list render (#236) shows `[score decision]` +
`[published]` badges — no publish-failed badge.

## Fix

Persist a `last_publish` summary onto the draft record on **every** publish
attempt (success and failure), then render it on both surfaces.

### Backend — `backend/api/routes/free.py`

On every publish attempt, write `last_publish` to the draft before returning:

```python
draft["last_publish"] = {
    "status": pub_status,            # published / mock_published / failed / auth_expired / ...
    "error": publish_result.get("error"),         # None on success
    "error_type": publish_result.get("error_type"),  # None on success
    "at": _now_iso(),
}
```

- Success: `last_publish.status == "published"` (or `mock_published`); error
  fields None. The existing success mutations (`published`/`post_id`/`post_url`)
  stay as-is; `last_publish` is additive.
- Failure: `last_publish` written, but `published`/`post_id`/`post_url` stay
  unchanged (failures still do not flip the draft to published). `updated_at`
  refresh — a publish attempt IS a meaningful update to the record.

Persist for both success and failure (move the `store.aput` out of the
`if pub_status in _PUBLISH_SUCCESS_STATUSES` block, but keep the success-only
field mutations inside it).

### Frontend — `frontend/src/views/AgentTUI.vue` `/draft <id>`

In the status block of `handleDraft`, after the `published` line, render
`last_publish` when present:

- success (`status == "published"` or `mock_published`): no extra line — the
  existing `published` + `post_url`/hint lines already convey it. Avoids
  redundancy.
- failure (`status` not in the success set): render a red/dim line
  `Last Publish: <status> — <error>` (+ `error_type` parenthetical if present),
  with the `at` timestamp dim. Points the user at re-attempting publish after
  fixing the cause (the recovery hint already surfaced in the publish turn via
  #239; this is the durable reminder).

i18n: new keys `draftDetailLastPublishLabel` + `draftDetailLastPublishFailed`
(zh + en).

### Agent-side — `backend/services/omp_bridge.py` list render

In the `xhs_free_draft_list` render, add a `[publish failed]` badge when
`last_publish.status` is a failure (not `published`/`mock_published`), so the
agent can pick the next step from the list (failed→re-attempt publish after
fixing cause) without calling the detail. Mirrors the existing
`[score decision]`/`[published]` badge pattern (#236).

### Spec — `.trellis/spec/backend/free-creation.md`

- Draft Status Metadata: add `last_publish: {status, error?, error_type?, at}`.
- `xhs_free_publish` route behavior: note that every attempt writes
  `last_publish` (success + failure); failures do NOT flip `published`.
- Agent-side list render: add the `[publish failed]` badge note (aligns with
  #236's `[score decision]`/`[published]` badges).

## Scope

- `backend/api/routes/free.py` — write `last_publish` on every publish (~8 lines).
- `frontend/src/views/AgentTUI.vue` — `/draft <id>` `last_publish` failure line (~12 lines).
- `frontend/src/locales/{en,zh-CN}.json` — 2 keys × 2 langs.
- `backend/services/omp_bridge.py` — list render `[publish failed]` badge (~4 lines).
- `.trellis/spec/backend/free-creation.md` — metadata + route + list-render notes.
- `tests/unit/services/test_omp_bridge.py` — list fixture with a failed-publish
  draft asserting the `[publish failed]` badge.
- `tests/unit/api/test_free.py` (or wherever free routes are tested) — publish
  failure asserts `last_publish` persisted with status/error/error_type/at.

## Verification

- `ruff check .` + `ruff format --check .` clean.
- `mypy backend` clean.
- full `pytest`.
- `vue-tsc --noEmit` clean (vite build OOMs locally — CI covers build).

## Non-goals (YAGNI)

- Full publish history (list of all attempts) — only the latest. One field, not
  an append-only log.
- Retry-queue / auto-retry — just surface the cause; user/agent re-attempts.
- Clearing `last_publish` on a later successful publish — the success naturally
  overwrites `last_publish.status` to `published`; old failure is gone.
