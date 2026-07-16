# Continue Showcase Visual Polish

## Goal

Make the public Showcase feel more deliberate and faster to first interaction while removing duplicate creation guidance.

## Scope

- Keep one prominent “go create” CTA in the hero; make the navigation action a lighter secondary entry with distinct copy.
- Reduce first-screen work and unnecessary detail requests while preserving workflow filtering, sorting, replay navigation, and featured content behavior.
- Keep visual hierarchy, responsive layout, i18n, keyboard focus, reduced-motion behavior, and 44px touch targets intact.

## Acceptance Criteria

1. The page no longer presents two visually equivalent “go create” buttons.
2. Showcase shell and process visuals render without blocking the first workflow list paint.
3. Workflow details are loaded only when needed, with the featured workflow still becoming available and visible cards remaining hydrated.
4. Loading, error, empty, and retry states remain understandable.
5. Type-check, full tests, production build, diff check, and runtime health checks pass.
