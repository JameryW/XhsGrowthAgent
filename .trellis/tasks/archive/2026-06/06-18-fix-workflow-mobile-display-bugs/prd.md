# Fix Workflow and Mobile Display Bugs

## Problem

The workflow implementation has several cross-layer bugs in gate resume defaults, realtime state syncing, multi-workflow frontend state isolation, and mobile display/navigation behavior. These can leave users stuck at human gates, show stale or cross-thread optimization data, miss newly pending reviews, or fail to recover mobile WebSocket sessions.

## Scope

- Fix backend workflow resume defaults for blogger selection and remove duplicate workflow-completed event emission.
- Sync workflow realtime payloads into frontend state for blogger/ripple-related fields.
- Prevent optimization state from leaking across workflow tabs.
- Improve mobile navigation access to start/settings/logout and correct mobile timeline/header display for waiting states.
- Make WebSocket reconnect after server heartbeat timeout/background mobile throttling.
- Keep brief PDF upload API on the shared API client path.
- Add or update focused tests for changed backend/frontend logic where practical.

## Acceptance Criteria

- Generic resume at blogger selection skips safely instead of producing an invalid blogger selection.
- Workflow completed events are emitted from the runner only.
- Dashboard can show blogger candidates from realtime events without requiring manual refresh.
- Switching workflow tabs cannot show stale optimization versions or hide current choices because of another tab's selected version.
- Timeline/header accurately identify awaiting brief, ripple, blogger, choice, draft, and review states.
- Mobile users have visible access to start/settings/logout.
- WebSocket reconnects after heartbeat timeout closure.
- Type check and focused backend tests pass.
