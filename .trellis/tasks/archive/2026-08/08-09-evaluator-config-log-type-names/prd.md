# evaluator_config exception log diagnostics

## Goal

Improve diagnosis of the RQGM evaluator-weight fallback paths. Database
failures in `backend/db/evaluator_config.py` are intentionally swallowed so
weight loading and online evolution can continue, but their warning logs
currently record only the exception message. Include the concrete exception
class so operators can distinguish connection, timeout, and data failures.

## Scope

Update the four warning sites that handle DB-related fallback behavior:

- evaluator-weight override loading;
- labeled-sample loading during training;
- fitted-weight application;
- non-blocking online evolution.

Keep log levels, fallback values, training results, evolution reports, and
publish-path behavior unchanged. Use parameterized logging with
`type(e).__name__` and the original exception message. Do not expose
credentials, prompts, or sample contents.

## Acceptance criteria

- All four scoped warning records contain the concrete exception type and
  original message.
- Weight loading still returns defaults when the DB fails.
- Training still returns a report and does not raise on fetch/apply failures.
- Online evolution still returns an error report and releases its guard.
- Add focused caplog assertions for all four paths.
- `ruff format --check`, `ruff check`, targeted tests, mypy, and full pytest
  pass.

## Out of scope

- No changes to evaluator weight calculation, DB queries, transaction scope,
  evolution thresholds, user-facing report strings, or event behavior.

## Implementation result

- Added exception types to all four scoped warning logs while preserving the
  original fallback values, reports, and event behavior.
- Added caplog assertions for DB override loading, training sample fetch,
  training weight application, and online evolution failure paths.
- No spec update was needed; the repository logging guideline already defines
  this exception-diagnostic convention.
- Validation: evaluator-config tests `40 passed`, full pytest `2141 passed`
  with one pre-existing Starlette/httpx deprecation warning, backend mypy
  passed for 165 files, ruff check/format passed for backend and tests, and
  `git diff --check` passed.
