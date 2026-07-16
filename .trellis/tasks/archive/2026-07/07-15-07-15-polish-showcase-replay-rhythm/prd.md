# Showcase / Replay interaction rhythm

## Goal

Complete another refinement pass so users can tell what is informational, what is current, and what is actionable at a glance.

## Requirements

- Keep Showcase hero, workflow overview, featured item, filters, and records visually distinct without adding duplicate actions.
- Make delayed detail loading and filtered results feel stable and intentional.
- Make WorkflowReplay show the active checkpoint and current execution context without duplicating phase indicators.
- Preserve mobile touch targets, horizontal overflow containment, localization, reduced motion, lazy loading, and existing navigation behavior.

## Acceptance

- No layout jump when featured/detail data arrives.
- Current selection and next action are visible in both pages.
- Desktop and mobile screenshots show no clipped primary content or page-level horizontal scroll.
- Type-check, build, full tests, route checks, and diff check pass.
