# accounts exception log diagnostics

## Goal

Improve diagnosis of account migration and per-account CDP fallback paths
without changing their graceful-degradation behavior. The remaining caught
exceptions in `backend/db/accounts.py` should identify the concrete exception
class instead of recording only its string message.

## Scope

Update the three warning sites in `backend/db/accounts.py`:

- legacy `owner_user_id` migration failure;
- CDP port allocation when account listing fails;
- per-account CDP endpoint lookup when account loading fails.

Keep warning levels, return values, pool-readiness checks, and migration/port
allocation behavior unchanged. Add `type(e).__name__` next to the original
message using parameterized logging. Do not log credentials, cookies, or
account contents.

## Acceptance criteria

- All three logs contain the concrete exception type and original message.
- Migration failure remains best-effort and does not abort account startup.
- CDP allocation failure still returns port `0`.
- CDP endpoint lookup failure still returns an empty endpoint for global-CDP
  fallback.
- Add focused regression tests asserting the diagnostic records and existing
  fallback values.
- `ruff format --check`, `ruff check`, targeted tests, mypy, and full pytest
  pass.

## Out of scope

- No changes to account schema, ownership migration semantics, CDP port
  selection, or endpoint resolution.

## Implementation result

- Added exception types to the owner migration, CDP port allocation, and
  per-account CDP endpoint warning logs while preserving all fallbacks.
- Added three regression tests asserting the concrete exception type, original
  message, and existing fallback result for each path.
- No spec update was needed; the repository logging guideline already records
  this exception-diagnostic convention.
- Validation: account tests `12 passed`, full pytest `2139 passed` with one
  pre-existing Starlette/httpx deprecation warning, backend mypy passed for
  165 files, targeted ruff format/check passed, and `git diff --check` passed.
