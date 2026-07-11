# free draft: /edit <id> <field> <value> TUI command

## Goal

Free mode can create/list/view/delete/publish/evaluate drafts, and the agent
can `xhs_free_draft_update` (PATCH) — but the TUI has **no edit command**. A
user wanting to fix a draft's title or niche must either re-create it or ask
the agent conversationally. The `PATCH /free/draft/{id}` route exists and
accepts all-optional fields; it just has no TUI entry point.

Add `/edit <id> <field> <value>` — single-line scalar-field edit. Covers the
common quick fixes (title, niche, content_angle, target_audience) without a
terminal text editor. `body` is multi-line free text — out of scope (agent
handles it via `xhs_free_draft_update`); `hashtags`/`image_paths` are lists —
out of scope (terminal single-line can't express them cleanly).

## What I already know

- `backend/api/routes/free.py:341` `PATCH /draft/{draft_id}` — `FreeDraftUpdate`
  (all fields optional incl. title/body/hashtags/image_paths/niche/
  content_angle/target_audience). Merges onto existing, preserves draft_id,
  refreshes updated_at. **No backend change needed** — route already supports
  partial scalar updates.
- `FreeDraftUpdate` (free.py:62): `title|body|hashtags|image_paths|niche|
  content_angle|target_audience`, all `| None = None`.
- TUI `handleDraft`/`handleDelete` pattern: free-only guard, parse arg, GET
  draft (delete does GET-first for confirmation), call route, render result.
- `SLASH_COMMANDS` (AgentTUI.vue:203) — add `/edit` for tab-completion.
- Spec free-creation.md: Scope/Trigger lists TUI commands; Isolation section
  documents each free-mode command's behavior; Tests Required lists test_free_routes.
- omp host tool `xhs_free_draft_update` already exists for the agent path —
  this TUI command is the human path, parallel.

## Requirements

- TUI `/edit <id> <field> <value...>` (free mode): parse `<id>` + `<field>`
  + the rest as `<value>` (value may contain spaces — title/niche are free
  text). Allowed fields: `title`, `niche`, `content_angle`, `target_audience`.
  Unknown field → red error listing the allowed set. Missing args → usage.
- PATCH `/free/draft/{id}?account_id=` with body `{<field>: <value>}`. On
  success render "updated: <field> = <value>" (green) + the new updated_at.
  On 400 (draft not found / store none) → red error message.
- `SLASH_COMMANDS` + tab-completion: add `/edit`.
- showHelp free-mode section: add `/edit <id> <field> <value>` line.
- First-entry banner command list (PR #224): add `/edit` if #224 merged;
  if not, document dependency.
- Non-free mode → `freeWorkflowOpDisabled`.
- i18n: `editUsage`, `editUnknownField`, `editUpdated`, `editFailed` (en+zh-CN).

## Acceptance Criteria

- [ ] `/edit <id> title 新标题` PATCHes + renders success with new value +
      updated_at.
- [ ] Unknown field → red error naming allowed fields.
- [ ] Missing id/field/value → usage line.
- [ ] Draft not found → red error (route 400 surfaced).
- [ ] Non-free → freeWorkflowOpDisabled.
- [ ] `/edit` in SLASH_COMMANDS + showHelp.
- [ ] `vue-tsc --noEmit` clean; ruff+mypy clean (frontend-only, gate holds).
- [ ] Spec: add `/edit <id> <field> <value>` to Scope/Trigger command list +
      Isolation behavior + showHelp/first-entry mention.

## Out of Scope

- `body` editing (multi-line — agent handles via `xhs_free_draft_update`).
- `hashtags`/`image_paths` (list fields — terminal single-line awkward).
- Inline multi-field edit (`/edit <id> title X niche Y` — keep one field/cmd;
  YAGNI, run twice).
- Backend changes (PATCH route already sufficient).

## Technical Notes

- `handleEdit(raw: string)` in AgentTUI — parse: `parts = text.split(/\s+/)`,
  `id=parts[1]`, `field=parts[2]`, `value=parts.slice(3).join(' ')`.
- Allowed-fields set: `['title','niche','content_angle','target_audience']`.
- PATCH body: `{ [field]: value }` — single field.
- Reuse `client.patch(`/free/draft/${id}?account_id=${accountId}`, { [field]: value })`.
- showHelp free-mode block: add `/edit <id> <field> <v>` line near /delete.
- Spec Isolation section: add a `/edit <id> <field> <value>` bullet (free-only
  guard, unknown-field 400-ish error, allowed-field set, reuses PATCH route).
- Branch from main. No #223/#224 dependency (PATCH route on main since #211;
  first-entry banner list only if #224 merged — add /edit to it then).
- Frontend gate = vue-tsc (vite build OOMs locally; build left to CI).
