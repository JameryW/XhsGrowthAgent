# QR verification state detection

## Problem

The QR login modal only shows its numeric verification input when the API
returns `verification_required=true`. The normal Playwright-CDP status path
currently returns only `scanned`, while the raw-CDP path derives the flag from
the entire page text. This makes the two transports disagree and allows
unrelated page copy to trigger a false verification prompt.

## Goal

Make both QR login transports expose the same verification state, based on a
visible verification-code control that the operator could actually fill.

## Scope

- Share one page-state probe between Playwright-CDP and raw-CDP sessions.
- Detect verification from visible, enabled numeric/code inputs (including
  multi-box code inputs), rather than arbitrary body text.
- Return `verification_required: false` explicitly for a scanned session when
  no verification control is present; return `true` only when the control is
  visible and fillable.
- Keep the existing QR status mapping, confirmed-state cleanup, and manual
  verification-code submission behavior unchanged.
- Add regression tests for normal CDP and raw-CDP status responses and update
  the browser-safety spec with the detection contract.

## Acceptance criteria

1. A normal CDP `scanned` response includes an explicit boolean
   `verification_required` derived from the active login page.
2. A raw-CDP response uses the same detection semantics and does not classify
   unrelated page text as a verification request.
3. Confirmed/waiting/expired responses do not expose a stale verification flag.
4. Existing verification-code submission and login cleanup tests continue to
   pass.
5. Targeted backend tests, Ruff, mypy, formatting, and diff checks pass.
