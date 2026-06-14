# Findings

## Summary

The current production service on `http://127.0.0.1:8889/` renders frontend content successfully. The blank page observed during local dev reproduction is caused by Vite dev/HMR configuration interacting with a port conflict, not by a Vue runtime exception in `Showcase.vue`.

## Evidence

- `npm run build` in `frontend/` passed.
- `/start` mounted normally and redirected to `/login?redirect=/start`.
- `/` initially showed only the App shell while the route view was still empty, but after waiting it rendered `Showcase.vue` content.
- Browser console repeatedly logged Vite HMR failures:
  - `WebSocket connection to 'ws://127.0.0.1:3000/?token=...' failed`
  - `[vite] server connection lost. Polling for restart...`
- `ss` showed port `3000` is occupied by the `umami_umami_1` container, while the dev server was on `5174`.
- `frontend/vite.config.ts` hardcodes `server.hmr.clientPort = 3000`, so when Vite runs on another port it still tells the browser to connect HMR to `3000`.
- The production container served `/`, JS/CSS assets, `/api/workflow/list`, and workflow detail endpoints with HTTP 200.

## Likely Fix

Make Vite HMR use the actual dev server port instead of hardcoding `3000`, or make port `3000` strict/free before starting Vite. The narrow code fix is to remove `hmr.clientPort: 3000` from `frontend/vite.config.ts` unless there is a reverse proxy that requires it.

The recent analytics scripts in `frontend/index.html` are not the primary reproduced failure, but because they are external head scripts they can still increase startup sensitivity if the analytics host is slow.
