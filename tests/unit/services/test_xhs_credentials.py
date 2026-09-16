"""P2a-S5a: who owns an account's credential, and what it entitles.

Four things are pinned here.

1. **Where the credential comes from.**  The account's own rows first; the
   deployment credential (``XHS_COOKIE``) second; nothing third.  The account's
   answer is *final* — an unusable account credential is never silently
   replaced by the deployment default, because that would read and publish as a
   different identity than the caller asked for.  Presence of a row is a
   statement about the account; an unset environment variable is not, which is
   why the two sources differ on what an empty value means.
2. **Fail-closed at the boundary.**  A reader that raises means "unknown", and
   unknown is not permission to act as somebody else.  A *missing* account
   store is a different thing from an unreadable one and is treated as such.
3. **One answer, two readers.**  The cookie and the scopes come off the same
   :class:`XhsCredential`; the scope vocabulary is a mirror of ``catalog``'s
   declarations, and the two are compared here so a rename cannot drift.
4. **The default reader is the production read.**  Its behaviour is asserted
   against the real ``CredentialRow`` type and its real ``value`` property
   rather than through an injected mapping.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from backend.db.accounts import CredentialRow
from backend.services.xhs_credentials import (
    COOKIE_KEY,
    SOURCE_ACCOUNT,
    SOURCE_ENVIRONMENT,
    USER_ID_KEY,
    XHS_CREDENTIAL_KEYS,
    XHS_READ_SCOPE,
    XHS_WRITE_SCOPE,
    granted_scopes,
    load_credential,
)
from backend.tools.runtime.catalog import build_registry

# ``a1`` with enough material is what ``XHSCookieParser.is_valid`` asks for.
VALID = "a1=" + "0" * 20 + "; web_session=session"
OTHER = "a1=" + "1" * 20 + "; web_session=other"
MALFORMED = "web_session=stale"


def _reader(**rows: str):
    """A reader that answers with the given rows, whatever account is asked for."""

    async def _read(account_id: str) -> Mapping[str, str]:
        return dict(rows)

    return _read


class TestWhereTheCredentialComesFrom:
    async def test_the_accounts_own_row_wins(self, monkeypatch):
        monkeypatch.setenv(COOKIE_KEY, OTHER)
        credential = await load_credential(
            "acc-1", reader=_reader(**{COOKIE_KEY: VALID, USER_ID_KEY: "u1"})
        )

        assert credential.source == SOURCE_ACCOUNT
        assert credential.cookie == VALID
        assert credential.user_id == "u1"
        assert credential.usable is True

    async def test_an_unusable_account_credential_is_not_overridden(self, monkeypatch):
        """The identity rule, and the one an operator will meet for real.

        The account has a row and the deployment has a *good* credential.  Using
        the deployment's would read and publish as the wrong account, silently,
        on a path where the caller named the account explicitly — so the
        account's broken credential is reported as broken instead.
        """
        monkeypatch.setenv(COOKIE_KEY, OTHER)
        credential = await load_credential("acc-1", reader=_reader(**{COOKIE_KEY: MALFORMED}))

        assert credential.source == SOURCE_ACCOUNT
        assert credential.cookie == MALFORMED
        assert credential.usable is False
        assert credential.scopes == ()

    async def test_the_deployment_credential_is_the_single_account_fallback(self, monkeypatch):
        monkeypatch.setenv(COOKIE_KEY, VALID)
        monkeypatch.setenv(USER_ID_KEY, "deployment-user")
        credential = await load_credential("acc-1", reader=_reader())

        assert credential.source == SOURCE_ENVIRONMENT
        assert credential.cookie == VALID
        assert credential.user_id == "deployment-user"
        assert credential.usable is True

    async def test_a_blank_account_does_not_consult_the_account_source(self, monkeypatch):
        """``xhs.trending``'s default ``account_id=""`` is a real call shape.

        There is no account to look up, so the reader must not be asked — and
        the deployment credential is what such a call means.
        """
        asked: list[str] = []

        async def _spy(account_id: str) -> Mapping[str, str]:
            asked.append(account_id)
            return {COOKIE_KEY: VALID}

        monkeypatch.setenv(COOKIE_KEY, VALID)
        credential = await load_credential("   ", reader=_spy)

        assert asked == []
        assert credential.account_id == ""
        assert credential.source == SOURCE_ENVIRONMENT
        assert credential.cookie == VALID

    async def test_nothing_anywhere_names_no_source(self, monkeypatch):
        """An unset deployment credential is not a statement, so there is no source.

        This is what an operator sees in the refusal ("credential source: none")
        when neither the account nor the deployment has one — as opposed to a
        source that was consulted and had nothing usable in it.
        """
        monkeypatch.setenv(COOKIE_KEY, "")
        monkeypatch.setenv(USER_ID_KEY, "")
        credential = await load_credential("acc-1", reader=_reader())

        assert credential.source == ""
        assert credential.cookie == ""
        assert credential.usable is False
        assert credential.scopes == ()


class TestFailClosedAtTheBoundary:
    async def test_a_raising_reader_yields_an_unusable_credential(self, monkeypatch):
        """Unknown is not permission.

        The account store is unreadable, so whether this account has a login of
        its own is *unknown*.  Falling back to the deployment credential would
        answer a question nobody could answer, with an identity the caller did
        not name — so the boundary stops here rather than fail open.
        """

        async def _boom(account_id: str) -> Mapping[str, str]:
            raise RuntimeError("connection reset")

        monkeypatch.setenv(COOKIE_KEY, VALID)
        credential = await load_credential("acc-1", reader=_boom)

        assert credential.usable is False
        assert credential.source == ""
        assert credential.scopes == ()

    async def test_a_missing_account_store_is_not_a_reader_failure(self, monkeypatch):
        """No pool means the deployment has no per-account credentials at all.

        That is a configuration fact (``db/accounts`` is Postgres-only, with no
        memory fallback — the same distinction ``db/creator_agent`` draws), not
        a read that failed, so the deployment credential still applies.
        """
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)
        monkeypatch.setenv(COOKIE_KEY, VALID)

        credential = await load_credential("acc-1")

        assert credential.source == SOURCE_ENVIRONMENT
        assert credential.usable is True

    async def test_the_deployment_credential_reads_the_declared_environment_keys(self, monkeypatch):
        """``.env.example`` declared ``XHS_COOKIE``/``XHS_USER_ID`` from day one.

        Nothing read them until this slice, so the declaration was decoration.
        The mapping is asserted through the real settings object (not a
        paraphrase), which is also what pins the env prefix.
        """
        from backend.config.settings import Settings

        monkeypatch.setenv(COOKIE_KEY, VALID)
        monkeypatch.setenv(USER_ID_KEY, "u9")

        platform = Settings().platform

        assert platform.cookie == VALID
        assert platform.user_id == "u9"


class TestUsability:
    @pytest.mark.parametrize("cookie", ["", "web_session=only", "a1=short", "a1="])
    async def test_a_cookie_without_login_material_is_not_usable(self, cookie):
        credential = await load_credential("acc-1", reader=_reader(**{COOKIE_KEY: cookie}))

        assert credential.usable is False
        assert credential.scopes == ()

    async def test_a_user_id_alone_is_not_a_credential(self):
        credential = await load_credential("acc-1", reader=_reader(**{USER_ID_KEY: "u1"}))

        assert credential.usable is False

    async def test_one_usable_credential_grants_both_scopes(self):
        credential = await load_credential("acc-1", reader=_reader(**{COOKIE_KEY: VALID}))

        assert credential.scopes == (XHS_READ_SCOPE, XHS_WRITE_SCOPE)

    async def test_granted_scopes_is_the_same_answer_as_the_credential(self):
        """One rule, two readers — asserted rather than assumed.

        The dispatcher asks for scopes and the executor asks for the credential;
        if these two ever disagreed, a publish could be refused for a grant the
        Gateway would have accepted (or the reverse).
        """
        credentialed = _reader(**{COOKIE_KEY: VALID})
        bare = _reader()

        assert (
            await granted_scopes("acc-1", reader=credentialed)
            == (await load_credential("acc-1", reader=credentialed)).scopes
        )
        assert await granted_scopes("acc-1", reader=bare) == ()

    def test_the_scope_vocabulary_mirrors_the_catalogs_declarations(self):
        """The constants are a mirror, and this is the tie.

        Renaming a scope in ``catalog`` without touching this module would make
        every account unentitled — silently, because an unrecognised scope in
        the grant and an unrecognised requirement in the declaration look
        identical from the Gateway's side.  So the two are compared here.
        """
        registry = build_registry()
        declared = {
            scope
            for capability in registry.capabilities()
            for scope in registry.spec(capability).auth_scope
        }

        assert {XHS_READ_SCOPE, XHS_WRITE_SCOPE} <= declared
        assert registry.spec("xhs.publish").auth_scope == (XHS_WRITE_SCOPE,)
        assert XHS_CREDENTIAL_KEYS == (COOKIE_KEY, USER_ID_KEY)


class TestTheDefaultReaderIsTheRealPath:
    @staticmethod
    def _rows(*, material: bytes | None = b"ciphertext") -> list[CredentialRow]:
        return [
            CredentialRow(account_id="acc-1", key_name=COOKIE_KEY, _encrypted_bytes=material),
            CredentialRow(account_id="acc-1", key_name=USER_ID_KEY, _encrypted_bytes=material),
            CredentialRow(
                account_id="acc-1", key_name="ANTHROPIC_API_KEY", _encrypted_bytes=material
            ),
        ]

    @staticmethod
    def _store(monkeypatch, rows: list[CredentialRow], decoded: Mapping[bytes, str]) -> None:
        """Serve the rows from the real store read, with real decryption replaced.

        Only ``decrypt_value`` is doubled — the rows are the real ``CredentialRow``
        type and ``row.value`` still runs its own property, because that property
        (and its "no ciphertext answers empty" branch) is part of what the
        resolver consumes.
        """
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

        async def _list(account_id: str) -> list[CredentialRow]:
            assert account_id == "acc-1"
            return rows

        def _decrypt(data: bytes) -> str:
            return decoded[data]

        monkeypatch.setattr("backend.db.accounts.list_credentials", _list)
        monkeypatch.setattr("backend.db.accounts.decrypt_value", _decrypt)

    async def test_it_reads_the_accounts_rows_and_keeps_the_allow_list(self, monkeypatch):
        decoded = {b"cookie": VALID, b"uid": "u1", b"key": "sk-x"}
        rows = [
            CredentialRow(account_id="acc-1", key_name=COOKIE_KEY, _encrypted_bytes=b"cookie"),
            CredentialRow(account_id="acc-1", key_name=USER_ID_KEY, _encrypted_bytes=b"uid"),
            CredentialRow(
                account_id="acc-1", key_name="ANTHROPIC_API_KEY", _encrypted_bytes=b"key"
            ),
        ]
        self._store(monkeypatch, rows, decoded)

        credential = await load_credential("acc-1")

        assert credential.source == SOURCE_ACCOUNT
        assert credential.cookie == VALID
        assert credential.user_id == "u1"

    async def test_only_allow_listed_rows_count_as_the_accounts_credential(self, monkeypatch):
        """The allow-list lives in the reader, and it is load-bearing.

        A row for something else (an API key belongs in ``system_config``, but
        the legacy table can still hold one) must not count as "this account has
        its own credential" — otherwise the deployment credential would stop
        applying for an account that never had a login of its own, and every
        read would fail for a reason nobody could see.
        """
        self._store(
            monkeypatch,
            [
                CredentialRow(
                    account_id="acc-1", key_name="ANTHROPIC_API_KEY", _encrypted_bytes=b"key"
                )
            ],
            {b"key": "sk-x"},
        )
        monkeypatch.setenv(COOKIE_KEY, VALID)

        credential = await load_credential("acc-1")

        assert credential.source == SOURCE_ENVIRONMENT
        assert credential.cookie == VALID

    async def test_a_row_with_no_stored_material_is_empty_rather_than_a_crash(self, monkeypatch):
        """``CredentialRow.value`` answers ``""`` for a row with no ciphertext.

        That is the real type's contract, and it must stay the account's final
        answer: a row that exists but carries nothing is a cleared credential,
        not an invitation to use somebody else's.  The deployment credential is
        deliberately left valid here to assert exactly that.
        """
        self._store(monkeypatch, self._rows(material=None), {})
        monkeypatch.setenv(COOKIE_KEY, VALID)

        credential = await load_credential("acc-1")

        assert credential.source == SOURCE_ACCOUNT
        assert credential.usable is False
