# chrome_launcher exception log diagnostics

## Goal

Improve operational diagnosis for Chrome profile lifecycle and launcher CLI
degradation paths without changing their fail-safe behavior. The remaining
caught-exception logs should identify the concrete exception class instead of
recording only its string message.

## Scope

Update the four warning sites in `backend/services/chrome_launcher.py`:

- socat forwarder startup failure;
- stale SingletonLock file removal failure;
- launcher CLI database-pool initialization failure;
- launcher CLI account-list loading failure.

Keep log levels, return values, cleanup policy, and browser lifecycle behavior
unchanged. Add `type(e).__name__` next to the original message. Do not expose
credentials, cookies, or browser page contents.

## Acceptance criteria

- All four logs contain the concrete exception type and original message.
- socat/lock failures remain best-effort and return their existing values.
- CLI DB failures still degrade to an empty account list.
- Add focused regression tests for all four logging paths.
- `ruff format --check`, `ruff check`, targeted tests, mypy, and full pytest
  pass.

## Out of scope

- No change to Chrome launch/stop/reap logic, profile locking, CDP ports, or
  browser safety behavior.

## Implementation result

- Added exception types to the socat, stale-lock, DB-pool, and account-list
  warning logs.
- Added four regression tests covering the existing best-effort/empty-list
  fallbacks and their diagnostic records.
- Validation: Chrome launcher tests `67 passed`, full pytest `2136 passed`,
  backend mypy passed for 165 files, ruff format/check passed, and
  `git diff --check` passed.
