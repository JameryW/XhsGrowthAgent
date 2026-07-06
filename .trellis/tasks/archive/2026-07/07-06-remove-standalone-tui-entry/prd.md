# PRD: Remove Standalone TUI Entry

## Goal

Remove the standalone TUI navigation entry so that the TUI page is reachable only via the "开始创作" → 自由模式 flow. This keeps TUI as a destination of the creation-mode split, not an independent page users can navigate to directly.

## Requirements

- Remove the `/tui` item from `Navbar.vue` desktop nav.
- Remove the `/tui` item from `MobileTabBar.vue` mobile tab bar.
- Keep the `/tui` route in `router/index.ts` — `Home.vue` free-mode flow still navigates to it via `router.push({ name: 'tui', query })`.
- Leave the `nav.tui` i18n key in place (harmless, no longer rendered).

## Acceptance Criteria

- Desktop navbar no longer shows a TUI tab.
- Mobile tab bar no longer shows a TUI tab.
- Selecting 自由模式 from `CreationModeModal` still routes to `/tui?mode=free...` and the page works.
- `ruff check`, `vue-tsc --noEmit` pass.
