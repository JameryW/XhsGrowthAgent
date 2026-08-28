# Expose free publishing controls

## Goal

Make the free-creation welcome screen communicate the complete draft lifecycle: create, inspect, evaluate, publish, and fall back to manual publishing when needed.

## Problem

The free-mode command grid currently exposes session controls, draft management, and insights, while `/publish` and `/copy` are only discoverable through `/help`. This makes the final step of the product workflow invisible at the moment a user is deciding what to do next, even though both commands are already implemented and supported by the existing command parser.

## Scope

- Add a dedicated Publishing group to the free-mode command grid.
- Show `/publish <id> [confirm]` with a clear confirmation hint.
- Show `/copy <id>` as the manual-posting fallback.
- Add matching English and Simplified Chinese locale strings.
- Add a focused regression test that verifies both commands render in the free command grid.
- Preserve the existing command semantics, including explicit publish confirmation, degraded-mode blocking, and responsive one-column fallback on narrow terminals.
- Keep the change within the AgentTUI presentation seam; no new store, API, or backend behavior is required.

## Acceptance criteria

1. A free-mode user can discover both publishing controls without opening `/help`.
2. The command grid remains readable in English and Simplified Chinese and does not introduce a fixed-width overflow on narrow terminals.
3. Typing `/publish` still requires the existing explicit `confirm` argument; rendering the command must not trigger a side effect.
4. Typing `/copy` remains the only action that copies draft content for manual publishing.
5. The focused test, type-check, i18n parity check, and production build pass.
