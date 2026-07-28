# Persisted CDP engagement and public note access hardening

## Context

The current engagement service starts a separate Playwright browser, injects
cookies into a temporary context, and opens public note URLs directly. This
does not reuse the account's already-authenticated headed Chrome profile and
causes unnecessary main-site automation traffic. Creator statistics already
have a safer CDP path, but the public note body path must remain disabled by
default and the safe-mode policy should be explicit.

## Requirements

1. Make engagement operate through an account's persistent CDP Chrome when an
   endpoint is available. Do not launch a second headless browser, create a
   temporary cookie-only context, or add automation-stealth flags.
2. Serialize engagement operations per account/client and apply a conservative
   fixed cooldown between navigations/actions. A platform challenge, login
   shell, or risk-control response must stop the operation and must not be
   retried automatically.
3. Keep creator-statistics collection on the Creator Center surface. Public
   note-body navigation remains opt-in and disabled in the deployed safe
   configuration; safe mode must be enabled explicitly for the production
   service.
4. Preserve existing publishing and creator-statistics behavior, including
   CDP login state and existing test doubles.
5. Remove all actual headless browser execution from the repository's XHS
   paths (and keep the shared browser audit headed as well). Legacy
   `headless` parameters may remain only for source compatibility and must be
   ignored.

## Scope

- `backend/services/xhs_engagement.py`
- `backend/services/xhs_client.py`
- engagement callers that resolve the per-account CDP endpoint
- creator-stats runtime configuration/deployment defaults
- focused unit tests and relevant documentation/spec notes

## Acceptance criteria

- A CDP-backed engagement instance attaches to the supplied account Chrome and
  never calls `chromium.launch`, `new_context`, cookie injection, or stealth
  flags.
- Engagement actions are serialized and enforce the cooldown; risk/login
  pages return a structured failure and no follow-up action is attempted.
- Existing no-CDP callers fail closed with a clear configuration message rather
  than silently starting a new browser.
- Creator stats tests confirm public-body visits are zero by default and safe
  mode clamps the configured crawl budgets.
- Focused tests, Ruff, and formatting checks pass.
