"""Account isolation helpers — single-account + owner checks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.account_scope import (
    is_all_accounts_sentinel,
    require_owned_account,
    resolve_required_account_id,
)
from backend.api.errors import AccountNotFoundError, ValidationError
from backend.db.accounts import AccountRow


def _account(aid: str, owner: str, *, active: bool = False) -> AccountRow:
    return AccountRow(
        id=aid,
        name=f"name-{aid}",
        is_active=active,
        owner_user_id=owner,
    )


def test_all_accounts_sentinels_rejected():
    assert is_all_accounts_sentinel("__all_accounts__")
    assert is_all_accounts_sentinel("ALL")
    assert is_all_accounts_sentinel("__all__")
    assert not is_all_accounts_sentinel("acct-1")


@pytest.mark.asyncio
async def test_require_owned_account_denies_foreign_owner():
    with (
        patch(
            "backend.api.account_scope.get_account",
            new=AsyncMock(return_value=_account("a1", "user-u")),
        ),
        pytest.raises(AccountNotFoundError),
    ):
        await require_owned_account("user-v", "a1")


@pytest.mark.asyncio
async def test_require_owned_account_allows_owner():
    acc = _account("a1", "user-u")
    with patch("backend.api.account_scope.get_account", new=AsyncMock(return_value=acc)):
        out = await require_owned_account("user-u", "a1")
    assert out.id == "a1"


@pytest.mark.asyncio
async def test_resolve_rejects_all_accounts_sentinel():
    with pytest.raises(ValidationError) as ei:
        await resolve_required_account_id("user-u", "__all_accounts__")
    assert (
        "all-accounts" in str(ei.value.message).lower()
        or "aggregate" in str(ei.value.message).lower()
    )


@pytest.mark.asyncio
async def test_resolve_defaults_to_owned_active():
    active = _account("a-active", "user-u", active=True)
    with (
        patch(
            "backend.api.account_scope.get_active_account",
            new=AsyncMock(return_value=active),
        ),
        patch(
            "backend.api.account_scope.require_owned_account",
            new=AsyncMock(return_value=active),
        ),
    ):
        out = await resolve_required_account_id("user-u", None)
    assert out == "a-active"


@pytest.mark.asyncio
async def test_assert_thread_owned_mismatch():
    from backend.api.account_scope import assert_thread_owned
    from backend.api.errors import WorkflowNotFoundError

    wf = SimpleNamespace(account_id="acc-a", thread_id="t1")
    with (
        patch("backend.db.workflows.get_workflow", new=AsyncMock(return_value=wf)),
        patch(
            "backend.api.account_scope.require_owned_account",
            new=AsyncMock(return_value=_account("acc-a", "user-u")),
        ),
        pytest.raises(WorkflowNotFoundError),
    ):
        await assert_thread_owned("user-u", "t1", account_id="acc-b")
