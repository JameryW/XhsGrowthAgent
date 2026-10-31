"""Per-account outreach policy — who this account may reach out to, and how much.

The policy table §9.5 asked for.  ``XhsCredential.scopes`` derives from
*mechanism* (is there a cookie, is a browser profile bound) and that is all it
can derive from: it cannot express "this account is allowed to proactively DM
anyone", because permission to reach out is not a property of the credential —
two accounts with identical logins can be allowed different things.  This
module is the missing source: the three questions scope cannot answer, one
owner, per account.

1. **谁被允许触达** — :attr:`XhsOutreachPolicy.mode`.  Three values, and the
   middle one is the product default because it is what the platform already
   enforces informally: reply to whoever wrote to you (the inbound-peer
   whitelist), start nothing.  ``nobody`` suspends even replies;
   ``confirmed_anyone`` opens cold outreach, still one human confirmation per
   message.
2. **每账号每日上限** — :attr:`XhsOutreachPolicy.daily_proactive_cap`, the
   budget for *proactive* touches (a message to somebody who has not written
   first).  Replies are not proactive and do not spend it.
3. **是否只允许应答式触达** — :attr:`XhsOutreachPolicy.reply_only`, the
   question as a predicate: ``mode == inbound_only``.

Where a policy comes from, in the order consulted — the same precedence rule
:mod:`backend.services.xhs_credentials` established, for the same reasons:

1. **The account's own rows** in ``account_credentials`` (``XHS_OUTREACH_MODE``
   / ``XHS_OUTREACH_DAILY_PROACTIVE_CAP``).  A row that *carries a policy key*
   is a statement and is final: the deployment default is never consulted over
   it, not even when the account's own value is the restrictive one.  Falling
   through would let the deployment silently widen an account an operator
   narrowed.
2. **The deployment's declared environment** — ``XHS_OUTREACH_MODE`` /
   ``XHS_OUTREACH_DAILY_PROACTIVE_CAP``, plus the legacy switch
   ``XHS_ALLOW_OUTBOUND_DM`` as "the deployment opts into
   ``confirmed_anyone``".  That switch predates this model and was *global* —
   the only answer it could give was for every account at once.  It stays as
   the deployment default so an existing opt-in keeps meaning what it meant.
3. **The safe default**: ``inbound_only``, cap 0.  Replies work (the platform
   already allows answering someone who wrote first), nothing starts.

Fail-safe at every edge, and in one direction only: an unreadable store, a
malformed value, or an unknown mode name all land on *more* restriction, never
less.  A policy resolver must not invent permission the way a credential
resolver must not invent identity.

Reading is injectable (:class:`OutreachReader`) so the precedence rule can be
tested without a Postgres — not so the rule can be skipped.  The default reader
is the production read.

**Management writes (票 5ax).**  Until this slice the two keys could only be
written by hand into ``account_credentials``.  :func:`set_outreach_policy` and
:func:`clear_outreach_policy` are the validated write path: they accept only
the declared mode names / a non-negative integer cap, write only the keys the
caller named, and read the policy back so the caller sees the effective answer
rather than "saved".  Writes fail loudly (``OutreachPolicyStoreUnavailableError``)
when the account store is not available — the opposite of the read side's
fail-safe posture, because a management write that silently no-ops is worse
than an error: the operator would believe a suspension they never applied.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

logger = logging.getLogger("xhs_growth.services.xhs_outreach_policy")

__all__ = [
    "DAILY_PROACTIVE_CAP_KEY",
    "MODE_KEY",
    "OUTREACH_CONFIRMED",
    "OUTREACH_INBOUND",
    "OUTREACH_MODES",
    "OUTREACH_NOBODY",
    "OUTREACH_POLICY_KEYS",
    "OutreachPolicyStoreUnavailableError",
    "OutreachReader",
    "XhsOutreachPolicy",
    "clear_outreach_policy",
    "load_outreach_policy",
    "policy_from_values",
    "read_outreach_overrides",
    "set_outreach_policy",
]

#: ③ Nobody at all — even replies are suspended.  The operator's "stop touching
#: people" switch, not the default: the platform already allows replying to
#: whoever wrote first, and a resolver that defaults to silence would refuse
#: work the account may legitimately do.
OUTREACH_NOBODY = "nobody"

#: The safe default and the product rule: answer whoever wrote first (the
#: inbound-peer whitelist ``xhs_risk_gate`` maintains), start nothing.
OUTREACH_INBOUND = "inbound_only"

#: Cold outreach is permitted — still one human confirmation per message, still
#: under the daily cap.  "谁被允许触达" for this mode is *anyone*, gated per
#: call, because an allowlist of strangers is not a policy this product has.
OUTREACH_CONFIRMED = "confirmed_anyone"

OUTREACH_MODES: tuple[str, ...] = (OUTREACH_NOBODY, OUTREACH_INBOUND, OUTREACH_CONFIRMED)

#: Account-row keys.  The resolver never invents a key name of its own — same
#: allow-list discipline as ``XHS_CREDENTIAL_KEYS``.
MODE_KEY = "XHS_OUTREACH_MODE"
DAILY_PROACTIVE_CAP_KEY = "XHS_OUTREACH_DAILY_PROACTIVE_CAP"
OUTREACH_POLICY_KEYS: tuple[str, ...] = (MODE_KEY, DAILY_PROACTIVE_CAP_KEY)

#: Deployment default for ``daily_proactive_cap`` when the legacy
#: ``XHS_ALLOW_OUTBOUND_DM`` switch (or the mode env) opens cold outreach and
#: no cap is declared.  20 is not arbitrary: it is ``XHS_DM_DAILY_LIMIT``'s
#: default, which was the *effective* bound on outbound DMs before this model
#: existed.  An existing opt-in keeps meaning what it meant.
_LEGACY_CAP_DEFAULT = 20


@dataclass(frozen=True)
class XhsOutreachPolicy:
    """One account's answers to the three questions scope cannot express."""

    account_id: str = ""
    #: ③ / ① — one of :data:`OUTREACH_MODES`; see the module docstring.
    mode: str = OUTREACH_INBOUND
    #: ② — proactive touches allowed per UTC day.  Replies never spend it.
    daily_proactive_cap: int = 0

    @property
    def reply_only(self) -> bool:
        """③ — 是否只允许应答式触达."""
        return self.mode == OUTREACH_INBOUND

    @property
    def allows_engagement(self) -> bool:
        """Whether this account may touch anybody at all (including replies)."""
        return self.mode != OUTREACH_NOBODY

    @property
    def allows_proactive(self) -> bool:
        """Whether cold outreach is permitted *at all* — the budget half of ②.

        A zero cap is no budget, so ``confirmed_anyone`` with cap 0 still says
        no: mode answers "who", the cap answers "how much", and 0 of something
        is none of it.
        """
        return self.mode == OUTREACH_CONFIRMED and self.daily_proactive_cap > 0


def _parse_cap(raw: object) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _parse_mode(raw: object) -> str:
    text = str(raw or "").strip().lower()
    return text if text in OUTREACH_MODES else ""


def policy_from_values(
    account_id: str,
    values: Mapping[str, str],
    *,
    fallback: XhsOutreachPolicy | None = None,
) -> XhsOutreachPolicy:
    """Build the policy from one source's key-values.

    Per-field fallback, restrictive direction only: a malformed or unknown
    value does not fail the whole policy, and does not widen it either — the
    field lands on ``fallback``'s answer (the safe default when none is given).
    """
    base = fallback or XhsOutreachPolicy()
    mode = _parse_mode(values.get(MODE_KEY))
    cap_raw = values.get(DAILY_PROACTIVE_CAP_KEY)
    return XhsOutreachPolicy(
        account_id=(account_id or "").strip(),
        mode=mode or base.mode,
        daily_proactive_cap=(
            _parse_cap(cap_raw) if cap_raw is not None else base.daily_proactive_cap
        ),
    )


def _carries_policy(values: Mapping[str, str]) -> bool:
    """Whether a source says *anything* about policy.

    Presence of a policy key is the statement — the same "a row is a statement,
    an unset variable is not" rule the credential resolver draws.  Rows that
    merely carry other keys (a cookie, say) are silent on policy and fall
    through to the deployment default.
    """
    return any(key in values for key in OUTREACH_POLICY_KEYS)


OutreachReader = Callable[[str], Awaitable[Mapping[str, str]]]
"""How the account's own policy rows are fetched (injectable seam).

Same shape as ``xhs_credentials.CredentialReader``: the default is the real
database read, and the seam exists so a test can put a policy in front of the
resolver without a Postgres — not so a test can skip the precedence rule.
"""


async def _read_stored(account_id: str) -> Mapping[str, str]:
    """The default reader: this account's policy rows from ``account_credentials``.

    Same store the credential rows live in — a per-account key-value table, not
    a credential table with a policy column bolted on.  No pool means this
    deployment has no account store at all (``db/accounts`` is Postgres-only),
    which is a configuration fact, not a failure: the deployment default
    applies, exactly as it does for the credential.
    """
    from backend.db.pool import is_pool_ready

    if not is_pool_ready():
        return {}
    from backend.db.accounts import list_credentials

    rows = await list_credentials(account_id)
    return {row.key_name: row.value for row in rows if row.key_name in OUTREACH_POLICY_KEYS}


def _deployment_values() -> Mapping[str, str]:
    """The deployment's declared policy, read at call time.

    ``XHS_ALLOW_OUTBOUND_DM`` is the legacy switch: before this model it
    answered the question *globally* (its function took an ``account_id`` and
    ignored it).  It stays as "the deployment opts into ``confirmed_anyone``",
    which is what it always meant, and an account row can still narrow it.
    """
    import os

    values: dict[str, str] = {}

    mode_env = _parse_mode(os.environ.get(MODE_KEY, ""))
    if mode_env:
        values[MODE_KEY] = mode_env
    elif os.environ.get("XHS_ALLOW_OUTBOUND_DM", "").strip().lower() in ("1", "true", "yes"):
        values[MODE_KEY] = OUTREACH_CONFIRMED

    cap_env = os.environ.get(DAILY_PROACTIVE_CAP_KEY, "").strip()
    if cap_env:
        values[DAILY_PROACTIVE_CAP_KEY] = cap_env
    elif MODE_KEY in values:
        # An opt-in with no declared budget keeps its historical bound.
        values[DAILY_PROACTIVE_CAP_KEY] = str(_LEGACY_CAP_DEFAULT)

    return values


async def load_outreach_policy(
    account_id: str,
    *,
    reader: OutreachReader | None = None,
) -> XhsOutreachPolicy:
    """Resolve one account's outreach policy — or the honest safe default.

    Never raises.  A resolver that throws would leave the gate with no answer
    at all, and "no answer" must not become "proceed"; every fallback below
    lands on more restriction, never less.
    """
    account = (account_id or "").strip()
    safe = XhsOutreachPolicy(account_id=account)
    if account:
        try:
            stored = await (reader or _read_stored)(account)
        except Exception as exc:  # fail-safe: unknown is not permission
            logger.warning(
                "outreach policy read failed: account_id=%s err=%s: %s",
                account,
                type(exc).__name__,
                exc,
            )
            return safe
        if _carries_policy(stored):
            return policy_from_values(account, stored, fallback=safe)
    return policy_from_values(account, _deployment_values(), fallback=safe)


# ── Management write path (票 5ax) ───────────────────────────────────────────


class OutreachPolicyStoreUnavailableError(RuntimeError):
    """The account store cannot take a management write.

    Deliberately an error rather than a fallback: the read side may answer a
    broken store with the safe default (unknown is not permission), but a
    *write* that reports success while writing nothing would leave the operator
    believing a suspension they never applied.  The API maps this to 503.
    """


def _require_account(account_id: str) -> str:
    account = (account_id or "").strip()
    if not account:
        raise ValueError("account_id is required for an outreach policy write")
    return account


def _normalize_mode(mode: object) -> str:
    text = str(mode or "").strip().lower()
    if text not in OUTREACH_MODES:
        raise ValueError(
            f"unknown outreach mode {mode!r}; expected one of {', '.join(OUTREACH_MODES)}"
        )
    return text


def _validate_cap(daily_proactive_cap: object) -> int:
    if isinstance(daily_proactive_cap, bool) or not isinstance(daily_proactive_cap, int):
        raise ValueError(
            f"daily_proactive_cap must be a non-negative int (got {daily_proactive_cap!r})"
        )
    if daily_proactive_cap < 0:
        raise ValueError("daily_proactive_cap must be a non-negative int")
    return daily_proactive_cap


async def set_outreach_policy(
    account_id: str,
    *,
    mode: str | None = None,
    daily_proactive_cap: int | None = None,
) -> XhsOutreachPolicy:
    """Write the named policy keys and return the *effective* policy.

    Only the fields the caller passes are written — an omitted field keeps the
    account's existing answer (or the deployment default if it has none), which
    is the same per-field semantics the reader already applies.  A body that
    names nothing is refused: a management write that writes nothing is a
    caller mistake, not a no-op worth reporting as success.

    The return value is read back from the account store, so it is what the
    gates will see — not a reconstruction of the request.
    """
    from backend.db.pool import is_pool_ready

    account = _require_account(account_id)
    if mode is None and daily_proactive_cap is None:
        raise ValueError("set_outreach_policy needs at least one of mode / daily_proactive_cap")
    normalized_mode = _normalize_mode(mode) if mode is not None else None
    normalized_cap = _validate_cap(daily_proactive_cap) if daily_proactive_cap is not None else None
    if not is_pool_ready():
        raise OutreachPolicyStoreUnavailableError(
            "outreach policy write needs the account store (Postgres pool is not ready)"
        )

    from backend.db.accounts import upsert_credential

    if normalized_mode is not None:
        await upsert_credential(account, MODE_KEY, normalized_mode)
    if normalized_cap is not None:
        await upsert_credential(account, DAILY_PROACTIVE_CAP_KEY, str(normalized_cap))

    stored = await _read_store_for_write(account)
    if not _carries_policy(stored):
        raise OutreachPolicyStoreUnavailableError(
            f"outreach policy write did not persist for account {account!r}"
        )
    return policy_from_values(account, stored)


async def clear_outreach_policy(account_id: str) -> XhsOutreachPolicy:
    """Delete the account's two policy rows and return the effective policy.

    Removing the rows is what "clear" must mean: an upsert with an empty value
    would still be an account-level statement (see the module docstring), so
    the deployment default would never apply again.  Idempotent — clearing a
    policy that was never overridden removes nothing and still returns the
    effective answer.
    """
    from backend.db.pool import is_pool_ready

    account = _require_account(account_id)
    if not is_pool_ready():
        raise OutreachPolicyStoreUnavailableError(
            "outreach policy clear needs the account store (Postgres pool is not ready)"
        )

    from backend.db.accounts import delete_credential

    for key in OUTREACH_POLICY_KEYS:
        await delete_credential(account, key)
    # After the delete the account has no policy rows, so the deployment
    # default applies again — resolve it through the one owner of that rule.
    return await load_outreach_policy(account)


async def read_outreach_overrides(account_id: str) -> dict[str, str]:
    """The account's own policy rows — the ``overrides`` half of the GET payload.

    Displaying them is what makes a policy change auditable: "effective" alone
    cannot tell an override apart from the deployment default.  No pool means
    there is no account store (a configuration fact), so the honest answer is
    "no overrides"; an unreadable store is reported as unavailable rather than
    rendered as an empty override set.
    """
    from backend.db.pool import is_pool_ready

    account = (account_id or "").strip()
    if not account or not is_pool_ready():
        return {}
    try:
        return dict(await _read_stored(account))
    except Exception as exc:
        raise OutreachPolicyStoreUnavailableError(
            f"outreach policy rows unreadable for account {account!r}: {type(exc).__name__}: {exc}"
        ) from exc


async def _read_store_for_write(account_id: str) -> Mapping[str, str]:
    """Read the rows a write just touched, without the read side's fallback.

    ``load_outreach_policy`` would answer a failed read with the safe default,
    which after a successful write would claim a policy the account does not
    have.  A write's read-back must fail loudly instead.
    """
    try:
        return await _read_stored(account_id)
    except Exception as exc:
        raise OutreachPolicyStoreUnavailableError(
            f"outreach policy read-back failed for account {account_id!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
