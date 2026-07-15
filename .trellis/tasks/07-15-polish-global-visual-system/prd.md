# Global Visual System Polish

## Goal

Create a more coherent visual baseline across authenticated pages by improving the shared page header, cards, form controls, tables, and application background without changing page behavior or data flows.

## Scope

- Add restrained depth, highlight, and motion accents to shared headers and cards.
- Improve form control focus/hover states and table readability.
- Keep the authenticated app shell background structured but lightweight.
- Preserve responsive behavior, localization, keyboard focus, reduced-motion support, and existing component APIs.

## Acceptance Criteria

1. Shared page headers and cards have a consistent surface hierarchy and clearer focal accents.
2. Form controls and table surfaces provide visible, accessible interaction states.
3. Mobile layouts retain touch targets and do not introduce page-level horizontal overflow.
4. Reduced-motion users do not receive delayed or hidden content.
5. Type-check, full tests, production build, diff check, and runtime HTTP checks pass.
