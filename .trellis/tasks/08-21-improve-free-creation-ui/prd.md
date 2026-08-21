# Improve free creation mode and README showcase

## Goal

Make Free Creation a clear, account-scoped entry path from the Start Creating page into the Agent TUI, then document the improved path in the English-first README and the Simplified Chinese counterpart.

## Current gaps

- The Start Creating form only explains Free Creation; it does not collect a creation goal before navigation.
- The `account_id` selected on Start Creating is placed in the route but AgentTUI resolves free-mode commands from the global active account instead of the selected route account.
- The TUI can show a topic from the route, but it does not prefill that topic into the editable prompt, so the hand-off is easy to miss.
- README product-tour copy describes Free Creation as a terminal workspace but does not explain the guided hand-off or account-scoped draft/insight loop.

## Requirements

### Start Creating

- When Free Creation is selected, show a localized goal textarea or input with a clear explanation that the text is carried into the editable Agent prompt.
- Provide a small set of localized example prompt chips for common actions such as writing a note, finding topic ideas, and improving a draft. Chips fill the goal; they do not submit it.
- Show a compact four-step Free Creation path: describe, create, evaluate, publish.
- Preserve the existing account selector and pass the selected account and goal to `/tui?mode=free`.
- Keep trend and brief modes unchanged.

### AgentTUI

- Resolve the route `account_id` first when it matches an owned account; fall back to the existing active account behavior only when no valid route account is present.
- Use the resolved account for free-mode account context, draft commands, evaluation, analytics, suggestions, and edits.
- Prefill the route goal into the editable desktop or mobile prompt without sending it automatically. The user must still confirm by pressing Enter/Send.
- Keep the prompt editable, visible, and usable while the Agent socket is connecting or reconnecting.
- Preserve the existing free-mode command and reconnect behavior.

### README showcase

- Update `README.md` and `README.zh-CN.md` to describe the guided Free Creation entry, account-scoped hand-off, editable prompt, and draft/evaluation loop.
- Add or update a repository-local product image if local visual verification produces a clean, complete Free Creation panel. Do not claim a hosted screenshot was captured when the deployment is unavailable.
- Keep English as the default README and keep both language versions equivalent in product claims.

## Acceptance criteria

1. Free Creation exposes a goal input, example chips, and a four-step path when selected.
2. Example chips only prefill the goal; submitting the form navigates with `mode=free`, `account_id`, and the goal query when provided.
3. AgentTUI uses a valid route account before the global active account and keeps the selected account visible.
4. A route goal appears in the editable prompt on desktop and mobile and is not sent until the user confirms.
5. Trend and Brief mode behavior remains unchanged.
6. New user-visible strings exist in both locale files.
7. Focused tests, type-check, i18n check, and build pass.
8. README product-tour copy and local image references pass validation.

## Out of scope

- Changing the backend free-agent protocol or adding new agent tools.
- Auto-publishing from the new goal input.
- Replacing the terminal workspace with a separate rich-text editor.
