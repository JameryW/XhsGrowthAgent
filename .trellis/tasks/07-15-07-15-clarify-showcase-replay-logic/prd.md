# Showcase / Replay logic clarity

## Goal

Make the public showcase and workflow replay pages communicate one clear primary action at a time, with intentional empty and partial-data states.

## Requirements

- Showcase: remove repeated section-title language, separate product orientation from live workflow data, and make empty/filtered states explain the next action.
- Workflow replay: make the selected checkpoint the primary content, keep phase progress as context, and make the no-selection/no-detail states explicit.
- Preserve navigation, filtering, replay selection, localization, keyboard focus, touch targets, reduced-motion behavior, and lazy-loading performance.
- Keep the full-bleed background consistent with the page canvas on desktop and mobile.

## Acceptance

- A first-time user can identify the page purpose and next action without scanning repeated headings.
- Empty, filtered, and no-detail states do not look like broken or unfinished content.
- Desktop and mobile layouts keep a single obvious reading order and do not overflow horizontally.
- Type-check, build, full tests, diff check, and runtime route checks pass.
