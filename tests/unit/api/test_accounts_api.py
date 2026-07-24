"""Tests for accounts API routes."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_crypto():
    """Ensure ENCRYPTION_KEY is set for tests."""
    from backend.db.crypto import generate_key

    os.environ["ENCRYPTION_KEY"] = generate_key()
    import backend.db.crypto as crypto_mod

    crypto_mod._fernet = None
    yield
    os.environ.pop("ENCRYPTION_KEY", None)
    crypto_mod._fernet = None


@pytest.fixture
def client():
    """Create a test client with the accounts router mounted + auth override."""
    from fastapi import FastAPI

    from backend.api.deps import get_current_user
    from backend.api.routes.accounts import router

    app = FastAPI()
    app.include_router(router, prefix="/api/accounts")

    async def _user():
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def test_list_accounts_empty(client):
    """GET /api/accounts returns empty list when no accounts exist."""
    with patch("backend.db.accounts.list_accounts", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = []
        resp = client.get("/api/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"] == []


def test_create_account(client):
    """POST /api/accounts creates a new account."""
    from backend.db.accounts import AccountRow

    mock_account = AccountRow(
        id="acc-1",
        name="Test Account",
        is_active=False,
        created_at="2026-01-01T00:00:00",
        owner_user_id="user-test",
    )

    with patch("backend.db.accounts.create_account", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_account
        resp = client.post("/api/accounts", json={"name": "Test Account", "is_active": False})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Test Account"


def test_create_account_empty_name(client):
    """POST /api/accounts with empty name returns validation error."""
    # ValidationError is an APIError(400) but without the error middleware,
    # FastAPI returns 500. Check that the endpoint raises the specific error.
    from backend.api.errors import ValidationError

    with pytest.raises(ValidationError):
        client.post("/api/accounts", json={"name": "  ", "is_active": False})


def test_delete_account(client):
    """DELETE /api/accounts/{id} removes an account."""
    from backend.db.accounts import AccountRow

    owned = AccountRow(
        id="acc-1",
        name="Test",
        is_active=False,
        owner_user_id="user-test",
    )
    with (
        patch(
            "backend.api.account_scope.get_account",
            new_callable=AsyncMock,
            return_value=owned,
        ),
        patch("backend.db.accounts.delete_account", new_callable=AsyncMock) as mock_del,
    ):
        mock_del.return_value = True
        resp = client.delete("/api/accounts/acc-1")

    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True
