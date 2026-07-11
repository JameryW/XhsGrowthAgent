# free draft detail: show post_url + analytics hint

## Goal

`/draft <id>` (AgentTUI free mode) renders `Published: yes` when a draft has
`published=True`, but stops there. The publish write-back (PR #223) persists
`post_id` + `post_url` on the draft — the detail view ignores them. A user
publishes, runs `/draft <id>`, sees "Published: yes", and has no link to the
live post or a hint that `/analytics <id>` exists. Surface the post_url (so
the user can open the live note) and an action hint pointing at `/analytics`.

## What I already know

- `backend/api/routes/free.py:publish_draft` (252-266): on success persists
  `draft["post_id"]` + `draft["post_url"]` (PR #223). `GET /free/draft/{draft_id}`
  returns the full record via `_load_draft` — `post_id`/`post_url` already in
  the response, frontend just doesn't render them.
- `frontend/src/views/AgentTUI.vue:1086-1100` `FreeDraftRecord` interface —
  missing `post_id` + `post_url` fields (type hole; currently untyped).
- `handleDraft` (1102-1173): status block renders `last_evaluation`,
  `published`, `created_at`, `updated_at`. No `post_url` line, no action hint.
- Spec `.trellis/spec/backend/free-creation.md` "TUI display" section (222-233)
  covers `/drafts` list badges only; `/draft <id>` detail layout unspecified.
- `/analytics <id>` command already shipped (#223) — this is the follow-on
  discoverability fix.

## Requirements

- `FreeDraftRecord` interface: add `post_id?: string` + `post_url?: string`.
- `handleDraft` status block: when `draft.published` and `post_url` present,
  render the post_url line (clickable-looking cyan). When `post_id` present
  (real, non-mock), append an action hint: "run `/analytics <id>` for
  engagement". Mock-published (`post_id` starts with `mock_`) → show
  "mock-published (dry-run) — re-publish for a real post" instead of the
  analytics hint.
- i18n keys both locales: `draftDetailPostUrlLabel`, `draftDetailAnalyticsHint`,
  `draftDetailMockPublishedHint`.
- No backend change — route already returns the fields.

## Acceptance Criteria

- [ ] Published draft with real post_id+post_url: `/draft <id>` shows post_url
      line + analytics hint.
- [ ] Mock-published draft: shows mock hint, no analytics hint.
- [ ] Unpublished draft: unchanged (no post lines).
- [ ] `vue-tsc --noEmit` clean; `ruff`+`mypy` clean (frontend-only change but
      gate holds); CI green.
- [ ] Spec: add `/draft <id>` detail post_url/mock-hint rendering note to the
      "TUI display" section.

## Out of Scope

- Editing post_url (read-only display).
- Auto-opening the URL (TUI is a terminal — just print it).
- Re-fetching analytics inline (separate `/analytics` command, already shipped).

## Technical Notes

- `handleDraft` status block, after the `published` line (1157-1161):
  - `if (draft.post_url) writeLine(post_url)` — cyan value.
  - `if (draft.post_id && !draft.post_id.startsWith('mock_'))` → analytics hint;
    else if mock → mock hint.
- `FreeDraftRecord` interface: add two optional string fields.
- Spec "TUI display" section: add a `/draft <id>` detail paragraph covering
  post_url + the two hints, parallel to the `/drafts` badge list.
- No backend/tests needed — pure frontend render + spec sync. Frontend gate =
  `vue-tsc` (vite build OOMs on low-RAM box per memory; build left to CI).
