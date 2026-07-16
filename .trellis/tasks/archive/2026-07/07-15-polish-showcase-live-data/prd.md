# Showcase Live Data Hierarchy

## Goal

Make the lower half of the public Showcase feel like a calm live workspace: summarize the current state first, spotlight one workflow, then let users scan and filter the remaining cards.

## Scope

- Refine the live workspace heading, stats, featured workflow, filter toolbar, card grid, load-more control, and footer.
- Improve narrow-screen spacing and card readability without changing workflow data, filtering, sorting, replay navigation, or API behavior.
- Preserve localization, keyboard focus, 44px touch targets, and reduced-motion behavior.

## Acceptance Criteria

1. Statistics, featured content, filters, and cards have an obvious visual reading order.
2. Featured workflow is visually distinct but does not overpower the workflow list.
3. Mobile card content and controls remain readable with no page-level horizontal overflow.
4. Load-more, no-result, and footer states match the same visual system.
5. Type-check, full tests, production build, diff check, and runtime HTTP checks pass.
