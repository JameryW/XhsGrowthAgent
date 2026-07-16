# Restructure Showcase and Replay Layouts

## Goal

Give the public Showcase and demo WorkflowReplay two coherent, calm workspace layouts with a clear visual reading order and less competing surface treatment.

## Scope

- Recompose Showcase around a compact entry hero, one focused live-workspace canvas, and a disciplined workflow list.
- Recompose WorkflowReplay around workflow identity, pipeline navigation, checkpoint navigation, one primary result canvas, and a secondary summary rail.
- Reduce decorative noise, repeated headings, oversized empty areas, and competing cards while retaining the existing data, filtering, replay, and navigation behavior.
- Keep mobile layouts single-column, horizontally scrollable only where intentional, and preserve localization, keyboard focus, touch targets, and reduced-motion behavior.

## Acceptance Criteria

1. Both pages have an obvious first-to-last reading order at desktop and mobile widths.
2. Primary content occupies the visual focus; background effects and secondary cards support rather than compete with it.
3. Showcase live workflows and Replay results remain readable without page-level horizontal overflow.
4. Existing workflow API calls, filters, checkpoint selection, replay lifecycle, and route behavior are unchanged.
5. Type-check, full tests, production build, diff check, screenshots, and runtime HTTP checks pass.
