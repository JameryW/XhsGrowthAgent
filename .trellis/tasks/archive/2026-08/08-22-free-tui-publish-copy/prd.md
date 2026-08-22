# Add free draft publish and copy commands to the Agent TUI

## Goal

Close the Free Creation publish loop inside the Agent TUI. The backend already exposes a full real-publish path (`POST /free/publish`, `backend/api/routes/free.py:351` — CDP resolution, XHS publish, post_id/post_url persistence, failure tracking via `last_publish`), but the TUI has no way to call it: publishing today requires a conversational LLM round-trip, and the manual-publish fallback forces users to hand-select the wrapped draft body out of the `/draft` card.

## Current gaps

- `processSlashCommand` (`frontend/src/views/AgentTUI.vue:1440`) has no `/publish` case; the help listings (`:2188-2210`) and quick actions (`:2632`) don't mention publishing.
- `/draft <id>` renders the body inside a CJK-wrapped box but offers no copy action; `copySelection` (`:628`) only copies xterm text selections, which multi-line wrapped boxes make error-prone.
- The draft detail already warns "do not publish on a degraded verdict" (`:1813`) and tracks `last_publish` failures, but nothing enforces or surfaces this at publish time.

## Requirements

### `/publish <draft_id> [confirm]`

- Free-mode-only guard (workflow mode gets the existing `freeWorkflowOpDisabled` line).
- Missing draft id → localized usage line.
- GET the draft first (same pattern as `handleDelete`): render a compact preview — title, evaluation verdict (score/decision, degraded, or unevaluated), published state.
- Guards:
  - Degraded evaluation → refuse and point at `/evaluate <id>`.
  - Already published with a non-mock post_id → refuse with the post_url and point at `/analytics <id>`.
  - Without the literal `confirm` argument → show the preview plus the exact confirm command; never POST on the first call.
- POST `/free/publish` with `{ draft_id, account_id }` only after confirm.
- Render the outcome: success (post_url + `/analytics` hint), mock_published (dry-run hint), failure (status + error, noting the cause is persisted on the draft).

### `/copy <draft_id>`

- Free-mode-only guard; missing id → usage line.
- GET the draft, compose `title + body + hashtags` as plain text, write to `navigator.clipboard`.
- Success line with the character count; clipboard failure → localized error pointing at manual selection from `/draft <id>`.

### Discoverability

- Add both commands to the free-mode help sections (agent-mode "free drafts" section and command-mode section).
- In the `/draft <id>` detail card: when the draft is not yet published, show a yellow follow-up hint with the exact `/publish <id> confirm` command; always show a dim hint for `/copy <id>`.

## Acceptance criteria

1. `/publish` without `confirm` never issues a POST; the confirm line names the exact re-run command.
2. Degraded-eval and already-published drafts are refused with localized reasons and next-step hints.
3. A confirmed publish POSTs to `/free/publish` and renders success/mock/failure outcomes from `publish_result`.
4. `/copy` puts title+body+hashtags on the clipboard and reports the size; clipboard failure degrades to a localized manual-selection hint.
5. Both commands appear in both free-mode help sections; the draft detail shows publish/copy follow-up hints.
6. Workflow (non-free) mode still rejects both commands via the existing guard.
7. New user-visible strings exist in both locale files (`i18n:check` passes).
8. Focused tests cover the confirm gate, degraded refusal, already-published refusal, success render, and copy path; `type-check`, `test:run`, and `build` pass.

## Out of scope

- Backend changes to `/free/publish` or the draft store.
- A GUI (non-TUI) drafts/publish surface — separate follow-up.
- Publishing images or multi-draft batch operations.
