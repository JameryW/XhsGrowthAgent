# Browser Automation Safety

## XHS browser execution

All XHS browser operations must run in a headed browser. The legacy
`headless` parameters are retained only for caller compatibility and are
ignored by services; production code must pass or enforce `headless=False`.

When an account has a bound Chrome profile, interactive operations must attach
through its CDP endpoint. Engagement must not start a second browser, create a
cookie-only temporary context, inject stealth scripts, or serialize cookies.
If the account has no usable CDP endpoint, the operation fails closed.
CDP login reuses only the first existing `browser.contexts[0]`; when the bound
Chrome exposes no browser context, login fails with an actionable error and
must never call `browser.new_context()`. Creating a short-lived login page
inside that existing context remains allowed.

## Interaction safeguards

- Serialize operations per account.
- Apply a conservative cooldown between browser actions.
- Detect login shells and platform risk-control pages before and after
  navigation or submission.
- Stop on a risk-control signal; do not automatically retry the same action.
- The workflow graph does not perform automatic comment/DM actions. Any
  remaining comment/DM browser action is an explicit operator/tool action.
- Automatic post-login and scheduled creator-statistics syncs are list-only
  (`force_light=True`); per-note detail enrichment requires an explicit
  configuration or manual request.
- Keep creator-statistics collection on Creator Center. Public note pages are
  opt-in only and disabled for scheduled production syncs.

## Testing boundary

Tests should assert that CDP is used, `chromium.launch` is not used by
engagement, existing persistent contexts are not replaced, and risk pages
produce a blocked result without a follow-up navigation.
