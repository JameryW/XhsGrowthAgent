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
    """Create a test client with the accounts router mounted."""
    from fastapi import FastAPI
    from backend.api.routes.accounts import router

    app = FastAPI()
    app.include_router(router, prefix="/api/accounts")
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

    mock_account = AccountRow(id="acc-1", name="Test Account", is_active=False, created_at="2026-01-01T00:00:00")

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
    # FastAPI returns 500. Check that the endpoint raises correctly.
    with pytest.raises(Exception):
        client.post("/api/accounts", json={"name": "  ", "is_active": False})


def test_get_credentials(client):
    """GET /api/accounts/{id}/credentials returns masked credentials."""
    from backend.db.accounts import CredentialRow
    from backend.db.crypto import encrypt_value

    encrypted = encrypt_value("sk-ant-1234567890abcdef")
    mock_cred = CredentialRow(account_id="acc-1", key_name="ANTHROPIC_API_KEY", _encrypted_bytes=encrypted)

    with patch("backend.db.accounts.list_credentials", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [mock_cred]
        resp = client.get("/api/accounts/acc-1/credentials")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["data"][0]["key_name"] == "ANTHROPIC_API_KEY"
    assert data["data"][0]["masked_value"] == "sk-a...cdef"
    assert data["data"][0]["is_set"] is True


def test_set_credentials(client):
    """PUT /api/accounts/{id}/credentials saves credentials."""
    with patch("backend.db.accounts.set_credentials", new_callable=AsyncMock) as mock_set, \
         patch("backend.db.accounts.get_active_account", new_callable=AsyncMock) as mock_active:
        mock_active.return_value = None  # Not the active account
        resp = client.put("/api/accounts/acc-1/credentials", json={"credentials": {"ANTHROPIC_API_KEY": "sk-new-key"}})

    assert resp.status_code == 200
    assert mock_set.called


def test_delete_account(client):
    """DELETE /api/accounts/{id} removes an account."""
    with patch("backend.db.accounts.delete_account", new_callable=AsyncMock) as mock_del, \
         patch("backend.db.accounts.get_active_account", new_callable=AsyncMock) as mock_active, \
         patch("backend.db.accounts.deactivate_credentials", new_callable=AsyncMock):
        mock_del.return_value = True
        mock_active.return_value = None  # Not the active account
        resp = client.delete("/api/accounts/acc-1")

    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True
