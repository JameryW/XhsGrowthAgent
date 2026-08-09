# xhs_login exception log diagnostics

## Goal

Improve operational diagnosis for recoverable failures in the XHS login and
read-only login-status paths by including the concrete exception type in the
existing warning messages. This continues the observability cleanup started by
the evaluator-config log fix, without changing user-visible behavior.

## Scope

Update the six `backend/services/xhs_login.py` warning sites that currently log
only `str(e)`/`str(exc)`:

- page-side QR status polling;
- QR response interception;
- optional playwright-stealth fallback;
- raw-CDP login-status inspection;
- Playwright-CDP connection failure;
- general login-status inspection failure.

Keep the existing message text, severity, and control-flow fallback intact;
append `type(e).__name__` using the module's established `%s` formatting.
Do not log cookie values, full page text, or introduce a new browser action.

## Acceptance criteria

- Each of the six warning messages contains the exception type and message.
- Return values, status/reason fields, cleanup, and fallback behavior remain
  unchanged.
- Add focused regression coverage that exercises representative page,
  interception, stealth, and CDP/status failure paths and verifies the log
  records contain the concrete exception type.
- `ruff format --check`, `ruff check`, targeted login tests, and mypy pass.

## Out of scope

- No change to login-state evidence rules or browser automation safety.
- No change to log level, logger namespace, API response shape, or exception
  handling policy.

## Implementation result

- Updated all six scoped warnings to include `type(e).__name__` and the
  original exception message.
- Added six focused log-diagnostic regression tests.
- Added the exception-type rule to the backend logging spec.
- Validation: 2130 pytest tests passed, backend mypy passed for 165 files,
  ruff format/check passed, and `git diff --check` passed.
