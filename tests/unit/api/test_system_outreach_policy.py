"""`/api/system/outreach-policy/{account_id}` — the management write path (票 5ax).

Mirrors the cool-down policy routes: same auth dependency, same ``success``
envelope, same account-in-path shape.  The DB is mocked at the account-store
seams (``is_pool_ready`` / ``list_credentials`` / ``upsert_credential`` /
``delete_credential``) so these exercise the real service + route, never a
Postgres.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.services.xhs_outreach_policy import (
    DAILY_PROACTIVE_CAP_KEY,
    MODE_KEY,
    OUTREACH_CONFIRMED,
    OUTREACH_INBOUND,
    OUTREACH_NOBODY,
)

_ENV_KEYS = (MODE_KEY, DAILY_PROACTIVE_CAP_KEY, "XHS_ALLOW_OUTBOUND_DM")


@pytest.fixture(autouse=True)
def _clean_deployment(monkeypatch: pytest.MonkeyPatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    """An in-memory ``account_credentials`` behind the production seams."""
    rows: dict[tuple[str, str], str] = {}

    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

    async def _list(account_id: str) -> list[Any]:
        return [
            SimpleNamespace(key_name=key, value=value)
            for (account, key), value in rows.items()
            if account == account_id
        ]

    async def _upsert(account_id: str, key_name: str, value: str) -> None:
        rows[(account_id, key_name)] = value

    async def _delete(account_id: str, key_name: str) -> bool:
        return rows.pop((account_id, key_name), None) is not None

    monkeypatch.setattr("backend.db.accounts.list_credentials", _list)
    monkeypatch.setattr("backend.db.accounts.upsert_credential", _upsert)
    monkeypatch.setattr("backend.db.accounts.delete_credential", _delete)
    return rows


@pytest.fixture
def client():
    from backend.api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "username": "ops"}
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _effective(response) -> dict[str, Any]:
    body = response.json()
    assert body["success"] is True, body
    return body["data"]["effective"]


class TestGet:
    def test_returns_the_effective_policy_and_the_account_overrides(self, client, store):
        store[("acc-1", MODE_KEY)] = OUTREACH_NOBODY
        store[("acc-1", DAILY_PROACTIVE_CAP_KEY)] = "2"

        response = client.get("/api/system/outreach-policy/acc-1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["account_id"] == "acc-1"
        assert data["effective"]["mode"] == OUTREACH_NOBODY
        assert data["effective"]["daily_proactive_cap"] == 2
        assert data["overrides"] == {
            MODE_KEY: OUTREACH_NOBODY,
            DAILY_PROACTIVE_CAP_KEY: "2",
        }

    def test_account_rows_win_over_the_deployment_env(self, client, store, monkeypatch):
        monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")
        store[("acc-1", MODE_KEY)] = OUTREACH_NOBODY

        response = client.get("/api/system/outreach-policy/acc-1")

        assert _effective(response)["mode"] == OUTREACH_NOBODY

    def test_without_a_store_the_effective_policy_is_the_safe_default(self, client, monkeypatch):
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)

        response = client.get("/api/system/outreach-policy/acc-1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["effective"]["mode"] == OUTREACH_INBOUND
        assert data["overrides"] == {}


class TestPut:
    def test_writes_the_named_keys_and_reads_back_the_effective_policy(self, client, store):
        response = client.put(
            "/api/system/outreach-policy/acc-1",
            json={"mode": OUTREACH_CONFIRMED, "daily_proactive_cap": 3},
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["effective"]["mode"] == OUTREACH_CONFIRMED
        assert data["effective"]["daily_proactive_cap"] == 3
        assert data["overrides"] == {
            MODE_KEY: OUTREACH_CONFIRMED,
            DAILY_PROACTIVE_CAP_KEY: "3",
        }
        assert store == {
            ("acc-1", MODE_KEY): OUTREACH_CONFIRMED,
            ("acc-1", DAILY_PROACTIVE_CAP_KEY): "3",
        }

    def test_an_invalid_mode_comes_back_in_the_api_envelope(self, client, store):
        response = client.put(
            "/api/system/outreach-policy/acc-1",
            json={"mode": "everyone"},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "ERROR_VALIDATION"
        assert "unknown outreach mode" in body["error"]["message"]
        assert store == {}

    def test_a_negative_cap_is_a_validation_error(self, client, store):
        response = client.put(
            "/api/system/outreach-policy/acc-1",
            json={"daily_proactive_cap": -1},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "ERROR_VALIDATION"
        assert store == {}

    def test_an_empty_body_is_refused(self, client, store):
        response = client.put("/api/system/outreach-policy/acc-1", json={})

        assert response.status_code == 400
        assert "at least one" in response.json()["error"]["message"]

    def test_an_unavailable_store_is_503_not_a_claimed_success(self, client, monkeypatch):
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)

        response = client.put(
            "/api/system/outreach-policy/acc-1",
            json={"mode": OUTREACH_CONFIRMED},
        )

        assert response.status_code == 503
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "ERROR_SERVICE_UNAVAILABLE"


class TestDelete:
    def test_removes_the_rows_and_falls_back_to_the_deployment(self, client, store, monkeypatch):
        monkeypatch.setenv(MODE_KEY, OUTREACH_CONFIRMED)
        store[("acc-1", MODE_KEY)] = OUTREACH_NOBODY
        store[("acc-1", DAILY_PROACTIVE_CAP_KEY)] = "1"

        response = client.delete("/api/system/outreach-policy/acc-1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["removed"] == [MODE_KEY, DAILY_PROACTIVE_CAP_KEY]
        # Deployment default applies again (legacy opt-in keeps its historical cap).
        assert data["effective"]["mode"] == OUTREACH_CONFIRMED
        assert data["effective"]["daily_proactive_cap"] == 20
        assert data["overrides"] == {}
        assert store == {}

    def test_clearing_an_unset_policy_is_a_no_op_success(self, client, store):
        response = client.delete("/api/system/outreach-policy/acc-1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["removed"] == []
        assert data["effective"]["mode"] == OUTREACH_INBOUND

    def test_an_unavailable_store_is_503(self, client, monkeypatch):
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)

        response = client.delete("/api/system/outreach-policy/acc-1")

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "ERROR_SERVICE_UNAVAILABLE"
