# Research: CDP per-profile — multiple isolated Chrome instances for multi-account publishing

- **Query**: How to run multiple isolated Chrome instances each with its own user-data-dir and CDP remote-debugging-port, for a Playwright-based publisher that needs per-account login state.
- **Scope**: mixed (internal codebase + external Playwright/Chrome docs)
- **Date**: 2026-07-03

## Summary (answer to Q1 first, since it drives everything)

`connect_over_cdp(endpoint)` is the right Playwright API for "connect to an already-running Chrome bound to a specific profile". `launch_persistent_context(user_data_dir)` is a *different* lifecycle model — it spawns a fresh Chrome owned by the Playwright process and closes it when the context closes. The repo already uses `connect_over_cdp` (single global endpoint) and should keep that model, extending it to per-account endpoints. Do **not** mix the two for the same Chrome process (Playwright forbids two instances on the same user-data-dir, and `launch_persistent_context` + an externally launched Chrome on the same dir will collide on the SingletonLock).

## Findings

### Files Found (current state of the repo)

| File Path | Description |
|---|---|
| `backend/services/xhs_publisher.py:96-116` | `_ensure_browser` — `connect_over_cdp(self.cdp_endpoint)` to one global Chrome; `else` branch `launch()` is the non-CDP fallback |
| `backend/services/xhs_publisher.py:118-158` | `_ensure_page` CDP branch (line 122-129): uses `browser.contexts[0]` (the profile's own login state), deliberately skips cookie/stealth injection |
| `backend/services/xhs_publisher.py:76-94` | `XHSPublisher.__init__(cookie, headless, cookie_storage_path, slow_mo, cdp_endpoint)` — single endpoint, no user_data_dir/port concept |
| `backend/agents/publisher.py:60-74` | `_resolve_cdp_endpoint(settings)` — reads `settings.platform.cdp_endpoint` or `XHS_CDP_ENDPOINT` env, falls back to probing `host.containers.internal:9223` |
| `backend/agents/publisher.py:180-200` | `run_publish` — resolves selected account's cookie via `get_account_cookie(account_id)`, then builds `XHSClient(cdp_endpoint=_resolve_cdp_endpoint(settings))` with the GLOBAL endpoint (the bug: account cookie is fetched but CDP still points at global Chrome) |
| `backend/config/settings.py:34-46` | `XHSPlatformSettings` — `cdp_endpoint: str = ""` (single global field), `headless`, `use_browser`, `cookie`, `user_id` |
| `backend/db/accounts.py:18-25` | `AccountRow` — `id, name, is_active, created_at, updated_at`. NO profile/port fields exist yet |
| `backend/db/accounts.py:286-294` | `get_account_cookie(account_id)` — returns `(cookie, user_id)` tuple from credentials table; the only per-account data available to the publisher today |
| `backend/services/xhs_client.py:272-298` | `XHSClient.__init__(cookie, user_id, use_browser, headless, cdp_endpoint)` — passes `cdp_endpoint` straight through to `XHSPublisher` at line 514 |
| `.chrome-profile/` | The single existing user-data-dir for the常驻 Chrome (JameryW's login state). Not managed by deploy.sh; manually launched. Contains `Default/` profile dir, `SingletonLock`-style lock files would live here |
| `verify_cdp_publish.py` / `probe_submit_*.py` | Ad-hoc scripts that hardcode `http://127.0.0.1:9222` and `connect_over_cdp`, then manually inject cookies into `browser.contexts[0]`. Confirm the current single-endpoint workflow |
| `tests/unit/services/test_xhs_publisher.py:234-252` | `test_cdp_endpoint_stored` — locks that `cdp_endpoint` is stored as instance attr; new per-account logic must keep this contract |
| `tests/unit/agents/test_run_publish.py:63-72` | `test_resolve_cdp_endpoint_uses_env_when_settings_attr_missing` — locks `_resolve_cdp_endpoint` env fallback behavior |

### Q1 — `connect_over_cdp` vs `launch_persistent_context`

Source: Playwright Python API reference (`https://playwright.dev/python/docs/api/class-browsertype`).

**`browser_type.connect_over_cdp(endpoint_url, *, ...)`** (Added v1.9):
> This method attaches Playwright to an existing browser instance using the Chrome DevTools Protocol. The default browser context is accessible via `browser.contexts`. … Connecting over the Chrome DevTools Protocol is only supported for Chromium-based browsers. … This connection is significantly lower fidelity than the Playwright protocol connection via `browser_type.connect()`. If you are experiencing issues or attempting to use advanced functionality, you probably want to use `browser_type.connect()`.

- Accepts an http url (`http://localhost:9222/`) or a ws url (`ws://127.0.0.1:9222/devtools/browser/<guid>`).
- Returns a `Browser` proxy; `browser.contexts[0]` is the *default* context = the profile the Chrome was launched with. Login cookies live there.
- Notable kwargs: `no_defaults` (v1.60, don't override accept_downloads/focus/media emulation — useful when attaching to a daily-driver browser), `is_local` (v1.58, enable FS-based optimizations when Playwright shares the host with the CDP server), `timeout` (default 30000ms).

**`browser_type.launch_persistent_context(user_data_dir, *, ...)`** (Added before v1.9):
> Returns the persistent browser context instance. Launches browser that uses persistent storage located at `user_data_dir` and returns the only context. Closing this context will automatically close the browser. … **Note that browsers do not allow launching multiple instances with the same User Data Directory.**

- Playwright *owns* the Chrome process. `context.close()` kills it. Login state persists in `user_data_dir` across runs, but the browser is not "always on".
- Conflicts with an externally-launched Chrome on the same dir (SingletonLock collision — see Q4).

**Verdict for this repo:** Keep `connect_over_cdp`. The publisher's design (常驻 real Chrome, profile自带登录态, no stealth/cookie injection — see `xhs_publisher.py:88-92` comment) is fundamentally the CDP-attach model. Switching to `launch_persistent_context` would (a) make Playwright own the Chrome lifecycle (kills the "always-on daemon" goal), (b) re-introduce the `--enable-automation`/CDP fingerprint that XHS shield detects (the whole reason the repo moved to real-Chrome-CDP), and (c) conflict if a user also has that Chrome open for manual login. The fix is: **launch N real Chromes (one per account) each with its own `--user-data-dir` + `--remote-debugging-port`, then `connect_over_cdp` to the per-account port**.

### Q2 — Launching Chrome with `--user-data-dir` + `--remote-debugging-port`

Source: Chromium user_data_dir docs (`https://chromium.googlesource.com/chromium/src/+/master/docs/user_data_dir.md`) + Playwright's reference to it.

Chrome command line:
```
google-chrome \
  --user-data-dir=/test/xhs/.chrome-profiles/<account_id> \
  --remote-debugging-port=<port> \
  --remote-debugging-address=127.0.0.1 \
  --no-first-run --no-default-browser-check \
  (headed for扫码登录; drop --headless once logged in if desired)
```

Key facts from the docs:
- **user_data_dir is the PARENT of the "Profile Path"** seen at `chrome://version`. Each profile (e.g. `Default`) is a subdirectory. So `--user-data-dir=/test/xhs/.chrome-profiles/acct-A` gives that Chrome its own `Default/`, cookies, localStorage, the lot. `chrome://version` → "Profile Path" = `…/acct-A/Default`; "User Data Dir" = `…/acct-A`.
- **`--remote-debugging-port=<port>`** opens the CDP HTTP server on that port. `--remote-debugging-address=127.0.0.1` binds to loopback (default is `127.0.0.1` on recent Chrome; explicitly setting avoids binding to `0.0.0.0` on older builds). The JSON list of targets is at `http://127.0.0.1:<port>/json/version` (gives `webSocketDebuggerUrl`), and `http://127.0.0.1:<port>/json` lists pages. Playwright's `connect_over_cdp(f"http://127.0.0.1:{port}")` works against this.
- **One port per Chrome process.** Two Chromes cannot share a port (second launch fails with "cannot listen on port"). Each account → distinct port.

**Port allocation conventions:**
- Base range + offset. Common pattern: `9222 + index` (e.g. account 0 → 9222, account 1 → 9223). The repo already probes `9223` in `_resolve_cdp_endpoint` (`publisher.py:68`), suggesting 9222 is the existing single-account port — a per-account scheme should avoid 9222 collisions or treat the global account as index 0.
- Better: persist the chosen port in the accounts table (e.g. `cdp_port INTEGER`) so it's stable across restarts rather than re-derived. Derived schemes (hash of account_id) risk collisions and make "is this port in use" checks harder.
- Free-port detection: bind a socket to `('127.0.0.1', port)` with `SO_REUSEADDR=0`; if it succeeds, port is free. But for persistent daemons you want STABLE ports, not random free ones — so prefer fixed allocation from a small range and store the assignment.

**"Is this Chrome already running" detection:**
1. **HTTP probe** the CDP endpoint: `GET http://127.0.0.1:<port>/json/version` — if it returns JSON with `Browser` + `webSocketDebuggerUrl`, Chrome is up on that port. This is what `_resolve_cdp_endpoint`'s socket probe (`publisher.py:68-73`) approximates; replace the raw socket connect with an HTTP GET for accuracy (a port can be open but Chrome not ready, or be a different service).
2. **SingletonLock / SingletonCookie / SingletonSocket files** in the user_data_dir. Chrome writes `user_data_dir/SingletonLock` (a symlink on Linux/Mac whose target is `hostname-<pid>`), `SingletonCookie`, and `SingletonSocket`. Presence of a *live* SingletonLock means a Chrome is running on that dir. Stale locks (Chrome killed without cleanup) linger and must be handled (see Q4).
3. **pgrep / pidfile**: simplest robust approach — write a pidfile (`<user_data_dir>/chrome.pid`) at launch, check `os.kill(pid, 0)` to see if alive. Combined with the HTTP probe this covers crash-recovery (pidfile stale but Chrome actually died → port probe fails → relaunch).

### Q3 — OSS patterns for managing N persistent Chrome profiles + CDP endpoints

Common patterns observed in bot/scraper frameworks (BotD, puppeteer-cluster, selenium-grid session queues, browserless, adblock-fingerprint farms):

| Pattern | Lifecycle | Pros | Cons |
|---|---|---|---|
| **Always-on daemons** (one Chrome per account, launched at boot/supervisor, never killed) | Long-lived | Zero startup latency on publish; login state always warm; matches this repo's "常驻 real Chrome" design | N Chrome processes eat RAM (~200-400MB each idle); need a process supervisor (systemd/pm2/supervisord) to restart on crash |
| **Spawn-on-demand** (launch Chrome right before publish, kill after) | Short-lived | Low resource use when idle; clean slate each time | 5-15s startup per publish; must re-warm login (cookies persist in user_data_dir so login survives, but page/nav warmup doesn't); harder to keep a扫码 login session alive |
| **Pool with warm pool size** (browserless-style) | Hybrid | Scales to many accounts with few concurrent Chromes | Complex; overkill for ≤10 accounts |

For this repo ( handful of XHS accounts, publish is bursty not constant,扫码 login is a one-time manual step): **always-on daemons managed by a supervisor** fits best. The existing `.chrome-profile/` Chrome is already an always-on daemon — just generalize to N. Concretely:
- A small launcher script (`scripts/chrome-profiles.sh` or a Python `backend/services/chrome_launcher.py`) that reads the accounts table (or a config file mapping account_id → user_data_dir + port) and ensures each Chrome is up: HTTP-probe the port; if down, `google-chrome --user-data-dir=… --remote-debugging-port=… &` and write a pidfile. Run on boot / before publish.
- `run_publish` resolves the selected account's CDP port (from accounts table) and passes `cdp_endpoint=http://127.0.0.1:<port>` to `XHSClient`/`XHSPublisher` instead of the global `_resolve_cdp_endpoint(settings)`.

Lifecycle choice note: the PRD lists "常驻 vs 按需启停" as an open question. The repo's existing comment at `xhs_publisher.py:88-92` ("连接常驻真实 Chrome") and the fact that扫码 login is manual/one-time strongly favor always-on. Spawn-on-demand would require re-扫码 or cookie-injection-on-launch, which the CDP-attach model deliberately avoids.

### Q4 — Gotchas

**Profile lock (SingletonLock):**
- Chrome writes `SingletonLock`, `SingletonCookie`, `SingletonSocket` into the user_data_dir to enforce single-instance-per-dir. On Linux `SingletonLock` is a symlink whose target is `<hostname>-<pid>`.
- Two Chromes on the SAME user_data_dir: the second launch detects the lock and either (a) exits, or (b) on some configs, focuses the existing window and exits. Either way, no second instance. This is exactly the Playwright note: "browsers do not allow launching multiple instances with the same User Data Directory".
- **Stale locks**: if Chrome was `kill -9`'d or crashed, the lock files remain. Next launch sees them and may refuse to start, OR (newer Chrome) detects the PID is dead and proceeds. To be safe, a launcher should: HTTP-probe the port first; if the port is dead AND the SingletonLock's target PID is not alive, remove `SingletonLock`/`SingletonCookie`/`SingletonSocket` before relaunching. Never blindly delete locks while a Chrome might be running (corrupts the profile).
- **Cross-process profile access**: connecting via CDP (`connect_over_cdp`) does NOT take the SingletonLock — it's a DevTools client, not a second browser instance. So Playwright attaching to a running Chrome via CDP is safe and is the canonical way to share a profile. The danger is only when *launching* a second Chrome on the same dir.

**Cookies / login state persistence:**
- Login state (cookies, localStorage, IndexedDB, service-worker registrations) lives in `<user_data_dir>/Default/`. It persists across Chrome restarts as long as the dir is intact. This is why the repo can扫码 once and reuse the session.
- **Do not inject cookies via `context.add_cookies()` when using CDP attach** — the repo already learned this (`xhs_publisher.py:122-129` comment): the profile's own cookies are authoritative; injecting DB cookies into a real-Chrome context is an automation fingerprint XHS shield flags. The per-account CDP model makes this cleaner: each Chrome IS logged in as its account, so no cookie injection needed at all. The `get_account_cookie` lookup in `run_publish` becomes a fallback/verification only, not the source of truth.
- Cookie expiry: XHS session cookies expire. With per-profile Chrome, the account's Chrome shows the login page when the session dies — operator re-扫码 in THAT Chrome's window. The publisher detects this via `_check_login` (`xhs_publisher.py:216-227`) returning False (URL contains "login"). Recovery = manual re-scan in the bound Chrome, not cookie refresh.

**Headless vs headed for扫码登录:**
- 扫码登录 (QR scan login) REQUIRES a visible window — the QR code is rendered in the DOM and the user scans it with the XHS mobile app. `--headless=new` (or old) renders the page but the user cannot interact with a headless window's QR; some login flows also detect headless and block.
- Convention: launch each account's Chrome **headed** at least for the initial login. Once logged in, the session persists in user_data_dir; you can restart the Chrome headless afterward if resource matters. But for a multi-account publisher where the operator wants to re-scan anytime, keeping all account Chromes headed (even if minimized) is simpler. The repo's `_ensure_browser` `headless` flag (`xhs_publisher.py:79`) currently defaults True — but that only affects the non-CDP `launch()` branch; the CDP branch inherits the Chrome's own headed/headless state, so the launcher decides.
- Real Chrome (not chromium) for反爬: the PRD notes this. `google-chrome` (branded) has a different fingerprint baseline than `chromium`/`chromium-browser`. The launcher must use the real Chrome binary path (e.g. `/usr/bin/google-chrome` or `/opt/google/chrome/chrome`), not the Playwright-bundled chromium. `connect_over_cdp` does not care which binary launched the Chrome — it just attaches.

### Mapping onto repo constraints

| Constraint | Implication |
|---|---|
| Python backend, Playwright async API | Keep `connect_over_cdp`; the per-account endpoint is just a different URL string per account. No Playwright API change needed. |
| `XHSPublisher._ensure_browser` does `connect_over_cdp(self.cdp_endpoint)` to one global Chrome | Change `cdp_endpoint` from a global to a per-account value. `run_publish` already has `publish_account_id` (`publisher.py:170`); look up that account's bound port and pass `f"http://127.0.0.1:{port}"` instead of `_resolve_cdp_endpoint(settings)`. The publisher code itself barely changes. |
| accounts table has no profile field | Add `chrome_profile_path TEXT` + `cdp_port INTEGER` columns (migration in `backend/db/accounts.py` alongside `_CREATE_ACCOUNTS_SQL`). `AccountRow` gains the fields. `get_account_cookie` could grow a sibling `get_account_cdp_endpoint(account_id)` or return a richer struct. Derived scheme (`/test/xhs/.chrome-profiles/<account_id>` + hash-based port) is an alternative but stored fields are more robust (stable ports, operator-overridable path). |
| Real Chrome preferred for反爬 | Launcher uses `google-chrome` binary, not Playwright's chromium. `connect_over_cdp` is binary-agnostic. |
| `.chrome-profile/` is the existing single profile | Keep it as the "default"/global account's dir for backward compat (the PRD's "不破坏现有单账号 CDP 模式" criterion). New accounts get `.chrome-profiles/<account_id>/`. The global `_resolve_cdp_endpoint` still works as fallback when an account has no bound port. |
| Container vs host | `_resolve_cdp_endpoint` already handles `host.containers.internal:9223` (`publisher.py:68`) — Chrome runs on the host, backend in container. Per-account ports must be reachable from the container; `--remote-debugging-address=0.0.0.0` (or the host bridge IP) + container-side `host.containers.internal:<port>` per account. This is a networking concern, not a Playwright one. |

### Related Specs

No `.trellis/spec/` documents directly cover CDP or browser profile management (the spec tree was not searched exhaustively; a `find .trellis/spec -name '*.md'` would confirm). The PRD at `.trellis/tasks/07-03-cdp-profile-chrome-user-data-dir/prd.md` is the authoritative task spec and lists the open questions this research addresses.

## External References

- [Playwright Python — BrowserType (connect_over_cdp, launch_persistent_context)](https://playwright.dev/python/docs/api/class-browsertype) — confirms `connect_over_cdp` attaches to an existing CDP endpoint (returns Browser; `browser.contexts[0]` is the default profile context), and that `launch_persistent_context` owns the Chrome lifecycle with the hard constraint "browsers do not allow launching multiple instances with the same User Data Directory". No version constraint beyond v1.9+; the repo's `playwright-stealth` integration implies a recent Playwright.
- [Chromium — user_data_dir.md](https://chromium.googlesource.com/chromium/src/+/master/docs/user_data_dir.md) — authoritative on user-data-dir vs profile-path (user_data_dir is the PARENT of "Profile Path" at `chrome://version`), default locations, and that `SingletonLock`/`SingletonCookie`/`SingletonSocket` enforce single-instance-per-dir.
- [Playwright Python — BrowserType.connect_over_cdp (anchor)](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp) — `endpoint_url` accepts `http://localhost:9222/` or `ws://…/devtools/browser/<guid>`; kwargs `no_defaults` (v1.60), `is_local` (v1.58), `timeout` (default 30000ms).
- [Chrome DevTools Protocol — HTTP endpoints](https://chromedevtools.github.io/devtools-protocol/) — `GET /json/version` and `GET /json` on the debugging port list targets; used for "is Chrome up" detection. (Standard, stable since Chrome 64+.)

## Caveats / Not Found

- **No `.trellis/spec/` search was performed** — if there is an existing spec doc on browser/publisher architecture it was not consulted. A `find .trellis/spec -name '*.md' | xargs grep -l -i chrome` would catch it before implementation.
- **OSS framework citations (Q3) are from general knowledge, not freshly-fetched sources** — the exa MCP tools were unavailable in this environment (not in the tool list), so specific GitHub repos (puppeteer-cluster, browserless, etc.) are referenced by their well-documented patterns rather than quoted. The patterns are stable and widely documented, but a implementer wanting exact code snippets should fetch those repos directly.
- **Chrome binary path not verified on this host** — `which google-chrome` / `which google-chrome-stable` should be run to confirm the branded Chrome is installed before the launcher is written. If only `chromium` is present, the反爬 rationale may need re-evaluation.
- **Container networking for per-account ports not fully resolved** — the host-vs-container reachability for N distinct debugging ports (9222, 9223, …) from inside the backend container needs a concrete test. The existing 9223 probe works, so the pattern extends, but `--remote-debugging-address` and container `--network` config must allow each port.
- **Port-allocation collision risk** — `9222 + index` can collide with other services on the host (e.g. 9222 is a common CDP default). A stored `cdp_port` column lets the operator override; a launcher should fail loud (not silently pick a random port) if the configured port is taken by a non-Chrome process.
