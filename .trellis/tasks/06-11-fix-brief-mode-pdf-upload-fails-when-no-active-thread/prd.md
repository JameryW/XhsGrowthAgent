# fix: brief mode PDF upload fails when no active thread

## Goal

Fix brief mode workflow when user uploads PDF without typing text: the workflow must start correctly and route to brief_analyzer, not error out.

## Root Cause

Two issues:

1. **Backend start endpoint**: When `workflow_mode=brief` but `brief_text` is None, `start_workflow` did not set `phase=BRIEFING` (only set when both `workflow_mode=brief AND brief_text`). This caused the orchestrator to route to `trend_scout` instead of `brief_analyzer`.

2. **Brief analyzer error on empty raw_text**: `BriefAnalyzerAgent.execute()` returned `phase=ERROR` when `raw_text` was empty, terminating the workflow. This happened because the graph starts executing immediately and `brief_analyzer` runs before the PDF upload completes.

## Fix

1. **Start endpoint** (`workflow.py`): Always set `phase=BRIEFING` when `workflow_mode=brief`. When `brief_text` is absent (PDF upload pending), save the initial state to checkpoint but don't start graph execution. Return `thread_id` so the PDF upload can proceed.

2. **Upload endpoint** (`workflow.py`): After `aupdate_state` with `brief_content`, check if the workflow is paused and start graph execution if so.

3. **Brief analyzer** (`brief_analyzer.py`): When `raw_text` is empty, return `phase=BRIEFING` with `resolved=False` instead of `phase=ERROR`. This handles edge cases where the analyzer somehow runs before content arrives.

## Acceptance Criteria

- [x] Brief mode start without `brief_text` sets `phase=BRIEFING`
- [x] Graph doesn't start execution when brief content is pending
- [x] PDF upload triggers graph execution
- [x] Brief analyzer doesn't error on empty `raw_text`
- [x] Brief mode with `brief_text` (no PDF) works unchanged
- [x] All 758 existing tests pass

## Technical Notes

- Frontend flow: `startWorkflow(brief, no text)` → get `thread_id` → `uploadPendingPdf(thread_id)` → backend saves content + starts graph
- `aupdate_state` with `as_node="orchestrator"` creates a checkpoint that the graph can resume from
- `_start_resume_task` is reused to start execution after upload
