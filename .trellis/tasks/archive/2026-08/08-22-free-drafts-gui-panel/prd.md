# Free draft History tab

## Problem

Free Creation already persists drafts and exposes them through the Agent TUI, but the authenticated GUI History page only lists workflow runs. Users who create content in Free Creation cannot discover, reopen, filter, or remove those drafts from the main product navigation.

## Goal

Add a bilingual Free drafts tab to the existing History page. The tab must use the selected account scope, expose useful draft state at a glance, and provide a direct path back into the existing Free Creation workspace for continued editing and publishing.

## Scope

### In scope

- Add a typed frontend adapter for the existing `/free/drafts/{account_id}` and `/free/draft/{draft_id}`/delete endpoints.
- Add a `Workflows` / `Free drafts` tab switcher to History. Keep Workflows as the default so existing `/history` links and behavior remain unchanged. Persist the selected tab in `?tab=free-drafts`.
- Add a reusable Free Draft History panel with:
  - account-scoped loading, retry, empty and refresh states;
  - search by title and filters for all, unpublished, published, evaluated and unevaluated drafts;
  - cards showing title, excerpt, hashtags, created/updated time, publish state, and the latest evaluation score/decision when available;
  - a Continue action that opens AgentTUI in Free Creation mode for the selected account and draft;
  - a guarded Delete action using the existing confirmation modal.
- Extend AgentTUI's Free Creation route handling so a `draft_id` query opens the requested draft detail instead of starting a new draft context.
- Add English and Simplified Chinese locale keys for every new visible string.
- Add focused component/API/route tests for account scoping, tab deep links, filters, empty/error/retry states, stale account responses, delete confirmation, and draft deep links.

### Out of scope

- Changing the backend Free draft data model or endpoint behavior.
- Replacing the existing TUI editor or duplicating its full draft editing form inside History.
- Changing workflow history pagination, account selection, or public showcase behavior.

## UX and technical decisions

- History remains the account-scope owner. The Free Draft panel receives the resolved viewed account ID and never falls back to the backend's `default` namespace.
- The panel owns its request generation and abort handling so a late response from account A cannot overwrite account B's rows.
- API failures are rendered locally with a retry action; the API client receives `suppressToast: true` for these expected page-level states.
- Continue links include `mode=free`, `account_id`, and `draft_id`. AgentTUI loads the draft after its normal free-mode initialization, preserving the existing welcome experience for routes without `draft_id`.
- Use static Tailwind classes with explicit dark-mode variants, existing design-system components, and i18n keys in both supported locale files.

## Acceptance criteria

1. `/history` still opens the workflow tab and existing workflow tests continue to pass.
2. `/history?tab=free-drafts` opens the Free drafts tab and browser back/forward restores the tab.
3. The selected History account is passed to every draft list/delete request; no request is made when no account is selected.
4. Free drafts can be searched and filtered without losing the account scope, and the UI clearly distinguishes unpublished, published, evaluated, unevaluated, and unavailable evaluation states.
5. Loading, empty, API error, retry, account switch, and delete-confirmation states are accessible and bilingual.
6. Continue opens the selected draft in Free Creation, and AgentTUI displays the draft detail for the supplied `draft_id`.
7. Frontend i18n parity, type-check, focused tests, and production build pass.
