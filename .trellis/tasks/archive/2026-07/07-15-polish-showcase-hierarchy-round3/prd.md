# Showcase Hierarchy Polish — Round 3

## Goal

Give the Showcase a more cohesive visual system: the hero should establish the product promise, the loop should feel like the visual signature, and live workflow cards should read as a calm, useful workspace rather than a dense feed.

## Scope

- Refine hero, loop, live workspace summary, filter toolbar, workflow cards, and footer styling.
- Improve responsive spacing and content density without changing data fetching, filtering, sorting, replay navigation, or CTA destinations.
- Keep all visible copy localized, touch targets accessible, and existing reduced-motion behavior safe.

## Acceptance Criteria

1. Desktop and mobile have one obvious primary focal action and a consistent visual rhythm between sections.
2. The process loop remains the signature visual while live statistics and workflow cards have clearer hierarchy.
3. Workflow cards expose status/progress quickly without making detail content feel cramped.
4. Narrow layouts avoid horizontal overflow and keep controls comfortably tappable.
5. Loading, error, empty, filtered-no-result, and footer states remain aligned with the new visual system.
6. Type-check, full tests, production build, diff check, and runtime HTTP checks pass.
