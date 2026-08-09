# xhs_publisher exception log diagnostics

## Goal

Improve diagnosis of publish failures while preserving the publisher's
existing result and retry behavior. The two remaining publish-path exception
logs should distinguish exception classes such as timeouts, browser failures,
and malformed responses instead of recording only their string messages.

## Scope

Update these two sites:

- `backend/tools/xhs/publisher.py`: tool-level publish failure log;
- `backend/services/xhs_publisher.py`: `_wait_for_success` pending fallback log.

Keep the existing log levels, fallback result payloads, traceback behavior, and
browser/CDP lifecycle unchanged. Add `type(e).__name__` next to the original
message. Do not log cookies, tokens, or page contents.

## Acceptance criteria

- Both logs contain the concrete exception type and original message.
- Tool publish failures still return `status="error"` and close the publisher.
- `_wait_for_success` exceptions still return `status="pending"` with the
  existing manual-confirmation error.
- Add focused regression tests for both paths and assert the diagnostic log.
- `ruff format --check`, `ruff check`, targeted tests, mypy, and full pytest
  pass.

## Out of scope

- No changes to publish selectors, retries, anti-risk gates, CDP attachment,
  cookies, or API result contracts.

## Implementation result

- Added `type(e).__name__` to the publish-tool error log and the
  `_wait_for_success` pending fallback log.
- Added regression coverage for both paths, including the original fallback
  result and publisher cleanup behavior.
- Validation: targeted publisher tests `18 passed`, full pytest `2132 passed`,
  backend mypy passed for 165 files, ruff format/check passed, and
  `git diff --check` passed.
