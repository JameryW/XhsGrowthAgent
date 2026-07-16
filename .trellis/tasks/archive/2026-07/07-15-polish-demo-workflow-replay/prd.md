# Demo Workflow Replay Visual Polish

## Goal

Make the demo-mode workflow replay page feel like the natural second screen of the Showcase: an immersive but readable live system view with a clear pipeline, checkpoint history, focused result canvas, and compact output summary.

## Scope

- Refine the replay navigation and inline pipeline so the current workflow state is easier to scan.
- Add a stronger visual hierarchy for the checkpoint rail, selected agent result, summary sidebar, and demo-mode banner.
- Add restrained ambient motion, active-state glow, progress accents, and responsive spacing without changing replay state, API calls, or navigation behavior.
- Preserve localization, keyboard focus, 44px touch targets, mobile overflow safety, and reduced-motion behavior.

## Acceptance Criteria

1. Demo replay has an obvious reading order: workflow identity → pipeline state → selected checkpoint result → output summary.
2. Selected and running pipeline/checkpoint states are visually distinct without obscuring result content.
3. Desktop and mobile layouts remain readable with no page-level horizontal overflow.
4. Empty, loading/no-data, and demo-mode states use the same visual system as Showcase.
5. Type-check, full tests, production build, diff check, and runtime HTTP checks pass.
