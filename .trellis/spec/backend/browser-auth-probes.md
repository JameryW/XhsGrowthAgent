# Browser-backed Authentication Probes

## Creator Center login evidence

The account login-status probe in `backend/services/xhs_login.py` combines two
different kinds of evidence:

- `access-token-creator.xiaohongshu.com` is strong Cookie evidence and may
  immediately return `logged_in`.
- `id_token` and `web_session` alone are only `www_only`; they must not be
  treated as Creator Center login because the pair can survive an expired
  Creator SSO session.
- When the strong Cookie is absent, an already-open
  `creator.xiaohongshu.com` page may provide a second signal. The page must be
  outside the login routes, not show the login shell, and expose at least two
  stable Creator Center business markers before it is accepted as
  `creator_page_ready`.

## Probe safety

Login-status checks are read-only. A CDP fallback may enumerate existing page
targets, attach temporarily to inspect a page, and detach in `finally`, but it
must not navigate a host page, create a new tab, close a target, or log Cookie
values/full page text. A failure to inspect page evidence falls back to the
Cookie result rather than turning an inconclusive probe into a green status.

## Regression boundary

Any change to the evidence rules needs coverage for both raw-CDP and
Playwright-CDP paths, including a ready Creator Center page without the strong
Cookie and a Creator Center login shell with only the main-site Cookie pair.
