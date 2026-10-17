# fix flaky xhs_login QR confirm test

## Goal

Stabilize `test_status_confirmed_after_code_status_2` which flakes on CI when autouse-shrunk `_QR_CONFIRM_TIMEOUT_S` (0.01s) expires before `get_status()` applies `codeStatus=2`.

## Requirements

* Mirror sibling pattern: keep QR unexpired (`_qr_created_at = time.time()`) before asserting confirmed path.

## Acceptance Criteria

* [x] Confirmed-status test does not race QR expiry
* [x] Related login status tests still pass

## Out of Scope

* Production login behavior changes
