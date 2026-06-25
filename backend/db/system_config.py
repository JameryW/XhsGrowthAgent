"""System-wide configuration storage — global secrets shared across XHS accounts.

LLM keys, Ripple settings, embedding/search keys live here (not per-XHS-account).
Reuses crypto.py for at-rest encryption.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from backend.db.crypto import decrypt_value, encrypt_value, mask_value
from backend.db.pool import get_pool

logger = logging.getLogger("xhs_growth.db.system_config")


# ── Whitelisted system-config keys ──
# Anything global / not bound to a specific XHS account belongs here.

SYSTEM_KEYS = [
    # LLM providers
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "XIAOMIMIMO_API_KEY",
    # Ripple CAS
    "RIPPLE_BASE_URL",
    "RIPPLE_API_TOKEN",
    "RIPPLE_ENABLED",
    "RIPPLE_LLM_MODEL_PLATFORM",
    "RIPPLE_LLM_MODEL_NAME",
    "RIPPLE_LLM_API_KEY",
    "RIPPLE_LLM_URL",
    # Ripple simulation params (non-secret, shown as plain text in UI)
    "RIPPLE_MAX_WAVES",
    "RIPPLE_ENSEMBLE_RUNS",
    "RIPPLE_SIMULATION_HORIZON",
    # Search
    "TAVILY_API_KEY",
    # Embedding
    "XHS_EMBED_MODEL",
    "XHS_EMBED_BASE_URL",
]

# ponytail: params shown as plain-text/number inputs; secrets use password + mask
SYSTEM_PARAM_KEYS = {
    "RIPPLE_MAX_WAVES",
    "RIPPLE_ENSEMBLE_RUNS",
    "RIPPLE_SIMULATION_HORIZON",
    "RIPPLE_ENABLED",
}


# ── Key groups (UI hint; backend doesn't enforce) ──

SYSTEM_KEY_GROUPS = [
    {
        "id": "llm_providers",
        "keys": [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "DASHSCOPE_API_KEY",
            "XIAOMIMIMO_API_KEY",
        ],
    },
    {
        "id": "ripple_cas",
        "keys": [
            "RIPPLE_BASE_URL",
            "RIPPLE_API_TOKEN",
            "RIPPLE_ENABLED",
            "RIPPLE_LLM_MODEL_PLATFORM",
            "RIPPLE_LLM_MODEL_NAME",
            "RIPPLE_LLM_API_KEY",
            "RIPPLE_LLM_URL",
            "RIPPLE_MAX_WAVES",
            "RIPPLE_ENSEMBLE_RUNS",
            "RIPPLE_SIMULATION_HORIZON",
        ],
    },
    {
        "id": "search_embedding",
        "keys": [
            "TAVILY_API_KEY",
            "XHS_EMBED_MODEL",
            "XHS_EMBED_BASE_URL",
        ],
    },
]


@dataclass
class SystemConfigRow:
    key_name: str
    _encrypted_bytes: bytes | None = None
    updated_at: str = ""

    @property
    def value(self) -> str:
        if self._encrypted_bytes:
            return decrypt_value(self._encrypted_bytes)
        return ""

    @property
    def masked(self) -> str:
        v = self.value
        return mask_value(v) if v else ""


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS system_config (
    key_name        TEXT PRIMARY KEY,
    encrypted_value BYTEA NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT ''
);
"""


async def ensure_tables() -> None:
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_TABLE_SQL)
    logger.info("system_config table ensured")


# ── CRUD ──

async def list_config() -> list[SystemConfigRow]:
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT key_name, encrypted_value, updated_at FROM system_config "
                "ORDER BY key_name ASC"
            )
            rows = await cur.fetchall()
    return [
        SystemConfigRow(
            key_name=r["key_name"],
            _encrypted_bytes=r["encrypted_value"],
            updated_at=r.get("updated_at", ""),
        )
        for r in rows
    ]


async def set_config(items: dict[str, str]) -> None:
    """Batch-set system config. Empty values delete the key. Unknown keys ignored."""
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()

    pool = get_pool()
    async with pool.connection() as conn:
        for key_name, plain in items.items():
            if key_name not in SYSTEM_KEYS:
                logger.warning(f"Ignoring unknown system_config key: {key_name}")
                continue
            if not plain:
                await conn.execute(
                    "DELETE FROM system_config WHERE key_name = %s",
                    (key_name,),
                )
                continue
            encrypted = encrypt_value(plain)
            await conn.execute(
                """
                INSERT INTO system_config (key_name, encrypted_value, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (key_name)
                DO UPDATE SET encrypted_value = EXCLUDED.encrypted_value,
                              updated_at = EXCLUDED.updated_at
                """,
                (key_name, encrypted, now),
            )
    logger.info(f"Set {len(items)} system config keys")


async def delete_config(key_name: str) -> bool:
    pool = get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("DELETE FROM system_config WHERE key_name = %s", (key_name,))
    return cur.rowcount == 1


async def count_config() -> int:
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) FROM system_config")
        (n,) = await cur.fetchone()
    return int(n)


# ── Activation ──

async def activate_system_config() -> dict[str, str]:
    """Push all system_config rows into os.environ. Clears stale keys first."""
    for key in SYSTEM_KEYS:
        os.environ.pop(key, None)

    rows = await list_config()
    loaded = {}
    for r in rows:
        v = r.value
        if v:
            os.environ[r.key_name] = v
            loaded[r.key_name] = v
    logger.info(f"Activated {len(loaded)} system config keys into os.environ")
    return loaded


# ── Migration ──

async def migrate_from_accounts() -> int:
    """One-shot, idempotent migration: pull SYSTEM_KEYS from active account into system_config.

    No-op if system_config already has any rows. Returns number of keys migrated.
    """
    if await count_config() > 0:
        return 0

    from backend.db.accounts import get_active_account, list_credentials

    active = await get_active_account()
    if active is None:
        logger.info("No active account; nothing to migrate to system_config")
        return 0

    creds = await list_credentials(active.id)
    to_migrate = {c.key_name: c.value for c in creds if c.key_name in SYSTEM_KEYS and c.value}

    if not to_migrate:
        logger.info("Active account has no SYSTEM_KEYS to migrate")
        # Still strip SYSTEM_KEYS from all account_credentials so the schema is clean
        await _strip_system_keys_from_accounts()
        return 0

    await set_config(to_migrate)
    await _strip_system_keys_from_accounts()
    logger.info(
        f"Migrated {len(to_migrate)} keys from account {active.id} → system_config"
    )
    return len(to_migrate)


async def _strip_system_keys_from_accounts() -> None:
    """Remove SYSTEM_KEYS rows from account_credentials across all accounts."""
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "DELETE FROM account_credentials WHERE key_name = ANY(%s)",
            (SYSTEM_KEYS,),
        )
    logger.info("Stripped SYSTEM_KEYS from account_credentials")


async def bootstrap_from_environ() -> int:
    """Seed system_config from os.environ on first run (idempotent).

    No-op if system_config already has any rows.
    """
    if await count_config() > 0:
        return 0
    seed = {k: os.environ[k] for k in SYSTEM_KEYS if os.environ.get(k)}
    if not seed:
        return 0
    await set_config(seed)
    logger.info(f"Bootstrapped system_config with {len(seed)} keys from os.environ")
    return len(seed)
