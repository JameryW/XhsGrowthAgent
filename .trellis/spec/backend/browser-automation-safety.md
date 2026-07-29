# Browser Automation Safety

## XHS browser execution

All XHS browser operations must run in a headed browser. The legacy
`headless` parameters are retained only for caller compatibility and are
ignored by services; production code must pass or enforce `headless=False`.

When an account has a bound Chrome profile, interactive operations must attach
through its CDP endpoint. Engagement must not start a second browser, create a
cookie-only temporary context, inject stealth scripts, or serialize cookies.
If the account has no usable CDP endpoint, the operation fails closed.
CDP login reuses only the first existing `browser.contexts[0]`; when the bound
Chrome exposes no browser context, login fails with an actionable error and
must never call `browser.new_context()`. Creating a short-lived login page
inside that existing context remains allowed.
QR login status probes use the same browser-side DOM check for Playwright-CDP
and raw-CDP. `verification_required` is true only when a visible, enabled
numeric/code input exists, including a multi-box code control; visible page
copy alone is not evidence. The flag is returned only with `scanned` status
and is explicitly false when that status has no fillable verification control.
Waiting, confirmed, and expired responses must not carry a stale flag.

## Interaction safeguards

- Serialize operations per account.
- Apply a conservative cooldown between browser actions.
- Detect login shells and platform risk-control pages before and after
  navigation or submission.
- Stop on a risk-control signal; do not automatically retry the same action.
- The workflow graph does not perform automatic comment/DM actions. Any
  remaining comment/DM browser action is an explicit operator/tool action.
- Automatic post-login and scheduled creator-statistics syncs are list-only
  (`force_light=True`); per-note detail enrichment requires an explicit
  configuration or manual request.
- Keep creator-statistics collection on Creator Center. Overview, list, and
  Creator Center detail metric capture are allowed; public note pages are
  permanently forbidden for every sync mode. The legacy `body_filter`,
  `CREATOR_STATS_MAX_BODY_VISITS`, `CREATOR_STATS_BODY_LOOKBACK_DAYS`, and
  `CREATOR_STATS_BODY_EMPTY_CIRCUIT` inputs are compatibility-only no-ops and
  must never lead to `www.xiaohongshu.com/explore/<note>` navigation.
- Preserve `body_text` already supplied by a Creator Center response; do not
  enrich it by opening the public main site.

## Profile lifecycle safety

- Launcher lifecycle operations for one bound profile use an OS-level flock; never launch or stop the same profile concurrently from separate processes.
- `reap` may stop only an old profile with no active CDP client; if socket inspection fails, it must fail closed and skip the profile.
- Cache cleanup is dry-run by default, runs only while the profile is stopped, and may remove only an explicit cache-directory allowlist; login databases and symlinks are protected.

## Testing boundary

Tests should assert that CDP is used, `chromium.launch` is not used by
engagement, existing persistent contexts are not replaced, and risk pages
produce a blocked result without a follow-up navigation. Creator-statistics
tests must also assert that positive or mutated legacy body caps never produce
an `/explore/<note>` visit while Creator Center detail metrics remain captured.
