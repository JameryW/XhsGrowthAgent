# Fix Ripple Timeout Recovery Integration

## Problem

XHS workflows mark Ripple as unavailable after 900 seconds even though Ripple jobs commonly finish later. Recent production evidence showed:

- `job_9115c07603aa` completed after 1328 seconds.
- `job_138e392e1e40` completed after 1415 seconds.
- Recent Ripple job median completion time is about 1341 seconds, with most jobs exceeding the XHS 900 second wait limit.

The workflow falls back to zero-valued Ripple results, often loses the Ripple `job_id`, and cannot recover the final result after the job completes.

Follow-up workflow testing showed a second failure mode: completed Ripple jobs now return `prediction.relative_estimate`, `prediction.verdict`, `timeline`, and `observation.phase_vector` instead of legacy `output.metrics` / `output.phase_analysis`. XHS parsed those completed jobs as all-zero results, so the UI still looked like Ripple was unavailable.

## Goals

- Preserve Ripple `job_id` on XHS timeout.
- Avoid an outer timeout swallowing `RippleTimeoutError`.
- Align cancellation with Ripple's current two-step cancel API when available.
- Preserve graceful fallback behavior when cancel is unsupported or the job finishes later.
- Parse current Ripple output-json artifacts without synthesizing zero absolute metrics.
- Display relative estimates and qualitative Ripple signals in the UI.
- Add focused tests for timeout job id preservation, two-step cancel, and recovery status handling.

## Non-Goals

- Do not modify the Ripple service container code in this task.
- Do not increase workflow complexity with background recovery polling.
- Do not change workflow gate behavior.

## Acceptance Criteria

- Timeout fallback result includes the Ripple `job_id` whenever submission succeeded.
- `RippleService.cancel_simulation` attempts `cancel-request` and `cancel-confirm`, and still handles unsupported legacy cancel behavior safely.
- `recover_result` recognizes `completed`, `running`, `failed`, `not_found`, and `timed_out`.
- Current Ripple output-json shape is parsed into non-fallback Ripple data with relative estimate fields preserved.
- UI does not treat completed relative-estimate results as all-zero fallback.
- Unit tests cover the changed behavior.
