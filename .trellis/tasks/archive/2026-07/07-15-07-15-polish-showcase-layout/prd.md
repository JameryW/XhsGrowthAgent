# Showcase Layout & Visual Polish

## Goal

Continue improving the public Showcase page so its visual hierarchy communicates the product loop quickly, feels intentional on desktop and mobile, and keeps workflow data easy to scan.

## Scope

- Refine the public page shell, intro hero, workflow loop, stats strip, featured workflow, filters, cards, and footer.
- Reduce excessive vertical space and improve the transition from product story to live workflow data.
- Preserve all existing workflow fetching, filtering, replay navigation, and authentication behavior.
- Keep visible copy localized in both `zh-CN.json` and `en.json`.
- Keep keyboard navigation, reduced-motion behavior, focus visibility, and 44px touch targets intact.

## Acceptance Criteria

1. Desktop first viewport presents a clear brand/CTA header, concise product proposition, and a visually balanced workflow loop without forcing excessive scrolling before live data.
2. Mobile layout avoids horizontal overflow, keeps the process explanation readable, and retains comfortable touch targets for CTA, filters, cards, and load-more actions.
3. Stats, featured workflow, filters, and card grid have distinct visual hierarchy and consistent spacing.
4. Loading, error, empty, and filtered-no-result states remain understandable and visually aligned with the page shell.
5. Existing i18n, replay navigation, and data/state behavior remain unchanged.
6. Type-check, tests, production build, diff check, and deployed health checks pass.
