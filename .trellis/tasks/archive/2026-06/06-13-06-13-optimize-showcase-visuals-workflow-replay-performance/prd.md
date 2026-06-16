# Optimize Showcase Visuals And Workflow Replay Performance

## Goal

Improve the public showcase visual quality and reduce jank on the workflow replay detail page.

## Requirements

1. Showcase page should feel more polished on first paint without burying real workflow cards behind decorative effects.
2. Workflow replay page should render checkpoint and node-heavy views with less main-thread work and fewer expensive CSS effects.
3. Liquid glass surfaces should look clearer and more premium while using lower-cost blur/shadow settings.
4. Keep the existing API/data contracts unchanged.
5. Preserve existing replay functionality: checkpoint rail, node selection, summary sidebar, and agent result rendering.
6. Keep changes scoped to frontend presentation and rendering performance.

## Acceptance

- Showcase page first viewport has clearer hierarchy, better spacing, and lighter decorative motion.
- Workflow replay remains visually readable but avoids avoidable re-renders and heavy animation/filter effects.
- Liquid glass cards/nav/inset surfaces retain the glass style with improved contrast and reduced blur cost.
- `npm -C frontend run build` passes.
- `npm -C frontend run type-check` passes, or any existing unrelated failures are documented.

## Out Of Scope

- Backend workflow/checkpoint API changes.
- New workflow data fields.
- Reworking dashboard/review business logic.
