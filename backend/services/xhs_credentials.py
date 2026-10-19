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

Scopes are **not** one grant, because the two capabilities do not share a
mechanism.  Reads go through the HTTP client, whose identity *is* the cookie.
Writes go through the account's own browser: ``XHSPublisher`` is constructed
with ``cookie=""`` and drives CDP, so a publish can legitimately succeed for an
account whose cookie is stale or absent.  A single "has a cookie" rule would
refuse publishes the deployment can actually perform — the state
``.env.example`` describes — so the credential carries one more fact, whether a
browser profile is bound to the account (or, for a blank account id, declared by
the deployment), and the write scope is granted on either mechanism.

And one tier is **mechanism ∧ policy** (§9.5): proactive outreach needs the
write mechanism *and* the account's own permission to reach out, which comes
from :mod:`backend.services.xhs_outreach_policy`.  Two accounts with identical
logins can be allowed different things there — the question "may this account
proactively DM anyone" was never one a credential could answer.  The policy
rides the same :class:`XhsCredential` so the two readers — scopes to the
Gateway, cookie to the client — cannot disagree about it either.
:attr:`XhsCredential.scopes` states the rule.

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
from dataclasses import dataclass, field

from backend.services.xhs_outreach_policy import (
    OutreachReader,
    XhsOutreachPolicy,
    load_outreach_policy,
)

logger = logging.getLogger("xhs_growth.services.xhs_credentials")

__all__ = [
    "COOKIE_KEY",
    "SOURCE_ACCOUNT",
    "SOURCE_ENVIRONMENT",
    "USER_ID_KEY",
    "XHS_CREDENTIAL_KEYS",
    "XHS_OUTREACH_SCOPE",
    "XHS_READ_SCOPE",
    "XHS_WRITE_SCOPE",
    "CredentialReader",
    "ProfileReader",
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
#: The proactive tier.  Derived from **mechanism ∧ policy** — the only entry in
#: the vocabulary that a policy can withhold from an account whose mechanism is
#: perfect, because "logged in" was never the question it answers.  No catalog
#: capability declares it yet (engagement tools stay unregistered while
#: §9.4 says agents must not reach out); ``test_xhs_credentials`` pins that
#: deliberate absence so registration forces the decision.
XHS_OUTREACH_SCOPE = "xhs:outreach"

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

ProfileReader = Callable[[str], Awaitable[str]]
"""How "does this account have a browser profile bound?" is answered (seam).

The default is ``db.accounts.get_account_cdp_endpoint``, which answers with the
account's CDP endpoint or ``""``.  The seam returns the endpoint and this module
immediately reduces it to a bool: the *binding* is what a grant is made of, the
URL is reachability, and reachability is not entitlement — see
:attr:`XhsCredential.scopes`.
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
    # Whether a browser profile is bound to this account — the second
    # entitlement input, and the only one that does not come from the cookie
    # rows.  A bool rather than the endpoint on purpose: a stored URL invites
    # "the URL is non-empty, so the browser is up", which is the confusion
    # :attr:`scopes` exists to avoid.
    profile_bound: bool = False
    # The third entitlement input, and the only one that is not a mechanism:
    # policy says *whether this account may reach out*, which no amount of
    # logged-in-ness implies.  Resolved by ``load_credential`` alongside the
    # rest so the two readers of this object cannot disagree about it.
    outreach: XhsOutreachPolicy = field(default_factory=XhsOutreachPolicy)

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

        Two capabilities, two mechanisms, and then one tier that is **mechanism
        ∧ policy** — the table stopped being derivable from mechanism alone
        when "this account may proactively reach out" became a question, which
        the catalog cannot answer and a login cannot imply (§9.5):

        * ``xhs:read`` needs the cookie.  Every read capability builds an
          ``XHSClient`` whose identity *is* that cookie; without one there is no
          author to make the request as.
        * ``xhs:write`` needs *either* mechanism.  The publish path constructs
          ``XHSPublisher(cookie="")`` and drives the account's own browser over
          CDP, so a bound profile is sufficient there; the comment/DM path still
          posts over HTTP and is covered by the cookie.
        * ``xhs:outreach`` needs the write mechanism **and**
          :attr:`outreach`'s permission.  Two accounts with identical logins
          can be allowed different things here, and a reply-only account — the
          default — does not lose ``xhs:write`` for it: answering someone who
          wrote first is not outreach.

        The profile half is **binding, not reachability**.  ``profile_bound``
        records that the account has a CDP port bound to it; it never records
        that the browser answers.  Probing would make the same confirmation
        succeed or fail depending on whether a Chrome process happens to be
        running, and the Gateway would report that as *"not authorized"* — a
        false statement about the grant.  Whether the browser is up stays where
        it already lived: the publisher resolves the endpoint and the tool fails
        loudly (``cdp_unavailable``) when it is not there.

        Erring generous on the write scope is the safe direction to be wrong in:
        the bound profile is this account's own browser (or, when no account was
        named, the one the deployment declared), so a publish through it acts as
        the identity the caller named, which is what the grant is about.  It
        lends nobody a read — and policy never lends a mechanism: an account
        allowed outreach without a login still gets no scope, because there is
        nobody to reach out *as*.
        """
        scopes: list[str] = []
        if self.usable:
            scopes.append(XHS_READ_SCOPE)
        if self.usable or self.profile_bound:
            scopes.append(XHS_WRITE_SCOPE)
            if self.outreach.allows_proactive:
                scopes.append(XHS_OUTREACH_SCOPE)
        return tuple(scopes)


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


async def _read_bound_profile(account_id: str) -> str:
    """The default seam: the browser this identity may publish through, or ``""``.

    Two sources, and which one applies is the same question the cookie rule
    already answers:

    * **A named account** — its own CDP port (``db.accounts`` per-account
      binding).  ``get_account_cdp_endpoint`` already collapses every way of not
      having one — no pool, unknown account, ``cdp_port <= 0``, and its own
      failed read — to ``""``.  That collapse is *wrong* for the credential rows
      above (an unreadable store is not an empty one) and *right* here: for a
      binding, "could not tell" and "not bound" must give the same answer, and
      that answer is the one that denies a write.
    * **A blank account id** — the deployment's *declared* endpoint
      (``XHS_CDP_ENDPOINT``), the counterpart of ``XHS_COOKIE``: it is what a
      single-account deployment means, and it is the only answer a call with no
      account to look up can have.  Declared, never probed: the publisher has a
      reachability probe of its own for its fallback, and borrowing that answer
      would let the grant flip whenever a Chrome process stops.
    """
    if not account_id:
        from backend.config.settings import Settings

        return str(Settings().platform.cdp_endpoint or "").strip()
    from backend.db.accounts import get_account_cdp_endpoint

    return await get_account_cdp_endpoint(account_id)


async def _bound_profile(account_id: str, reader: ProfileReader | None) -> bool:
    """Whether a browser profile is bound to this account — one fact, one read.

    Resolved separately from the cookie rows instead of nested inside their
    precedence, because the two answer different questions: an unreadable
    credential store says nothing about whether this account has a browser, and
    the identity rule for cookies (never borrow the deployment's) has nothing to
    say about a profile that already belongs to the account.  A read that raises
    is still fail-closed — an unknown binding denies the write.
    """
    try:
        answer = await (reader or _read_bound_profile)(account_id)
    except Exception as exc:
        logger.warning(
            "account profile binding read failed: account_id=%s err=%s: %s",
            account_id,
            type(exc).__name__,
            exc,
        )
        return False
    return bool(str(answer or "").strip())


async def _read_deployment() -> Mapping[str, str]:
    """The deployment credential, read at call time.

    ``Settings()`` is constructed per call so a process that seeds ``.env``
    later (or a test that sets ``XHS_COOKIE``) is honoured without a restart;
    the same reason ``tools/xhs`` builds its ``Settings`` inside the factory.
    """
    from backend.config.settings import Settings

    platform = Settings().platform
    return {COOKIE_KEY: platform.cookie, USER_ID_KEY: platform.user_id}


def _credential(
    account_id: str,
    values: Mapping[str, str],
    source: str,
    *,
    profile_bound: bool = False,
    outreach: XhsOutreachPolicy | None = None,
) -> XhsCredential:
    return XhsCredential(
        account_id=account_id,
        cookie=str(values.get(COOKIE_KEY) or "").strip(),
        user_id=str(values.get(USER_ID_KEY) or "").strip(),
        source=source,
        profile_bound=profile_bound,
        outreach=outreach or XhsOutreachPolicy(account_id=account_id),
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
    profile_reader: ProfileReader | None = None,
    outreach_reader: OutreachReader | None = None,
) -> XhsCredential:
    """Resolve one account's credential, or the honest absence of one.

    Never raises: a caller that cannot state which credential it holds is not
    entitled to assume one, and both readers of this answer (the HTTP client
    and the Tool Gateway) need an answer rather than an exception.

    The profile binding is resolved first and carried into *every* answer below,
    including the refusals, because it is the one input that does not come from
    the cookie rows and therefore survives their failure.  A blank account id
    does not skip it: with no account to look up, the answer is the deployment's
    own declaration (``XHS_CDP_ENDPOINT``) — the same "a blank id means the
    deployment" rule the cookie source already follows.

    The outreach policy rides the same answer for the same reason the scopes
    do: ``granted_scopes`` and the executor must not disagree about whether
    this account may reach out.  It has its own source and its own precedence
    (see :mod:`backend.services.xhs_outreach_policy`) and never raises — a
    policy read that fails lands on the safe default, which withholds rather
    than grants.
    """
    account = (account_id or "").strip()
    profile_bound = await _bound_profile(account, profile_reader)
    outreach = await load_outreach_policy(account, reader=outreach_reader)
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
            return XhsCredential(account_id=account, profile_bound=profile_bound, outreach=outreach)
        if stored:
            return _credential(
                account,
                stored,
                SOURCE_ACCOUNT,
                profile_bound=profile_bound,
                outreach=outreach,
            )
    try:
        deployment = await _read_deployment()
    except Exception as exc:  # a missing deployment credential is simply absent
        logger.warning("deployment credential read failed: err=%s: %s", type(exc).__name__, exc)
        return XhsCredential(account_id=account, profile_bound=profile_bound, outreach=outreach)
    return _credential(
        account,
        deployment,
        SOURCE_ENVIRONMENT if _carries(deployment) else "",
        profile_bound=profile_bound,
        outreach=outreach,
    )


async def granted_scopes(
    account_id: str,
    *,
    reader: CredentialReader | None = None,
    profile_reader: ProfileReader | None = None,
    outreach_reader: OutreachReader | None = None,
) -> tuple[str, ...]:
    """The scopes this account holds — the credential answer, as a grant."""
    credential = await load_credential(
        account_id,
        reader=reader,
        profile_reader=profile_reader,
        outreach_reader=outreach_reader,
    )
    return credential.scopes
