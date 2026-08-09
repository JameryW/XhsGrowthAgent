# creator-stats pipeline exception log diagnostics

## Goal

Improve diagnosis of creator-statistics synchronization fallbacks without
changing sync results or browser cleanup. The fixture loader and the expected
Creator Center fetch failure path currently log only an exception's string
message, which makes timeout, file, and transport failures harder to separate.

## Scope

Update the two warning sites in `backend/services/creator_stats/pipeline.py`:

- fixture payload loading failure;
- `CreatorStatsFetchError` during live Creator Center fetch.

Keep warning levels, returned `SyncResult` fields, `error_code` classification,
and the `finally` transport close behavior unchanged. Include
`type(e).__name__` and the original message with parameterized logging. Do not
log cookies, page contents, or account credentials.

## Acceptance criteria

- Both warning records contain the concrete exception type and original
  message.
- Fixture failures still return a fixture-sourced error result without raising.
- Creator Stats fetch failures still return the classified error result and
  always close the injected client.
- Add focused caplog assertions for both paths.
- `ruff format --check`, `ruff check`, targeted tests, mypy, and full pytest
  pass.

## Out of scope

- No changes to Creator Center request/retry behavior, risk controls, sync
  classification, persistence, or browser lifecycle.

## Implementation result

- Added exception types to the fixture-load and Creator Center fetch warning
  logs while preserving `SyncResult`, error-code classification, and client
  cleanup behavior.
- Extended the existing fixture and live-fetch failure tests with caplog
  assertions; the live-fetch test also verifies the injected client's
  `aclose()` call.
- No spec update was needed; the logging and browser-safety guidelines already
  cover this behavior.
- Validation: creator-stats tests `232 passed`, full pytest `2141 passed` with
  one pre-existing Starlette/httpx deprecation warning, backend mypy passed for
  165 files, ruff check/format passed for backend and tests, and
  `git diff --check` passed.
