"""Console user CRUD — admin login accounts (multi-user support).

Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib hashlib, no extra deps).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from dataclasses import dataclass

from backend.db.pool import get_pool

logger = logging.getLogger("xhs_growth.db.console_users")

# PBKDF2 parameters — internal tool, not exposed to internet; 200k rounds is plenty.
# ponytail: pbkdf2 from stdlib — no bcrypt dep needed; bump rounds if threat model grows.
_PBKDF2_ROUNDS = 200_000
_PBKDF2_ALGO = "sha256"
_SALT_BYTES = 16


@dataclass
class ConsoleUserRow:
    id: str
    username: str
    created_at: str = ""
    last_login_at: str | None = None


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS console_users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT '',
    last_login_at   TEXT
);
"""


async def ensure_tables() -> None:
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_TABLE_SQL)
    logger.info("console_users table ensured")


# ── Password hashing ──

def _hash_password(password: str, salt: bytes | None = None) -> str:
    """Return 'pbkdf2_sha256$rounds$salt_hex$hash_hex'."""
    if salt is None:
        salt = os.urandom(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_{_PBKDF2_ALGO}${_PBKDF2_ROUNDS}${salt.hex()}${derived.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo_tag, rounds_str, salt_hex, hash_hex = stored.split("$", 3)
        if not algo_tag.startswith("pbkdf2_"):
            return False
        algo = algo_tag.split("_", 1)[1]
        rounds = int(rounds_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        derived = hashlib.pbkdf2_hmac(algo, password.encode(), salt, rounds)
        return hmac.compare_digest(derived, expected)
    except (ValueError, KeyError):
        return False


# ── CRUD ──

async def create_user(username: str, password: str) -> ConsoleUserRow:
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    user_id = str(uuid.uuid4())
    pwd_hash = _hash_password(password)

    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO console_users (id, username, password_hash, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, username, pwd_hash, now),
        )
    return ConsoleUserRow(id=user_id, username=username, created_at=now)


async def list_users() -> list[ConsoleUserRow]:
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, username, created_at, last_login_at "
                "FROM console_users ORDER BY created_at ASC"
            )
            rows = await cur.fetchall()
    return [
        ConsoleUserRow(
            id=r["id"],
            username=r["username"],
            created_at=r.get("created_at", ""),
            last_login_at=r.get("last_login_at"),
        )
        for r in rows
    ]


async def get_user_by_username(username: str) -> ConsoleUserRow | None:
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, username, created_at, last_login_at "
                "FROM console_users WHERE username = %s",
                (username,),
            )
            row = await cur.fetchone()
    if row is None:
        return None
    return ConsoleUserRow(
        id=row["id"],
        username=row["username"],
        created_at=row.get("created_at", ""),
        last_login_at=row.get("last_login_at"),
    )


async def verify_login(username: str, password: str) -> ConsoleUserRow | None:
    """Verify username+password. On success, update last_login_at and return user."""
    from datetime import UTC, datetime

    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, username, password_hash, created_at, last_login_at "
                "FROM console_users WHERE username = %s",
                (username,),
            )
            row = await cur.fetchone()

    if row is None:
        return None
    if not _verify_password(password, row["password_hash"]):
        return None

    now = datetime.now(UTC).isoformat()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE console_users SET last_login_at = %s WHERE id = %s",
            (now, row["id"]),
        )
    return ConsoleUserRow(
        id=row["id"],
        username=row["username"],
        created_at=row.get("created_at", ""),
        last_login_at=now,
    )


async def update_password(user_id: str, new_password: str) -> bool:
    pwd_hash = _hash_password(new_password)
    pool = get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE console_users SET password_hash = %s WHERE id = %s",
            (pwd_hash, user_id),
        )
    return cur.rowcount == 1


async def delete_user(user_id: str) -> bool:
    pool = get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("DELETE FROM console_users WHERE id = %s", (user_id,))
    return cur.rowcount == 1


async def count_users() -> int:
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) FROM console_users")
        (n,) = await cur.fetchone()
    return int(n)


# ── Bootstrap ──

async def bootstrap_default_user() -> None:
    """Seed admin/admin123 only when no users exist (idempotent first-install seed).

    This is the only entry point that ever puts a known credential in the
    database. Once you log in for the first time, change the password (or
    create a new user and delete this one) — there is no other path to
    admin/admin123 anywhere in the auth stack.
    """
    if await count_users() > 0:
        return
    await create_user("admin", "admin123")
    logger.info("Bootstrapped default console user: admin (CHANGE THE PASSWORD)")


# ── Self-check ──

def _selfcheck() -> None:
    h = _hash_password("hunter2")
    assert _verify_password("hunter2", h), "verify of correct password failed"
    assert not _verify_password("wrong", h), "verify of wrong password should fail"
    assert not _verify_password("hunter2", "garbage$$"), "malformed hash should fail closed"
    h2 = _hash_password("hunter2")
    assert h != h2, "salts must be unique"
    print("console_users self-check OK")


if __name__ == "__main__":
    _selfcheck()
