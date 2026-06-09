# Home Page Layout, Dashboard Width & Replay Mode Fix

## Goal

Fix layout issues across Home/Dashboard pages and a bug in replay mode:
1. Home page `max-w-3xl` (768px) causes excessive whitespace on desktop
2. Checklist + system status panels side-by-side in a narrow container looks weird
3. Dashboard `max-w-7xl` should be removed to match Review/History
4. Replay mode: clicking timeline nodes does nothing because `findCheckpointForAgent` matches `source` (always `"loop"`) instead of `current_agent`

## Requirements

* Home page container should fill available width (remove max-w-3xl) to match Review/History/Dashboard
* Dashboard should remove `max-w-7xl` to fill available width like Review/History
* Home page panels (checklist + system status) should stack vertically on desktop instead of side-by-side
* Replay mode: `findCheckpointForAgent` should match by `current_agent` field, not `source`
* Mobile layout remains unchanged

## Acceptance Criteria

* [ ] Home page has minimal whitespace on 1440px screens
* [ ] Dashboard content fills available width without max-w constraint
* [ ] Checklist and system status panels stack vertically on desktop
* [ ] Replay mode node clicks correctly select corresponding checkpoints
* [ ] Mobile (375px) and tablet (768px) layouts not regressed
* [ ] Typecheck green

## Definition of Done

* Lint / typecheck green
* All pages visually verified in browser at desktop/tablet widths
* Frontend build + deploy verified

## Out of Scope

* Dashboard sub-component layout changes
* Home page redesign or new features
* Color/theme system changes

## Technical Notes

* Key files: frontend/src/views/Home.vue, frontend/src/views/Dashboard.vue, frontend/src/components/dashboard/WorkflowTimeline.vue
* App.vue provides outer padding (p-6 desktop, p-4 tablet, p-3 mobile)
* Review/History have no max-w — they naturally fill the padded area
* LangGraph checkpoint metadata `source` is `"loop"` (internal), not the agent name; `current_agent` is the correct field to match
* Backend CheckpointSnapshot includes `current_agent` field (workflow.py:562)