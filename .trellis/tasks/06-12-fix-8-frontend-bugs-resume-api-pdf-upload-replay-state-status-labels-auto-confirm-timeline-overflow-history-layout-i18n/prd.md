# PRD: Fix 8 Frontend Bugs

## Summary
Fix 8 identified frontend bugs covering API consistency, PDF upload thread mismatch, replay state inconsistency, status label coverage, auto-confirm race condition, timeline mobile overflow, history layout overflow, and i18n violations.

## Bugs & Fixes

### Bug 1: resumeWorkflow() bypasses axios client
- **File**: `frontend/src/stores/workflow.ts:704`
- **Problem**: `resumeWorkflow()` with `resumeValue` does raw `fetch('/api/...')`, no `res.ok` check, no `ApiResponse` unwrap. Backend errors silently ignored, frontend sets state to running + toast success.
- **Fix**: Extend `frontend/src/api/workflow.ts:54` `resumeWorkflow` to accept optional `resume_value`, use `client.post()` consistently. Update store to call the API function.

### Bug 2: PDF upload uses wrong thread ID
- **File**: `frontend/src/components/WorkflowStartForm.vue:42`
- **Problem**: PDF upload uses `workflowStore.currentThreadId` — if user has an active workflow, PDF uploads to old thread. No active thread → queues upload, but backend only sets `briefing` phase when `brief_text` exists.
- **Fix**: Track the thread ID from the start response and use it for PDF upload. Ensure upload happens after thread creation with correct ID.

### Bug 3: Replay state inconsistency
- **File**: `frontend/src/stores/workflow.ts`, `frontend/src/components/dashboard/WorkflowTimeline.vue`
- **Problem**: Store has `effectiveState` but components read live `workflowState` or global `progressPercent`. `progress_percent` hardcoded to 0 at line 78. Replay shows checkpoint phase but live agent/content/progress.
- **Fix**: Components in replay mode must read from `effectiveState` and checkpoint-derived progress. Remove hardcoded `progress_percent: 0`.

### Bug 4: Status label incomplete coverage
- **File**: `frontend/src/components/dashboard/WorkflowHeader.vue:38`
- **Problem**: Only distinguishes stale / partial awaiting / running, rest shows idle. `completed`, `error`, `paused`, `cancelled`, `awaiting_blogger_selection`, `awaiting_ripple_decision` display incorrectly.
- **Fix**: Add explicit cases for all known states with appropriate labels and colors.

### Bug 5: BriefFileUpload auto-confirms on text arrival
- **File**: `frontend/src/components/BriefFileUpload.vue:35`
- **Problem**: Upload text arrival triggers `emit('confirm')` immediately, but component has editable preview + confirm button. Dashboard auto-resumes, user can't edit.
- **Fix**: Remove auto-emit on text arrival. Let user review and explicitly click confirm.

### Bug 6: Timeline mobile overflow
- **File**: `frontend/src/components/dashboard/WorkflowTimeline.vue:346`, `frontend/src/views/WorkflowReplay.vue:383`
- **Problem**: `flex justify-between` with `min-w-[60px]` nodes. 6 nodes = 360px minimum, mobile viewport ~296px. Nodes get clipped.
- **Fix**: Use horizontal scroll with `overflow-x-auto` on mobile, or reduce node size on small screens.

### Bug 7: History list mobile overflow
- **File**: `frontend/src/views/History.vue:197`
- **Problem**: Single-row flex with long thread ID + multiple action buttons. Small screens overflow.
- **Fix**: Mobile: stack actions below, show short ID only.

### Bug 8: Hardcoded English labels violate i18n
- **File**: `frontend/src/components/dashboard/ContentCards.vue:280` and others
- **Problem**: Labels like Topic/Angle/Audience/Key Points/Analytics/Views hardcoded in English.
- **Fix**: Replace with i18n keys, add Chinese translations.

## Scope
- Frontend only, no backend changes except possibly extending resume API signature
- Each fix is independent and can be verified individually
