"""Logout must actually invalidate the bearer token.

Before the fix ``POST /api/auth/logout`` returned 200 without calling
``revoke_token``: the same Authorization header stayed valid for /me and every
other authenticated route.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import auth as auth_mod
from backend.api.routes.auth import router


@pytest.fixture(autouse=True)
def _reset():
    auth_mod.reset_token_store_for_tests()
    yield
    auth_mod.reset_token_store_for_tests()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/auth")
    return TestClient(app)


def test_logout_revokes_the_presented_token():
    token = auth_mod.generate_token("u-1", "alice")
    headers = {"Authorization": f"Bearer {token.token}"}
    client = _client()

    assert auth_mod.validate_token(token.token) is not None
    response = client.post("/api/auth/logout", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["revoked"] is True
    assert auth_mod.validate_token(token.token) is None


def test_logout_with_service_token_is_still_a_clean_success(monkeypatch):
    """The shared service token is not in the store; logout still answers 200."""
    monkeypatch.setenv("XHS_SERVICE_TOKEN", "service-token-for-test")
    client = _client()
    response = client.post(
        "/api/auth/logout", headers={"Authorization": "Bearer service-token-for-test"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["revoked"] is False
