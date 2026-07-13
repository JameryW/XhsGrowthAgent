"""Account CRUD — multi-tenant XHS account management."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from backend.db.crypto import decrypt_value, mask_value
from backend.db.pool import get_pool

logger = logging.getLogger("xhs_growth.db.accounts")

# ── Data models ──


@dataclass
class AccountRow:
    id: str
    name: str
    is_active: bool = False
    created_at: str = ""
    updated_at: str = ""
    # Per-account Chrome profile binding (CDP multi-profile mode).
    # chrome_profile_path = user-data-dir for this account's dedicated Chrome;
    # cdp_port = the --remote-debugging-port that Chrome listens on.
    # Empty/0 means "no per-account binding → fallback to global CDP endpoint".
    chrome_profile_path: str = ""
    cdp_port: int = 0
    # Bound content niche (赛道): manual override or inferred from history notes
    niche: str = ""
    niche_source: str = ""  # manual | inferred | account_bound | ""


@dataclass
class CredentialRow:
    account_id: str
    key_name: str
    # encrypted_value stored as bytes in DB, but we keep decoded string in the dataclass
    _encrypted_bytes: bytes | None = None

    @property
    def value(self) -> str:
        if self._encrypted_bytes:
            return decrypt_value(self._encrypted_bytes)
        return ""

    @property
    def masked(self) -> str:
        v = self.value
        return mask_value(v) if v else ""


# ── Table creation ──

_CREATE_ACCOUNTS_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_CREDENTIALS_SQL = """
CREATE TABLE IF NOT EXISTS account_credentials (
    account_id      TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    key_name        TEXT NOT NULL,
    encrypted_value BYTEA NOT NULL,
    PRIMARY KEY (account_id, key_name)
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_accounts_active ON accounts (is_active);
"""

# Idempotent column adds for CDP multi-profile support.
# CREATE TABLE IF NOT EXISTS won't add columns to a pre-existing table, so ALTER
# handles upgrades. Safe on new tables (column already present → no-op).
# Same pattern as evaluator_config._ADD_SNAPSHOT_COL_SQL.
_ADD_CHROME_PROFILE_COL_SQL = (
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS chrome_profile_path TEXT NOT NULL DEFAULT ''"
)
_ADD_CDP_PORT_COL_SQL = (
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS cdp_port INTEGER NOT NULL DEFAULT 0"
)
_ADD_NICHE_COL_SQL = "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS niche TEXT NOT NULL DEFAULT ''"
_ADD_NICHE_SOURCE_COL_SQL = (
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS niche_source TEXT NOT NULL DEFAULT ''"
)


async def ensure_tables() -> None:
    """Create accounts + legacy credentials tables if they don't exist, and ensure
    the CDP multi-profile columns exist on pre-existing accounts tables."""
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_ACCOUNTS_SQL)
        await conn.execute(_CREATE_CREDENTIALS_SQL)
        await conn.execute(_CREATE_INDEX_SQL)
        await conn.execute(_ADD_CHROME_PROFILE_COL_SQL)
        await conn.execute(_ADD_CDP_PORT_COL_SQL)
        await conn.execute(_ADD_NICHE_COL_SQL)
        await conn.execute(_ADD_NICHE_SOURCE_COL_SQL)
    logger.info("accounts tables ensured")


# ── Account CRUD ──


async def create_account(name: str, is_active: bool = False) -> AccountRow:
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    id_ = str(uuid.uuid4())

    # Auto-allocate per-account Chrome profile binding (CDP multi-profile mode).
    # chrome_profile_path defaults to <chrome_profiles_dir>/<account_id> (empty
    # if the base dir isn't configured). cdp_port picks the first unoccupied
    # port starting at cdp_base_port+1, skipping ports already used by existing
    # accounts.
    from backend.config.settings import Settings

    settings = Settings()
    profiles_dir = getattr(settings.platform, "chrome_profiles_dir", "") or ""
    chrome_profile_path = f"{profiles_dir}/{id_}" if profiles_dir else ""
    cdp_port = await _allocate_cdp_port(settings)

    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO accounts
                (id, name, is_active, created_at, updated_at,
                 chrome_profile_path, cdp_port)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (id_, name, is_active, now, now, chrome_profile_path, cdp_port),
        )
    return AccountRow(
        id=id_,
        name=name,
        is_active=is_active,
        created_at=now,
        updated_at=now,
        chrome_profile_path=chrome_profile_path,
        cdp_port=cdp_port,
    )


async def _allocate_cdp_port(settings: Any) -> int:
    """Pick the first unoccupied CDP port starting at cdp_base_port+1.

    Skips ports already assigned to existing accounts. Returns 0 if the pool
    isn't ready (graceful degradation — account created without port binding,
    falls back to global CDP at publish time).
    """
    from backend.db.pool import is_pool_ready

    base_port = getattr(settings.platform, "cdp_base_port", 9222) or 9222
    if not is_pool_ready():
        return 0
    try:
        accounts = await list_accounts()
    except Exception as e:
        logger.warning("CDP port allocation: list_accounts failed, returning 0: %s", e)
        return 0
    used_ports = {a.cdp_port for a in accounts if a.cdp_port > 0}
    port = base_port + 1
    while port < base_port + 1000:  # sanity ceiling
        if port not in used_ports:
            return port
        port += 1
    return 0


async def get_account(account_id: str) -> AccountRow | None:
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM accounts WHERE id = %s", (account_id,))
            row = await cur.fetchone()
    if row is None:
        return None
    return _account_from_dict(row)


async def list_accounts() -> list[AccountRow]:
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM accounts ORDER BY is_active DESC, created_at ASC")
            rows = await cur.fetchall()
    return [_account_from_dict(r) for r in rows]


async def list_active_accounts() -> list[AccountRow]:
    """Return only accounts explicitly enabled for background imports.

    Keep this query separate from :func:`list_accounts` so callers cannot
    accidentally start a browser session for a disabled account when running
    the all-account import job.
    """
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM accounts WHERE is_active = TRUE ORDER BY created_at ASC"
            )
            rows = await cur.fetchall()
    return [_account_from_dict(r) for r in rows]


_ALLOWED_UPDATE_FIELDS = frozenset(
    {
        "name",
        "is_active",
        "chrome_profile_path",
        "cdp_port",
        "niche",
        "niche_source",
        "updated_at",
    }
)


async def update_account(account_id: str, **fields: Any) -> AccountRow | None:
    from datetime import UTC, datetime

    fields = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATE_FIELDS}
    fields["updated_at"] = datetime.now(UTC).isoformat()

    if not fields:
        return await get_account(account_id)

    # ponytail: set_clause built from keys, not string interpolation of values
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [account_id]

    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"UPDATE accounts SET {set_clause} WHERE id = %s RETURNING *",
                values,
            )
            row = await cur.fetchone()
    if row is None:
        return None
    return _account_from_dict(row)


async def delete_account(account_id: str) -> bool:
    pool = get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("DELETE FROM accounts WHERE id = %s", (account_id,))
    return cur.rowcount == 1


async def get_active_account() -> AccountRow | None:
    """Return the currently active account."""
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM accounts WHERE is_active = TRUE LIMIT 1")
            row = await cur.fetchone()
    if row is None:
        return None
    return _account_from_dict(row)


async def set_active_account(account_id: str) -> AccountRow | None:
    """Deactivate all accounts, then activate the given one. Returns the activated account."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()

    pool = get_pool()
    async with pool.connection() as conn:
        # Deactivate all
        await conn.execute("UPDATE accounts SET is_active = FALSE, updated_at = %s", (now,))
        # Activate target
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "UPDATE accounts SET is_active = TRUE, updated_at = %s WHERE id = %s RETURNING *",
                (now, account_id),
            )
            row = await cur.fetchone()
    if row is None:
        return None
    return _account_from_dict(row)


# ── Legacy credential table compatibility ──


async def list_credentials(account_id: str) -> list[CredentialRow]:
    """List all credentials for an account (masked values for display)."""
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT account_id, key_name, encrypted_value
                FROM account_credentials WHERE account_id = %s
                """,
                (account_id,),
            )
            rows = await cur.fetchall()
    return [
        CredentialRow(
            account_id=r["account_id"],
            key_name=r["key_name"],
            _encrypted_bytes=r["encrypted_value"],
        )
        for r in rows
    ]


def _resolve_cdp_host() -> str:
    """Resolve the host that the per-account Chrome's CDP port is reachable on.

    Mirrors the host-probe in ``backend.agents.publisher._resolve_cdp_endpoint``:
    inside a container, ``host.containers.internal`` resolves and points at the
    host where the always-on Chromes run; in local dev it doesn't resolve, so we
    fall back to ``127.0.0.1``. Returns the **IP** (not the hostname) — Chrome 144
    CDP rejects requests whose Host header isn't an IP or localhost (500
    "Host header is specified and is not an IP address or localhost"), so the
    endpoint must be ``http://<ip>:<port>`` not ``http://host.containers.internal``.
    Kept here (not imported from publisher) to avoid a circular import —
    publisher imports accounts at runtime.
    """
    import socket

    host = "host.containers.internal"
    try:
        return socket.gethostbyname(host)
    except OSError:
        return "127.0.0.1"


async def get_account_cdp_endpoint(account_id: str) -> str:
    """Return the per-account CDP endpoint for connecting to that account's
    dedicated Chrome instance.

    Returns ``http://<host>:{port}`` where <host> is ``host.containers.internal``
    inside a container or ``127.0.0.1`` in local dev (same probe convention as
    ``_resolve_cdp_endpoint``'s container fallback). Returns "" when the account
    doesn't exist, has no port binding (cdp_port=0), or the DB is unavailable —
    callers fall back to the global ``_resolve_cdp_endpoint``.
    """
    from backend.db.pool import is_pool_ready

    if not is_pool_ready():
        return ""
    try:
        account = await get_account(account_id)
    except Exception as e:
        logger.warning("get_account_cdp_endpoint: get_account failed: %s", e)
        return ""
    if account is None or account.cdp_port <= 0:
        return ""
    return f"http://{_resolve_cdp_host()}:{account.cdp_port}"


# ── Helpers ──


def _account_from_dict(d: dict[str, Any]) -> AccountRow:
    return AccountRow(
        id=d["id"],
        name=d["name"],
        is_active=d.get("is_active", False),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
        chrome_profile_path=d.get("chrome_profile_path", "") or "",
        cdp_port=int(d.get("cdp_port") or 0),
        niche=d.get("niche", "") or "",
        niche_source=d.get("niche_source", "") or "",
    )
