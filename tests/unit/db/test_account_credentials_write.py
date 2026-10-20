"""``account_credentials`` write path (票 5n).

The table had a reader and no writer: QR login stored the browser profile and
nothing stored the cookie, so the HTTP read path could only ever authenticate as
the deployment identity (``XHS_COOKIE`` env). These pin the write's two
properties:

* **one row per ``(account_id, key_name)``** — re-login replaces the cookie
  instead of accumulating rows, so a reader never has to guess which is current;
* **the value goes through ``db.crypto``** — the same helper the console's secret
  storage uses, so the encryption decision (Fernet, or the documented plaintext
  fallback) has one home.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from backend.db.accounts import upsert_credential
from backend.db.crypto import decrypt_value

pytestmark = pytest.mark.asyncio

_COOKIE = "a1=0123456789abcdef0123; web_session=sess-1"


class _Connection:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self._log = log

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> None:
        self._log.append((sql, params))


class _Pool:
    def __init__(self) -> None:
        self.log: list[tuple[str, Any]] = []

    def connection(self) -> _Connection:
        return _Connection(self.log)


async def test_the_credential_is_upserted_by_account_and_key() -> None:
    pool = _Pool()
    with patch("backend.db.accounts.get_pool", return_value=pool):
        await upsert_credential("acc-1", "XHS_COOKIE", _COOKIE)

    assert len(pool.log) == 1
    sql, params = pool.log[0]
    assert "INSERT INTO account_credentials" in sql
    assert "ON CONFLICT (account_id, key_name)" in sql, (
        "re-login must replace the cookie rather than accumulate rows"
    )
    assert params[0] == "acc-1"
    assert params[1] == "XHS_COOKIE"
    # The reader decrypts with the same helper; a round-trip is the real contract
    # (the bytes on disk may be Fernet ciphertext or the documented plaintext).
    assert decrypt_value(params[2]) == _COOKIE


async def test_the_value_is_encrypted_through_the_shared_helper() -> None:
    """No second encryption path: the writer must not hand-roll it."""
    pool = _Pool()
    with (
        patch("backend.db.accounts.get_pool", return_value=pool),
        patch("backend.db.accounts.encrypt_value", return_value=b"ciphertext") as encrypt,
    ):
        await upsert_credential("acc-1", "XHS_COOKIE", _COOKIE)

    encrypt.assert_called_once_with(_COOKIE)
    assert pool.log[0][1][2] == b"ciphertext"
