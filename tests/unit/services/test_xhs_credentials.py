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
5. **Scopes follow the mechanism, not the credential.**  Read needs the cookie;
   write needs the cookie *or* a bound browser profile, because the publish
   path drives CDP with ``cookie=""``.  Binding is not reachability, and a
   binding read that fails denies the write rather than inventing it.  A blank
   account id is bound by the deployment's *declared* endpoint, never by the
   publisher's reachability probe.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from backend.db.accounts import AccountRow, CredentialRow
from backend.services.xhs_credentials import (
    COOKIE_KEY,
    SOURCE_ACCOUNT,
    SOURCE_ENVIRONMENT,
    USER_ID_KEY,
    XHS_CREDENTIAL_KEYS,
    XHS_OUTREACH_SCOPE,
    XHS_READ_SCOPE,
    XHS_WRITE_SCOPE,
    granted_scopes,
    load_credential,
)
from backend.services.xhs_outreach_policy import (
    DAILY_PROACTIVE_CAP_KEY,
    MODE_KEY,
    OUTREACH_CONFIRMED,
    XhsOutreachPolicy,
)
from backend.tools.runtime.catalog import build_registry

_OUTREACH_ENV = (MODE_KEY, DAILY_PROACTIVE_CAP_KEY, "XHS_ALLOW_OUTBOUND_DM")


@pytest.fixture(autouse=True)
def _clean_deployment_outreach(monkeypatch):
    """The deployment outreach env is an input, not ambient state."""
    for key in _OUTREACH_ENV:
        monkeypatch.delenv(key, raising=False)
    yield


# ``a1`` with enough material is what ``XHSCookieParser.is_valid`` asks for.
VALID = "a1=" + "0" * 20 + "; web_session=session"
OTHER = "a1=" + "1" * 20 + "; web_session=other"
MALFORMED = "web_session=stale"


def _reader(**rows: str):
    """A reader that answers with the given rows, whatever account is asked for."""

    async def _read(account_id: str) -> Mapping[str, str]:
        return dict(rows)

    return _read


def _binding(endpoint: str):
    """A profile seam that answers with ``endpoint`` (``""`` = not bound)."""

    async def _read(account_id: str) -> str:
        return endpoint

    return _read


def _binding_that_raises():
    async def _read(account_id: str) -> str:
        raise RuntimeError("accounts table unreachable")

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

        # ``xhs:outreach`` is in the vocabulary and deliberately **not** in the
        # catalog: no capability declares it while the engagement tools stay
        # unregistered (§9.4 — registering is the moment agents can reach out).
        # When they register, this goes red on purpose and the declaring
        # capability must be named here in the same commit.
        assert XHS_OUTREACH_SCOPE not in declared


class TestScopesFollowTheMechanism:
    """The grant is per-capability, because the mechanisms are not shared.

    ``xhs:read`` *is* the cookie: every read capability builds an ``XHSClient``
    whose identity is that cookie.  ``xhs:write`` is the account's own browser —
    ``XHSPublisher`` is constructed with ``cookie=""`` and drives CDP — so a
    bound profile is enough there.  Granting the two together, which is what the
    owner did before this slice, refused publishes the deployment can actually
    perform.
    """

    async def test_a_cookie_grants_both(self):
        credential = await load_credential(
            "acc-1", reader=_reader(**{COOKIE_KEY: VALID}), profile_reader=_binding("")
        )

        assert credential.scopes == (XHS_READ_SCOPE, XHS_WRITE_SCOPE)

    async def test_a_bound_profile_grants_write_and_not_read(self):
        credential = await load_credential(
            "acc-1", reader=_reader(), profile_reader=_binding("http://127.0.0.1:9333")
        )

        assert credential.usable is False
        assert credential.profile_bound is True
        assert credential.scopes == (XHS_WRITE_SCOPE,)

    async def test_a_stale_cookie_with_a_bound_profile_keeps_the_write_grant(self):
        """The case the cookie-only rule answered wrongly.

        A stale cookie is a *read* problem — the HTTP client cannot act as
        anyone.  It says nothing about the browser, which still belongs to this
        account, so the publish path stays open while reads stay closed.
        """
        credential = await load_credential(
            "acc-1",
            reader=_reader(**{COOKIE_KEY: MALFORMED}),
            profile_reader=_binding("http://127.0.0.1:9333"),
        )

        assert credential.source == SOURCE_ACCOUNT
        assert credential.scopes == (XHS_WRITE_SCOPE,)

    async def test_a_failed_binding_read_denies_the_write(self):
        credential = await load_credential(
            "acc-1",
            reader=_reader(**{COOKIE_KEY: MALFORMED}),
            profile_reader=_binding_that_raises(),
        )

        assert credential.profile_bound is False
        assert credential.scopes == ()

    async def test_a_failed_binding_read_does_not_withdraw_the_cookie(self):
        """Independence cuts both ways: the cookie covers both scopes by itself."""
        credential = await load_credential(
            "acc-1",
            reader=_reader(**{COOKIE_KEY: VALID}),
            profile_reader=_binding_that_raises(),
        )

        assert credential.scopes == (XHS_READ_SCOPE, XHS_WRITE_SCOPE)

    async def test_a_blank_account_is_bound_by_the_declared_deployment_endpoint(self, monkeypatch):
        """With no account to look up, the deployment's declaration answers.

        ``XHS_CDP_ENDPOINT`` is the counterpart of ``XHS_COOKIE``: it is what a
        single-account deployment means.  It is *declared* and never probed — the
        publisher's own fallback probes the well-known port, and borrowing that
        answer would make the grant depend on whether a Chrome process is up.
        """
        monkeypatch.setenv(COOKIE_KEY, "")
        monkeypatch.setenv(USER_ID_KEY, "")
        monkeypatch.setenv("XHS_CDP_ENDPOINT", "http://127.0.0.1:9333")

        credential = await load_credential("")

        assert credential.account_id == ""
        assert credential.profile_bound is True
        assert credential.scopes == (XHS_WRITE_SCOPE,)

    async def test_a_blank_account_does_not_borrow_a_named_accounts_binding(self, monkeypatch):
        """The blank path must not hit the account store at all."""

        async def _must_not_be_called(account_id: str) -> str:
            raise AssertionError(f"account store consulted for {account_id!r}")

        monkeypatch.setattr("backend.db.accounts.get_account_cdp_endpoint", _must_not_be_called)
        monkeypatch.setenv(COOKIE_KEY, "")
        monkeypatch.setenv(USER_ID_KEY, "")
        monkeypatch.setenv("XHS_CDP_ENDPOINT", "http://127.0.0.1:9333")

        credential = await load_credential("  ")

        assert credential.profile_bound is True

    async def test_an_undeclared_deployment_has_no_binding(self, monkeypatch):
        monkeypatch.setenv(COOKIE_KEY, "")
        monkeypatch.setenv(USER_ID_KEY, "")
        monkeypatch.setenv("XHS_CDP_ENDPOINT", "")

        credential = await load_credential("")

        assert credential.profile_bound is False
        assert credential.scopes == ()

    async def test_the_seam_still_decides_when_one_is_injected(self, monkeypatch):
        asked: list[str] = []

        async def _spy(account_id: str) -> str:
            asked.append(account_id)
            return "http://127.0.0.1:9333"

        monkeypatch.setenv(COOKIE_KEY, "")
        monkeypatch.setenv(USER_ID_KEY, "")
        credential = await load_credential("   ", profile_reader=_spy)

        assert asked == [""]
        assert credential.profile_bound is True
        assert credential.scopes == (XHS_WRITE_SCOPE,)

    async def test_an_unreadable_credential_store_does_not_withdraw_the_binding(self):
        """Each fact is decided by its own read, not by the other one's failure.

        The boundary still answers a failed *row* read with a blank cookie, and
        that is right: unknown is not permission to borrow the deployment's
        identity.  It is not right for the binding, which came from its own
        successful read and belongs to this account — granting write from it acts
        as the account the caller named, which is what the grant is about.
        """

        async def _boom(account_id: str) -> Mapping[str, str]:
            raise RuntimeError("connection reset")

        credential = await load_credential(
            "acc-1", reader=_boom, profile_reader=_binding("http://127.0.0.1:9333")
        )

        assert credential.source == ""
        assert credential.scopes == (XHS_WRITE_SCOPE,)

    async def test_the_default_profile_seam_reads_the_accounts_cdp_binding(self, monkeypatch):
        """The production path, asserted end to end.

        A non-empty endpoint is what ``get_account_cdp_endpoint`` returns when the
        account row carries a ``cdp_port``, and that — nothing else — is what
        makes ``profile_bound`` true.  No probe, no socket, no Chrome.
        """
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

        async def _account(account_id: str) -> AccountRow:
            assert account_id == "acc-1"
            return AccountRow(id="acc-1", name="A", cdp_port=9333)

        monkeypatch.setattr("backend.db.accounts.get_account", _account)
        monkeypatch.setenv(COOKIE_KEY, "")
        monkeypatch.setenv(USER_ID_KEY, "")

        credential = await load_credential("acc-1", reader=_reader())

        assert credential.profile_bound is True
        assert credential.scopes == (XHS_WRITE_SCOPE,)

    async def test_an_account_with_no_cdp_port_is_not_bound(self, monkeypatch):
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

        async def _account(account_id: str) -> AccountRow:
            return AccountRow(id="acc-1", name="A", cdp_port=0)

        monkeypatch.setattr("backend.db.accounts.get_account", _account)
        monkeypatch.setenv(COOKIE_KEY, "")
        monkeypatch.setenv(USER_ID_KEY, "")

        credential = await load_credential("acc-1", reader=_reader())

        assert credential.profile_bound is False
        assert credential.scopes == ()


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

        # ``is_pool_ready`` is now true, so the default profile seam would try a
        # real ``get_account``.  These tests are about the credential *rows*, so
        # the binding is pinned to "not bound" rather than left to a warning.
        async def _no_binding(account_id: str) -> str:
            return ""

        monkeypatch.setattr("backend.db.accounts.get_account_cdp_endpoint", _no_binding)

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


def _outreach_rows(**rows: str):
    async def _read(account_id: str) -> Mapping[str, str]:
        return dict(rows)

    return _read


class TestTheOutreachTierIsMechanismAndPolicy:
    """``xhs:outreach`` — the one scope a policy can withhold (§9.5).

    Mechanism answers "can this account log in"; policy answers "may it start
    conversations".  Two accounts with identical cookies get different scopes
    here, which is the discrimination the credential table could never make
    when everything was derived from the login alone.
    """

    async def test_the_same_mechanism_gets_different_scopes_under_different_policies(self):
        permitted = await load_credential(
            "acc-1",
            reader=_reader(**{COOKIE_KEY: VALID}),
            profile_reader=_binding(""),
            outreach_reader=_outreach_rows(
                **{MODE_KEY: OUTREACH_CONFIRMED, DAILY_PROACTIVE_CAP_KEY: "3"}
            ),
        )
        reply_only = await load_credential(
            "acc-1",
            reader=_reader(**{COOKIE_KEY: VALID}),
            profile_reader=_binding(""),
            outreach_reader=_outreach_rows(),
        )

        assert permitted.scopes == (XHS_READ_SCOPE, XHS_WRITE_SCOPE, XHS_OUTREACH_SCOPE)
        assert reply_only.scopes == (XHS_READ_SCOPE, XHS_WRITE_SCOPE)

    async def test_a_reply_only_account_keeps_write(self):
        """Answering someone who wrote first is not outreach — the default
        policy withholds ``xhs:outreach`` and nothing else."""
        credential = await load_credential(
            "acc-1",
            reader=_reader(**{COOKIE_KEY: VALID}),
            profile_reader=_binding(""),
        )

        assert credential.outreach == XhsOutreachPolicy(account_id="acc-1")
        assert credential.scopes == (XHS_READ_SCOPE, XHS_WRITE_SCOPE)

    async def test_policy_alone_grants_nothing(self):
        """A permission without a mechanism is a permission to be nobody.

        The outreach policy says this account *may* start conversations; it
        never says *as whom*.  Without a cookie or a bound profile there is no
        identity to act under, so the mechanism half of the ∧ still fails.
        """
        credential = await load_credential(
            "acc-1",
            reader=_reader(),
            profile_reader=_binding(""),
            outreach_reader=_outreach_rows(
                **{MODE_KEY: OUTREACH_CONFIRMED, DAILY_PROACTIVE_CAP_KEY: "3"}
            ),
        )

        assert credential.outreach.allows_proactive is True
        assert credential.scopes == ()

    async def test_the_cap_is_half_of_the_answer(self):
        """``confirmed_anyone`` with a zero budget still reaches nobody."""
        credential = await load_credential(
            "acc-1",
            reader=_reader(**{COOKIE_KEY: VALID}),
            profile_reader=_binding(""),
            outreach_reader=_outreach_rows(
                **{MODE_KEY: OUTREACH_CONFIRMED, DAILY_PROACTIVE_CAP_KEY: "0"}
            ),
        )

        assert credential.scopes == (XHS_READ_SCOPE, XHS_WRITE_SCOPE)

    async def test_granted_scopes_carries_the_policy_half(self):
        """The dispatcher's grant and the executor's credential stay one answer."""
        scopes = await granted_scopes(
            "acc-1",
            reader=_reader(**{COOKIE_KEY: VALID}),
            profile_reader=_binding(""),
            outreach_reader=_outreach_rows(
                **{MODE_KEY: OUTREACH_CONFIRMED, DAILY_PROACTIVE_CAP_KEY: "2"}
            ),
        )

        assert scopes == (XHS_READ_SCOPE, XHS_WRITE_SCOPE, XHS_OUTREACH_SCOPE)
