# Fix public showcase authentication error

## Problem

The public showcase and replay routes are intentionally allowed to render without authentication. The router already skips the initial auth validation for these routes, but both route components still call `authStore.initialize()` during mount. In a browser with stale auth state or a deployment where the validation endpoint is protected, that redundant request can surface the API error `Authorization token required` on an otherwise public page.

## Scope

- Remove route-level auth initialization from `Showcase.vue` and `WorkflowReplay.vue`.
- Keep authentication state read-only on public pages so CTA routing still reflects the current local session.
- Preserve the existing auth guard for protected routes and the existing `suppressToast` behavior for public data requests.
- Add regression coverage proving public pages do not initialize auth when mounted anonymously/uninitialized.

## Acceptance criteria

1. Opening `/` or `/replay/:publicId` with no auth token does not request auth validation and does not show `Authorization token required`.
2. Public showcase/replay data requests and their local error states continue to work as before.
3. Protected routes still initialize and validate auth through the router guard.
4. The focused frontend tests, type-check, and production build pass.

## Out of scope

- Changing backend authentication dependencies or weakening protected endpoints.
- Changing login, logout, or authenticated CTA behavior.
