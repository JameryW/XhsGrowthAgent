# Close browser fallbacks and gate automatic engagement

## Context

Engagement now uses persistent CDP, but the publisher still has a legacy
no-CDP fallback that launches a separate browser and injects Cookie/stealth
state. The workflow agent can also open public note pages repeatedly while
automatically replying to comments and DMs. Both paths expand the automated
main-site surface.

## Requirements

1. Make `XHSPublisher` fail closed when no CDP endpoint is available. The
   publisher must not launch a second browser, create a temporary context,
   inject cookies, or apply stealth scripts. Existing CDP publishing behavior
   remains unchanged.
2. Add `XHS_AUTO_ENGAGEMENT`, defaulting to `false`, and gate the workflow
   agent's automatic comment/DM loop behind it. Explicit tool calls remain
   available and continue to use the persistent-CDP safeguards.
3. Expose the setting in `.env.example` and pass the safe default from the
   deployment script. Return a normal completed workflow when automatic
   engagement is disabled, with a clear log message.
4. Add focused tests for publisher fail-closed behavior and the disabled
   automatic-engagement branch.

## Acceptance criteria

- No production publisher path calls `chromium.launch`, `new_context`,
  `add_cookies`, or `playwright-stealth`.
- An `XHSPublisher` without CDP returns a clear configuration error before any
  browser is started.
- The engagement agent performs no comment/DM reads or sends when the setting
  is false, and behaves as before when explicitly enabled.
- Full tests, Ruff, formatting, and mypy checks pass.
