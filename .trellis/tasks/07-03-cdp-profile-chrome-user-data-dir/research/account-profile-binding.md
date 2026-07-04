# Research: Per-Account → Chrome-Profile Binding

- **Query**: How to persist a per-account → Chrome-profile binding (user-data-dir + CDP port) in a Python/LangGraph/FastAPI + Postgres project where accounts already exist and credentials are encrypted.
- **Scope**: internal (repo conventions) + design trade-offs
- **Date**: 2026-07-03

## Findings

### Files Inspected

| File Path | Relevance |
|---|---|
| `backend/db/accounts.py` | `accounts` table DDL, `AccountRow`, `ensure_tables()`, `update_account(**fields)` dynamic-set helper, `get_account_cookie()` |
| `backend/db/evaluator_config.py` | Migration convention: `ensure_tables()` + `ALTER TABLE … ADD COLUMN IF NOT EXISTS` (`_ADD_SNAPSHOT_COL_SQL`) |
| `backend/db/system_config.py` | Global key/value encrypted store; whitelisted `SYSTEM_KEYS`; `bootstrap_from_environ()` overrides `os.environ` at startup |
| `backend/db/__init__.py` | Re-exports each module's `ensure_tables as ensure_<x>_tables` |
| `backend/api/app.py` (lines 30–95) | Startup lifespan: `init_pool()` → parallel `ensure_tables()` gather → bootstrap steps |
| `backend/config/settings.py` | `XHSPlatformSettings` (`env_prefix="XHS_"`): `cookie`, `user_id`, `use_browser`, `headless`, `cdp_endpoint` |
| `backend/agents/publisher.py` | `run_publish()` — reads `publish_options.account_id`, resolves cookie via `get_account_cookie`, builds `XHSClient(cdp_endpoint=_resolve_cdp_endpoint(settings))` |
| `backend/services/xhs_client.py` | `XHSClient.__init__(cookie, user_id, use_browser, headless, cdp_endpoint)`; `_ensure_publisher()` builds `XHSPublisher(cookie, headless, cdp_endpoint)` |
| `backend/services/xhs_publisher.py` | `XHSPublisher.__init__(cookie, headless, cookie_storage_path, slow_mo, cdp_endpoint)`; `_ensure_browser()` does `connect_over_cdp` if `cdp_endpoint` else `launch` |
| `backend/api/routes/accounts.py` (lines 104–134) | `update_account` route — uses dynamic `fields` dict → `db_update(account_id, **fields)` |
| `.trellis/spec/backend/database-guidelines.md` | DB conventions; "Account-Scoped XHS Credentials" scenario already documents the `get_account_cookie(account_id)` pattern |
| `probe_submit_simple.py`, `verify_cdp_publish.py` | Scratch probes hardcoding `cdp_endpoint="http://127.0.0.1:9222"` + `ACCOUNT_ID` — confirm the single-shared-Chrome limitation being fixed |

### 1. Schema Options

**Current `accounts` DDL** (`backend/db/accounts.py:62-70`):
```sql
CREATE TABLE IF NOT EXISTS accounts (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT ''
);
```
No `chrome_profile_path` / `cdp_port` columns exist today (confirmed by grep — zero hits).

**Option A — Add columns to `accounts`** (`chrome_profile_path TEXT`, `cdp_port INT`)
- Pro: One table, one read (`get_account` already returns an `AccountRow`); `update_account(**fields)` dynamic-set accepts new keys with zero code change; aligns with how `is_active`/`name` are already per-account attributes.
- Pro: `AccountRow` dataclass gains two optional fields (`=""`/`0` defaults) — backward compatible.
- Con: Mixes browser-launch config into the identity table (minor — but `accounts` already mixes `is_active` which is runtime state, so the precedent is set).
- Migration cost: One `ALTER TABLE … ADD COLUMN IF NOT EXISTS` line in `ensure_tables()` (see §2).

**Option B — New join table `account_chrome_profiles(account_id PK FK→accounts, profile_path, cdp_port, updated_at)`**
- Pro: Clean separation; 1:1 today but leaves room for 1:N (multiple browser profiles per account) without another migration.
- Con: Extra join on every publish; new module (`backend/db/account_chrome_profiles.py`), new `ensure_tables` to wire into `app.py` gather, new CRUD to write + test. The repo has no existing 1:1 join table — `account_credentials` is the only child table and it's 1:N by design.
- Con: More surface area for the same data shape.

**Option C — Derive by convention** (`/test/xhs/.chrome-profiles/<account_id>`, port = `XHS_CDP_BASE_PORT + row_number`)
- Pro: Zero schema change; profile path is deterministic from `account_id`.
- Pro: Matches the CDP-mode design intent in `xhs_publisher.py:88-92` — "连接常驻真实 Chrome（用户扫码登录的持久 profile）" — the profile *is* the login state, so a stable per-account dir is the natural unit.
- Con: Port allocation by `row_number` requires a stable ordering (the `list_accounts()` ORDER BY `is_active DESC, created_at ASC` is stable but `created_at` ties are possible); a deleted account leaves a port gap; can't override per-env without re-deriving.
- Con: No DB record of which port → must be recomputed each publish, and concurrent publishes for different accounts need distinct Chrome instances on distinct ports (the convention must be enforced at Chrome-launch time, outside the app).

**Recommendation grounding (descriptive, not prescriptive):** The repo's established pattern for per-account attributes is columns on `accounts` (Option A) — `is_active`, `name`, `created_at` all live there, and `update_account(**fields)` + the `UpdateAccountRequest` route already extend to new fields with trivial changes. The evaluator_config `account_id IS NULL = global default` override pattern (lines 13, 158-194) is a closer analog if per-account *override of a global default* is desired (e.g. most accounts share one Chrome, one account has its own profile). For a pure "one profile per account, always" rule, columns on `accounts` are the lowest-friction match.

### 2. Migration Convention (follow this exactly)

There is **no migration framework** (no Alembic, no squashed migrations). The convention is **`ensure_tables()`-style create-if-absent + idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS`**, run at app startup in `app.py` lifespan.

**Pattern source** (`backend/db/evaluator_config.py:102-135`):
```python
# Idempotent column add for tables created before content_snapshot existed.
# CREATE TABLE IF NOT EXISTS won't add columns to an existing table, so ALTER
# handles upgrades. Safe on new tables (column already present → no-op).
_ADD_SNAPSHOT_COL_SQL = (
    "ALTER TABLE evaluator_samples ADD COLUMN IF NOT EXISTS content_snapshot JSONB"
)

async def ensure_tables() -> None:
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_CONFIG_SQL)
        await conn.execute(_CREATE_SAMPLES_SQL)
        await conn.execute(_ADD_SNAPSHOT_COL_SQL)  # upgrade pre-existing tables
        await conn.execute(_CREATE_SAMPLES_INDEX_SQL)
        ...
```

**To follow the convention for Option A**, add to `backend/db/accounts.py`:
```python
_ADD_CHROME_PROFILE_COL_SQL = (
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS chrome_profile_path TEXT NOT NULL DEFAULT ''"
)
_ADD_CDP_PORT_COL_SQL = (
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS cdp_port INTEGER NOT NULL DEFAULT 0"
)

async def ensure_tables() -> None:
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_ACCOUNTS_SQL)
        await conn.execute(_CREATE_CREDENTIALS_SQL)
        await conn.execute(_CREATE_INDEX_SQL)
        await conn.execute(_ADD_CHROME_PROFILE_COL_SQL)
        await conn.execute(_ADD_CDP_PORT_COL_SQL)
```
- `ensure_tables()` is already called in the `app.py:68-76` parallel gather — no startup wiring change needed.
- `AccountRow` gains `chrome_profile_path: str = ""` and `cdp_port: int = 0`; `_account_from_dict` reads them with `.get(..., default)`.
- `update_account(**fields)` already builds the SET clause from keys — passing `chrome_profile_path=...` works with no code change (route + request model need the field added).

**Important caveat from MEMORY.md** (`store-vectors-dim-recreate-not-truncate.md`, `system-config-overrides-environ.md`): when adding columns, `ALTER TABLE ADD COLUMN IF NOT EXISTS` is the safe idempotent path — do NOT assume `CREATE TABLE IF NOT EXISTS` adds columns to a pre-existing table (it does not). The evaluator_config comment at line 103-104 states this explicitly.

### 3. Where the Binding Should Be Resolved

**The seam is `run_publish()` in `backend/agents/publisher.py` (agent layer), NOT the service layer.**

Current flow (`publisher.py:116-194`):
1. `run_publish` reads `publish_options.account_id` (line 127).
2. If set, calls `get_account_cookie(account_id)` → `(cookie, user_id)` (line 136).
3. Builds `XHSClient(cookie=..., user_id=..., use_browser=True, headless=..., cdp_endpoint=_resolve_cdp_endpoint(settings))` (lines 188-194).
4. `XHSClient._ensure_publisher()` (service layer, `xhs_client.py:506-516`) lazily builds `XHSPublisher(cookie, headless, cdp_endpoint)`.

**Why agent layer is the right resolution point:**
- `run_publish` already does the account_id → cookie resolution (line 133-136). Adding account_id → profile/port resolution there is the same pattern, one more `await get_account(account_id)` call (which `run_publish` already makes at line 163 for the `is_active` early-fail check).
- The service layer (`XHSClient` / `XHSPublisher`) is intentionally account-agnostic — it takes raw `cookie`/`cdp_endpoint` strings. Pushing account-awareness into `XHSPublisher.__init__` would couple the Playwright layer to the accounts DB, breaking the lazy-import boundary (`xhs_publisher.py` only imports `playwright` + stdlib; `xhs_client.py` imports `xhs_publisher` lazily inside `_ensure_publisher`).
- `_resolve_cdp_endpoint(settings)` (lines 60-75) is the existing precedent for "agent layer computes the endpoint string, passes it down." A sibling `_resolve_chrome_profile(settings, account_id)` fits the same shape.

**Proposed seam (descriptive):**
- `XHSPublisher.__init__` gains `user_data_dir: str = ""` and/or `cdp_port: int = 0` params (mirroring how `cdp_endpoint` was added).
- `XHSClient.__init__` gains the same, threads them into `_ensure_publisher()`.
- `run_publish` resolves `account.chrome_profile_path` + `account.cdp_port` (or derives them by convention) and passes them to `XHSClient`.
- `XHSPublisher._ensure_browser()` uses `user_data_dir` when launching (non-CDP path, line 107-115) — the CDP path (line 102-105) already implies the Chrome instance has its own profile, so `user_data_dir` is only for the launch fallback / for launching a per-account Chrome on a per-account port.

**Note on CDP vs launch:** In CDP mode (`xhs_publisher.py:102-105`), `connect_over_cdp` attaches to an *already-running* Chrome whose `--user-data-dir` was set at Chrome launch time (outside the app). So `chrome_profile_path` + `cdp_port` are really "how to find/launch the right Chrome for this account," not "Playwright launch args." The app would either (a) launch a per-account Chrome `chrome --user-data-dir=<path> --remote-debugging-port=<port>` as a subprocess, then `connect_over_cdp` to it, or (b) assume an external orchestrator already launched it. The binding in DB is the source of truth for (a).

### 4. Settings / Env for Base Profile Dir + Base Port

**Existing precedent** — `XHSPlatformSettings` (`backend/config/settings.py:34-46`):
```python
class XHSPlatformSettings(BaseSettings):
    cookie: str = ""
    user_id: str = ""
    api_base: str = "https://edith.xiaohongshu.com"
    use_browser: bool = False
    headless: bool = True
    cdp_endpoint: str = ""   # ← XHS_CDP_ENDPOINT env
    model_config = {"env_prefix": "XHS_", "env_file": ".env", "extra": "ignore"}
```
- `env_prefix="XHS_"` means field `cdp_endpoint` → env var `XHS_CDP_ENDPOINT`. Confirmed used in `publisher.py:64`: `getattr(platform, "cdp_endpoint", "") or os.getenv("XHS_CDP_ENDPOINT", "")`.
- `_resolve_cdp_endpoint()` (publisher.py:60-75) reads `settings.platform.cdp_endpoint` first, falls back to `XHS_CDP_ENDPOINT` env, then probes `host.containers.internal:9223` (container default).

**To mirror for the new binding**, add to `XHSPlatformSettings`:
```python
chrome_profiles_dir: str = ""   # XHS_CHROME_PROFILES_DIR — base dir for per-account profiles
cdp_base_port: int = 9222       # XHS_CDP_BASE_PORT — base port, account N = base + N
```
- `env_prefix="XHS_"` auto-maps these to `XHS_CHROME_PROFILES_DIR` and `XHS_CDP_BASE_PORT`.
- Accessed as `settings.platform.chrome_profiles_dir` / `settings.platform.cdp_base_port` — same shape as `cdp_endpoint`.
- **Caveat (MEMORY.md `system-config-overrides-environ.md`):** `system_config` table overrides `os.environ` for whitelisted keys at startup (`activate_system_config()` in `app.py:95`). If `XHS_CHROME_PROFILES_DIR` / `XHS_CDP_BASE_PORT` should be DB-editable at runtime (like `XHS_EMBED_MODEL`), they must be added to `SYSTEM_KEYS` in `backend/db/system_config.py:22` — but these are per-deployment infra paths, not secrets, so they likely belong in `.env` + `XHSPlatformSettings` only (like `cdp_endpoint` is today: it is NOT in `SYSTEM_KEYS`). Following the `cdp_endpoint` precedent keeps it env-only.

**Convention derivation (if Option C is chosen):**
- `profile_path = f"{settings.platform.chrome_profiles_dir}/{account_id}"`
- `cdp_port = settings.platform.cdp_base_port + account_index` (where `account_index` is the 0-based position in `list_accounts()` ordering — but this is fragile; a stored `cdp_port` column per account is more robust).

### Related Specs

- `.trellis/spec/backend/database-guidelines.md` — "Account-Scoped XHS Credentials" scenario (lines 212-236) documents the `get_account_cookie(account_id)` pattern and the rule "Do not read account credentials directly with ad hoc SQL from agents/tools." A Chrome-profile binding should follow the same `get_account()`-via-`backend.db.accounts` rule, not ad hoc SQL.
- `.trellis/spec/backend/database-guidelines.md` — "Graceful degradation when DB is unavailable" (lines 178-182): all DB ops must degrade gracefully (`is_pool_ready()` check, catch + log). The profile/port resolution in `run_publish` must handle `get_account()` returning `None` (it already does, line 164).

## Caveats / Not Found

- **No existing `chrome_profile_path` / `cdp_port` / `user_data_dir` columns or fields anywhere** in `backend/` (grep returned zero hits). This is greenfield.
- **`.env.example` has no CDP/Chrome/profile entries** — only `XHS_COOKIE`, `XHS_USER_ID`, `XHS_USE_BROWSER`, `POSTGRES_URI`. The `XHS_CDP_ENDPOINT` env var is documented only in the `XHSPlatformSettings` field comment (`settings.py:42-44`) and used in `publisher.py`. New env vars should be added to `.env.example` for discoverability.
- **The probes (`probe_submit_simple.py`, `verify_cdp_publish.py`) hardcode `http://127.0.0.1:9222` and a single `ACCOUNT_ID`** — they confirm the current limitation (one shared Chrome for all accounts) but don't establish a per-account convention. They are untracked scratch files, not part of the codebase contract.
- **CDP mode vs launch mode:** In CDP mode the Chrome process is launched externally with its own `--user-data-dir`; the app only `connect_over_cdp`s. So `chrome_profile_path` stored in DB is meaningful for an app-managed Chrome launcher (subprocess), but in the current CDP-connect-only flow it's informational unless a launcher is added. The `cdp_port` is the actually-load-bearing field for `connect_over_cdp` (the endpoint URL).
- **No Alembic / migration versioning** — the `ensure_tables()` + `ALTER … ADD COLUMN IF NOT EXISTS` pattern is the only mechanism. Rollback is manual (no down-migration). This is acceptable for this repo's deployment model (single-instance, `deploy.sh` rebuilds) but means a column drop would require a manual `ALTER TABLE … DROP COLUMN`.
