"""Account and credentials CRUD — multi-tenant account management."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from backend.db.crypto import decrypt_value, encrypt_value, mask_value
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


# ── Known credential keys ──
#
# After the console-account-system refactor, accounts only hold XHS platform
# credentials. LLM/Ripple/embedding/search keys live in system_config (global).
# `CREDENTIAL_KEYS` is kept as an alias for `XHS_KEYS` so older imports still work.

XHS_KEYS = [
    "XHS_COOKIE",
    "XHS_USER_ID",
]

# Backward-compat alias — do not extend with non-XHS keys.
CREDENTIAL_KEYS = XHS_KEYS

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


async def ensure_tables() -> None:
    """Create accounts + credentials tables if they don't exist."""
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_ACCOUNTS_SQL)
        await conn.execute(_CREATE_CREDENTIALS_SQL)
        await conn.execute(_CREATE_INDEX_SQL)
    logger.info("accounts + credentials tables ensured")


# ── Account CRUD ──

async def create_account(name: str, is_active: bool = False) -> AccountRow:
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    id_ = str(uuid.uuid4())

    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO accounts
                (id, name, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (id_, name, is_active, now, now),
        )
    return AccountRow(id=id_, name=name, is_active=is_active, created_at=now, updated_at=now)


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


async def update_account(account_id: str, **fields) -> AccountRow | None:
    from datetime import UTC, datetime
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


# ── Credential CRUD ──

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


async def set_credentials(account_id: str, creds: dict[str, str]) -> None:
    """Batch-set credentials for an account. Upserts each key.

    Non-XHS keys are silently dropped — they belong in system_config.
    """
    pool = get_pool()
    async with pool.connection() as conn:
        for key_name, plain_value in creds.items():
            if key_name not in XHS_KEYS:
                logger.warning(
                    f"Ignoring non-XHS key on account {account_id}: {key_name} "
                    "(belongs in system_config)"
                )
                continue
            if not plain_value:
                # Delete empty values
                await conn.execute(
                    "DELETE FROM account_credentials WHERE account_id = %s AND key_name = %s",
                    (account_id, key_name),
                )
                continue
            encrypted = encrypt_value(plain_value)
            await conn.execute(
                """
                INSERT INTO account_credentials (account_id, key_name, encrypted_value)
                VALUES (%s, %s, %s)
                ON CONFLICT (account_id, key_name)
                DO UPDATE SET encrypted_value = EXCLUDED.encrypted_value
                """,
                (account_id, key_name, encrypted),
            )
    logger.info(f"Set {len(creds)} credentials for account {account_id}")


async def delete_credential(account_id: str, key_name: str) -> bool:
    pool = get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM account_credentials WHERE account_id = %s AND key_name = %s",
            (account_id, key_name),
        )
    return cur.rowcount == 1


# ── Hot reload ──

async def activate_credentials(account_id: str) -> dict[str, str]:
    """Load an account's credentials and push them to os.environ (hot reload).

    Clears all DB-managed keys from os.environ first so a previously-active
    account's keys don't leak into the new one (e.g. switching from an account
    with ANTHROPIC_API_KEY set to one without).

    Returns the dict of {env_var: value} that was loaded.
    """
    import os

    # Clear stale keys from any previously-active account
    for key in CREDENTIAL_KEYS:
        os.environ.pop(key, None)

    creds = await list_credentials(account_id)
    loaded = {}
    for cred in creds:
        value = cred.value
        if value:
            os.environ[cred.key_name] = value
            loaded[cred.key_name] = value
    logger.info(f"Activated {len(loaded)} credentials for account {account_id} into os.environ")
    return loaded


async def deactivate_credentials() -> None:
    """Remove all credential keys from os.environ that are managed by DB."""
    import os

    for key in CREDENTIAL_KEYS:
        os.environ.pop(key, None)
    logger.info("Deactivated all DB-managed credentials from os.environ")


async def load_active_credentials() -> dict[str, str]:
    """On startup: load the active account's credentials into os.environ.

    If no accounts exist yet, bootstrap a 'default' account seeded from the
    current os.environ — so first-time users coming from a .env-only setup
    don't have to re-paste every key in the UI.

    Returns empty dict if bootstrap had nothing to seed.
    """
    active = await get_active_account()
    if active is None:
        await _bootstrap_default_account()
        active = await get_active_account()
        if active is None:
            return {}
    return await activate_credentials(active.id)


async def _bootstrap_default_account() -> None:
    """Create a 'default' active account, seeded from os.environ XHS keys.

    No-op if any account already exists (keeps idempotent across restarts).
    System-wide keys (LLM/Ripple/etc.) are NOT seeded here — they belong in
    `backend.db.system_config`.
    """
    import os

    accounts = await list_accounts()
    if accounts:
        return

    acc = await create_account(name="default", is_active=False)
    await set_active_account(acc.id)
    seed = {k: os.environ[k] for k in XHS_KEYS if os.environ.get(k)}
    if seed:
        await set_credentials(acc.id, seed)
    logger.info(f"Bootstrapped default account with {len(seed)} XHS keys from os.environ")


# ── Helpers ──

def _account_from_dict(d: dict) -> AccountRow:
    return AccountRow(
        id=d["id"],
        name=d["name"],
        is_active=d.get("is_active", False),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )
