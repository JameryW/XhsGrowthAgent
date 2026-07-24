"""Account-level isolation helpers for private API routes.

Rules (product contract):
- Every private data query is scoped to **exactly one** XHS account.
- Aggregate sentinels (``__all__``, ``all``, ``__all_accounts__``) are rejected.
- Console users only access accounts they own (``owner_user_id``).
- Cross-account / cross-owner access returns 404 (no existence oracle).
"""

from __future__ import annotations

from typing import Any

from backend.api.deps import SERVICE_USER_ID
from backend.api.errors import AccountNotFoundError, ValidationError, WorkflowNotFoundError
from backend.db.accounts import AccountRow, get_account, get_active_account, list_accounts

# Frontend used ``__all_accounts__``; also accept short forms and reject all.
_ALL_ACCOUNT_SENTINELS = frozenset(
    {
        "__all__",
        "all",
        "*",
        "__all_accounts__",
        "all_accounts",
        "全部账号",
    }
)


def is_all_accounts_sentinel(value: str | None) -> bool:
    raw = (value or "").strip().lower()
    return raw in {s.lower() for s in _ALL_ACCOUNT_SENTINELS}


def _is_service(user_id: str) -> bool:
    """Trusted in-mesh callers (omp bridge/extension) bypass owner checks."""

    return user_id == SERVICE_USER_ID


async def require_owned_account(user_id: str, account_id: str) -> AccountRow:
    """Return account if it exists and is owned by ``user_id``; else 404.

    The service identity only requires the account to exist — in-mesh
    callers act across accounts by design.
    """
    uid = (user_id or "").strip()
    aid = (account_id or "").strip()
    if not uid:
        raise ValidationError("user", "authenticated user is required")
    if not aid or aid.lower() == "default" or is_all_accounts_sentinel(aid):
        raise ValidationError("account_id", "a concrete account_id is required")
    account = await get_account(aid)
    if account is None:
        raise AccountNotFoundError(aid)
    if not _is_service(uid) and (account.owner_user_id or "").strip() != uid:
        raise AccountNotFoundError(aid)
    return account


async def resolve_required_account_id(
    user_id: str,
    account_id: str | None,
    *,
    default_to_active: bool = True,
) -> str:
    """Resolve a single owned account id; never returns a global/all scope."""
    uid = (user_id or "").strip()
    if not uid:
        raise ValidationError("user", "authenticated user is required")

    raw = (account_id or "").strip()
    if is_all_accounts_sentinel(raw):
        raise ValidationError(
            "account_id",
            "all-accounts aggregate is disabled; pass a concrete account_id",
        )
    if raw and raw.lower() != "default":
        account = await require_owned_account(uid, raw)
        return account.id

    if not default_to_active:
        raise ValidationError("account_id", "account_id is required")

    # The service identity is not tied to one console user; resolve across
    # all accounts instead of an owner-filtered set.
    owner_filter = None if _is_service(uid) else uid
    active = await get_active_account(owner_user_id=owner_filter)
    if active is not None:
        return active.id

    owned = await list_accounts(owner_user_id=owner_filter)
    if owned:
        return owned[0].id

    raise ValidationError(
        "account_id",
        "no owned account available; create an account first",
    )


async def assert_thread_owned(
    user_id: str,
    thread_id: str,
    account_id: str | None = None,
) -> str:
    """Ensure workflow exists and belongs to an account owned by the user.

    Returns the workflow's account_id. Optional ``account_id`` must match when set.
    The service identity skips the owner check but still resolves the row
    when it exists (a missing row is not an error for in-mesh callers).
    """
    tid = (thread_id or "").strip()
    if not tid:
        raise ValidationError("thread_id", "thread_id is required")

    from backend.db.workflows import get_workflow

    row = await get_workflow(tid)
    if row is None:
        if _is_service(user_id):
            return ""
        raise WorkflowNotFoundError(tid)

    owner_account = (row.account_id or "").strip()
    if not owner_account:
        if _is_service(user_id):
            return ""
        raise WorkflowNotFoundError(tid)

    await require_owned_account(user_id, owner_account)

    requested = (account_id or "").strip()
    if requested and not is_all_accounts_sentinel(requested) and requested != owner_account:
        # Hide cross-account threads as not found.
        raise WorkflowNotFoundError(tid)

    return owner_account


async def assert_note_owned(user_id: str, account_id: str, note_id: str) -> Any:
    """Note must exist under an account the user owns."""
    from backend.api.errors import CreatorNoteNotFoundError
    from backend.db.creator_stats import get_note_stats

    account = await require_owned_account(user_id, account_id)
    nid = (note_id or "").strip()
    if not nid:
        raise ValidationError("note_id", "note_id is required")
    note = await get_note_stats(account.id, nid)
    if note is None:
        raise CreatorNoteNotFoundError(account.id, nid)
    return note


def account_to_public_dict(account: AccountRow) -> dict[str, Any]:
    """Serialize account for API responses (includes owner for debugging/UI)."""
    return {
        "id": account.id,
        "name": account.name,
        "is_active": account.is_active,
        "created_at": account.created_at,
        "updated_at": getattr(account, "updated_at", None),
        "chrome_profile_path": account.chrome_profile_path,
        "cdp_port": account.cdp_port,
        "niche": account.niche,
        "niche_source": account.niche_source,
        "owner_user_id": account.owner_user_id,
    }


__all__ = [
    "assert_note_owned",
    "assert_thread_owned",
    "account_to_public_dict",
    "is_all_accounts_sentinel",
    "require_owned_account",
    "resolve_required_account_id",
]
