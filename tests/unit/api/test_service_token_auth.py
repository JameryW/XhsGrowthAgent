"""Tests for service-token auth (deps) and the account_scope service bypass."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.api import deps
from backend.api.account_scope import (
    assert_thread_owned,
    require_owned_account,
    resolve_required_account_id,
)
from backend.api.errors import AccountNotFoundError, TokenInvalidError, WorkflowNotFoundError
from backend.db.accounts import AccountRow
from backend.db.workflows import WorkflowRow


def _auth(token: str) -> str:
    return f"Bearer {token}"


class TestServiceTokenAuth:
    async def test_service_token_accepted_when_configured(self, monkeypatch):
        monkeypatch.setenv("XHS_SERVICE_TOKEN", "mesh-secret")
        user = await deps.get_current_user(_auth("mesh-secret"))
        assert user == {"id": "service:omp", "username": "omp-service", "service": True}
        assert deps.is_service_identity(user)

    async def test_service_token_rejected_when_not_configured(self, monkeypatch):
        monkeypatch.delenv("XHS_SERVICE_TOKEN", raising=False)
        with pytest.raises(TokenInvalidError):
            await deps.get_current_user(_auth("mesh-secret"))

    async def test_wrong_service_token_rejected(self, monkeypatch):
        monkeypatch.setenv("XHS_SERVICE_TOKEN", "mesh-secret")
        with pytest.raises(TokenInvalidError):
            await deps.get_current_user(_auth("wrong"))

    async def test_user_jwt_still_accepted(self, monkeypatch):
        monkeypatch.delenv("XHS_SERVICE_TOKEN", raising=False)
        from backend.api.auth import generate_token

        issued = generate_token("user-1", "tester")
        user = await deps.get_current_user(_auth(issued.token))
        assert user == {"id": "user-1", "username": "tester"}
        assert not deps.is_service_identity(user)

    async def test_optional_user_accepts_service_token(self, monkeypatch):
        monkeypatch.setenv("XHS_SERVICE_TOKEN", "mesh-secret")
        user = await deps.get_optional_user(_auth("mesh-secret"))
        assert user is not None and user["id"] == "service:omp"
        assert await deps.get_optional_user(_auth("nope")) is None
        assert await deps.get_optional_user(None) is None


@pytest.fixture
def owned_account():
    return AccountRow(id="acc-1", name="acc-1", is_active=True, owner_user_id="user-test")


class TestAccountScopeServiceBypass:
    async def test_require_owned_account_bypasses_owner_for_service(self, owned_account):
        with patch(
            "backend.api.account_scope.get_account",
            new_callable=AsyncMock,
            return_value=owned_account,
        ):
            account = await require_owned_account(deps.SERVICE_USER_ID, "acc-1")
        assert account.id == "acc-1"

    async def test_require_owned_account_still_404s_foreign_user(self, owned_account):
        with (
            patch(
                "backend.api.account_scope.get_account",
                new_callable=AsyncMock,
                return_value=owned_account,
            ),
            pytest.raises(AccountNotFoundError),
        ):
            await require_owned_account("someone-else", "acc-1")

    async def test_require_owned_account_404s_missing_account_even_for_service(self):
        with (
            patch(
                "backend.api.account_scope.get_account",
                new_callable=AsyncMock,
                return_value=None,
            ),
            pytest.raises(AccountNotFoundError),
        ):
            await require_owned_account(deps.SERVICE_USER_ID, "ghost")

    async def test_resolve_defaults_across_accounts_for_service(self, owned_account):
        with (
            patch(
                "backend.api.account_scope.get_active_account",
                new_callable=AsyncMock,
                return_value=owned_account,
            ) as active_mock,
        ):
            resolved = await resolve_required_account_id(deps.SERVICE_USER_ID, None)
        assert resolved == "acc-1"
        # Service resolves across accounts: no owner filter applied.
        assert active_mock.await_args.kwargs["owner_user_id"] is None

    async def test_assert_thread_owned_bypasses_owner_for_service(self, owned_account):
        row = WorkflowRow(thread_id="t-1", account_id="acc-1")
        with (
            patch(
                "backend.db.workflows.get_workflow",
                new_callable=AsyncMock,
                return_value=row,
            ),
            patch(
                "backend.api.account_scope.get_account",
                new_callable=AsyncMock,
                return_value=owned_account,
            ),
        ):
            assert await assert_thread_owned(deps.SERVICE_USER_ID, "t-1") == "acc-1"

    async def test_assert_thread_owned_tolerates_missing_row_for_service(self):
        with patch(
            "backend.db.workflows.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            assert await assert_thread_owned(deps.SERVICE_USER_ID, "t-1") == ""
            with pytest.raises(WorkflowNotFoundError):
                await assert_thread_owned("user-test", "t-1")
