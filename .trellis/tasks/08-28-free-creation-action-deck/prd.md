# Free Creation draft action deck and recovery UX

## Goal

Make the Free Creation draft list answer “what should I do next?” without
leaving the account-scoped History page. Surface publish failures as a first
class state, make the primary action reflect each draft's state, and provide a
clear path to start another draft.

## Problem

The backend already records `last_publish` and supports the `publish_failed`
status filter, but the History free-drafts panel requests all summaries and
does not expose that filter or failure state. A failed draft therefore looks
like an ordinary unpublished draft. The panel also gives every card the same
“Continue” action and offers no new-draft CTA when a user lands on an empty
account.

## Scope

### Backend contract

- Include a safe `last_publish` summary in `GET /api/free/drafts/{account_id}`:
  `status`, `error_type`, and `at` only. Keep the full error available through
  the existing detail route; do not enlarge the list payload with raw failure
  text.
- Keep existing account resolution, status filtering, ordering, and legacy
  defaults unchanged.
- Update the Free Creation contract and backend regression coverage.

### History free-drafts panel

- Add a `Publish failed` status option and evaluate it from the list summary.
- Show a compact failure badge with the failure type and a retry-in-workspace
  hint when `last_publish` contains a non-success status.
- Add a small account-scoped overview row for visible drafts: total shown,
  published, and needs attention. The row must not imply a true total when the
  server reports that the 100-item cap was reached.
- Change the primary card action label by state: start/continue writing for
  ordinary unpublished drafts, review/revise for evaluated drafts that are not
  approved, fix and retry for publish failures, and open draft for published
  drafts. All actions keep the existing `mode=free`, `account_id`, and
  `draft_id` deep link.
- Add a “New draft” action in the account-scoped header and empty state. It
  navigates to Free Creation with the selected account and never submits a
  prompt automatically.
- Preserve existing loading, retry, stale-account, deletion, dark-mode,
  mobile touch-target, and accessibility behavior.

### Localization and tests

- Add every new visible string to both `en.json` and `zh-CN.json`.
- Extend backend, API adapter, and panel tests for `last_publish`, the failed
  filter, contextual action labels, overview counts, and new-draft navigation.

## Out of scope

- No new publish endpoint or retry API; retry continues through the existing
  Free Creation TUI.
- No raw publish exception rendering in the list payload.
- No replacement of the TUI editor or changes to workflow-mode History.

## Acceptance criteria

1. A failed publish is distinguishable from an ordinary unpublished draft and
   can be found through a visible History filter.
2. The list API includes only the safe publish summary fields and legacy drafts
   still render with no failure badge.
3. Overview counts are derived from the loaded account-scoped rows and clearly
   remain a bounded view when `truncated` is true.
4. Each card's primary action communicates its next step while preserving the
   existing Free Creation deep-link contract.
5. New-draft actions navigate with the selected account and do not submit an
   agent message.
6. Both locales remain key-equivalent; focused tests, type-check, i18n check,
   and production build pass.
