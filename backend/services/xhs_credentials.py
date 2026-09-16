"""Account credential ownership — which account's credential, sourced from where.

P1c named this hole twice and declined to fill it in its own slice:

* ``tools/xhs/trending.py`` — *"Credential plumbing (which account's cookie,
  sourced from where) belongs to P2a"*, because ``_get_client`` built an
  ``XHSClient`` with no cookie at all, so every HTTP read raised and the three
  read capabilities could only ever report "无法读取" .
* ``creator_agent/execution.py`` — *"nothing in this repo owns a publish grant
  yet"*, which is why the publish dispatcher passed ``granted_scopes=None``
  (the Gateway reads that as *unchecked*) and ``xhs.publish``'s declared
  ``auth_scope`` was decorative.

This module is that owner.  One answer, two readers: the cookie is handed to
the HTTP client, the scopes are handed to the Tool Gateway.  They cannot
disagree, because both are read off the same :class:`XhsCredential`.

Where the credential comes from, in the order it is consulted:

1. **The account's own rows** in ``account_credentials`` (``XHS_COOKIE`` /
   ``XHS_USER_ID``).  An account-specific credential is *final*: when the
   account has one, the deployment default is never consulted, not even when
   the account's own credential is unusable.  Falling through would read and
   publish as a different identity than the one the caller asked for, which is
   the one failure a credential resolver must not invent.
2. **The deployment credential** — ``XHS_COOKIE`` / ``XHS_USER_ID`` from the
   environment (``.env.example`` has declared them since the file existed;
   this is the slice that reads them).  This is what a single-account
   deployment means, and it is the fallback for a blank account id (the CLI
   and ``xhs.trending``'s default ``account_id=""``).

The two sources differ on what an empty value means, deliberately: **a row is
a statement, an unset variable is not.**  A row that exists but carries nothing
is a cleared credential — the account's answer, so it stays final.  An empty
``XHS_COOKIE`` says nobody configured a deployment credential, which is not an
answer at all, so ``source`` comes back empty rather than naming a source that
supplied nothing.

Fail-closed at the boundary, deliberately: a reader that *raises* answers
"unknown", and unknown is not permission to act as somebody else — so it yields
an unusable credential with no fallback to the deployment default.  A missing
account store is a different thing from an unreadable one: no pool means the
deployment has no per-account credentials at all (the same distinction
``db/creator_agent`` draws with ``is_pool_ready()``), which is a configuration
fact and not a failure, so the deployment credential still applies.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

logger = logging.getLogger("xhs_growth.services.xhs_credentials")

__all__ = [
    "COOKIE_KEY",
    "SOURCE_ACCOUNT",
    "SOURCE_ENVIRONMENT",
    "USER_ID_KEY",
    "XHS_CREDENTIAL_KEYS",
    "XHS_READ_SCOPE",
    "XHS_WRITE_SCOPE",
    "CredentialReader",
    "XhsCredential",
    "granted_scopes",
    "load_credential",
]

# The scope vocabulary lives next to the owner so the executor's precondition
# and the Gateway's requirement are the same string by construction.  It is a
# mirror of ``catalog``'s declarations, and
# ``tests/unit/services/test_xhs_credentials.py`` pins the two together so a
# rename on either side cannot drift.
XHS_READ_SCOPE = "xhs:read"
XHS_WRITE_SCOPE = "xhs:write"

COOKIE_KEY = "XHS_COOKIE"
USER_ID_KEY = "XHS_USER_ID"
# The keys this resolver reads.  Same allow-list the console manages and
# ``db.system_config`` keeps out of ``account_credentials``; the resolver never
# invents a key name of its own.
XHS_CREDENTIAL_KEYS: tuple[str, ...] = (COOKIE_KEY, USER_ID_KEY)

SOURCE_ACCOUNT = "account"
SOURCE_ENVIRONMENT = "environment"

CredentialReader = Callable[[str], Awaitable[Mapping[str, str]]]
"""How the account's own credential rows are fetched (injectable seam).

The default is the real database read.  It is a seam so a test can put a
credential in front of the resolver without a Postgres, not so a test can skip
the precedence rule — every decision this module makes is applied to whatever
the reader returns.
"""


@dataclass(frozen=True)
class XhsCredential:
    """One account's XHS credential, plus where it came from.

    ``source`` is carried rather than inferred from an empty ``account_id``,
    because "the account had no credential of its own" and "the account was not
    named at all" call for different operator answers, and a caller reading the
    result should not have to guess which one it is looking at.
    """

    account_id: str = ""
    cookie: str = ""
    user_id: str = ""
    source: str = ""

    @property
    def usable(self) -> bool:
        """Present *and* well formed — the availability half of the answer.

        A cookie that parses but carries no login material (``XHSClient``
        checks the same thing via ``XHSCookieParser.is_valid``) is not a
        credential: handing it over would put the HTTP client into the
        "configured, but every call fails" state that ``can_read`` exists to
        distinguish from "not configured".
        """
        if not self.cookie:
            return False
        from backend.services.xhs_signature import XHSCookieParser

        return XHSCookieParser.is_valid(self.cookie)

    @property
    def scopes(self) -> tuple[str, ...]:
        """What this credential entitles its holder to.

        One rule, both scopes: the credential *is* the account's identity
        evidence, and it is the same QR login that writes it and that binds the
        account's browser profile.  Read and write are granted together on
        purpose — deriving the write scope from "a browser is reachable" would
        make the grant flip whenever a Chrome process is stopped, and
        reachability is not entitlement.  Reachability keeps its existing home
        (the publisher resolves the account's endpoint; the tool fails loudly
        when the browser is not there).
        """
        if not self.usable:
            return ()
        return (XHS_READ_SCOPE, XHS_WRITE_SCOPE)


async def _read_stored(account_id: str) -> Mapping[str, str]:
    """The default reader: this account's rows from ``account_credentials``.

    No pool means this deployment has no account store (``db/accounts`` is
    Postgres-only, with no memory fallback), so there is nothing to read and
    nothing to distrust — an empty answer, distinct from the failure the
    boundary below guards against.
    """
    from backend.db.pool import is_pool_ready

    if not is_pool_ready():
        return {}
    from backend.db.accounts import list_credentials

    rows = await list_credentials(account_id)
    return {row.key_name: row.value for row in rows if row.key_name in XHS_CREDENTIAL_KEYS}


async def _read_deployment() -> Mapping[str, str]:
    """The deployment credential, read at call time.

    ``Settings()`` is constructed per call so a process that seeds ``.env``
    later (or a test that sets ``XHS_COOKIE``) is honoured without a restart;
    the same reason ``tools/xhs`` builds its ``Settings`` inside the factory.
    """
    from backend.config.settings import Settings

    platform = Settings().platform
    return {COOKIE_KEY: platform.cookie, USER_ID_KEY: platform.user_id}


def _credential(account_id: str, values: Mapping[str, str], source: str) -> XhsCredential:
    return XhsCredential(
        account_id=account_id,
        cookie=str(values.get(COOKIE_KEY) or "").strip(),
        user_id=str(values.get(USER_ID_KEY) or "").strip(),
        source=source,
    )


def _carries(values: Mapping[str, str]) -> bool:
    """Whether a source supplied a value at all.

    An *empty* environment variable is not a statement — nobody set a
    deployment credential — so it names no source.  A *row* in the account's
    credential table is a statement, even when its value is empty: it says this
    account has a credential slot, and a cleared credential must not silently
    become the deployment's identity.
    """
    return any(str(values.get(key) or "").strip() for key in XHS_CREDENTIAL_KEYS)


async def load_credential(
    account_id: str,
    *,
    reader: CredentialReader | None = None,
) -> XhsCredential:
    """Resolve one account's credential, or the honest absence of one.

    Never raises: a caller that cannot state which credential it holds is not
    entitled to assume one, and both readers of this answer (the HTTP client
    and the Tool Gateway) need an answer rather than an exception.
    """
    account = (account_id or "").strip()
    if account:
        try:
            stored = await (reader or _read_stored)(account)
        except Exception as exc:  # fail-closed: unknown is not permission
            logger.warning(
                "account credential read failed: account_id=%s err=%s: %s",
                account,
                type(exc).__name__,
                exc,
            )
            return XhsCredential(account_id=account)
        if stored:
            return _credential(account, stored, SOURCE_ACCOUNT)
    try:
        deployment = await _read_deployment()
    except Exception as exc:  # a missing deployment credential is simply absent
        logger.warning("deployment credential read failed: err=%s: %s", type(exc).__name__, exc)
        return XhsCredential(account_id=account)
    return _credential(account, deployment, SOURCE_ENVIRONMENT if _carries(deployment) else "")


async def granted_scopes(
    account_id: str,
    *,
    reader: CredentialReader | None = None,
) -> tuple[str, ...]:
    """The scopes this account holds — the credential answer, as a grant."""
    return (await load_credential(account_id, reader=reader)).scopes
