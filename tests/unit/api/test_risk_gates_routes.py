"""System risk-gates ops routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.services.xhs_risk_gate import note_browser_action, reset_gates_for_tests


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", "60")
    reset_gates_for_tests()
    yield
    reset_gates_for_tests()


@pytest.fixture
def client(monkeypatch):
    async def _user():
        return {"id": "u1", "username": "ops"}

    monkeypatch.setattr("backend.api.routes.system.get_current_user", _user)
    # Override dependency
    from backend.api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "username": "ops"}
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_get_and_clear_risk_gates(client, monkeypatch):
    note_browser_action(account_id="acc-z", owner="publisher")
    r = client.get("/api/system/risk-gates")
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    data = body["data"]
    assert isinstance(data.get("active"), list)
    assert any(row.get("kind") == "browser_action" for row in data["active"])

    r2 = client.post(
        "/api/system/risk-gates/clear",
        json={"account_id": "acc-z"},
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["total"] >= 1
    r3 = client.get("/api/system/risk-gates", params={"account_id": "acc-z"})
    assert r3.json()["data"]["active"] == []


def test_risk_gates_account_health_shape(client, monkeypatch):
    from backend.services.xhs_risk_gate import note_engagement_risk_pause, set_cooldown_policy

    monkeypatch.setenv("XHS_ENGAGEMENT_RISK_PAUSE_SECONDS", "1800")
    monkeypatch.setenv("CREATOR_STATS_SAFE_MODE", "1")
    set_cooldown_policy("acc-health", browser_action_seconds=25.0)
    note_engagement_risk_pause("acc-health", reason="risk_control")

    r = client.get("/api/system/risk-gates", params={"account_id": "acc-health"})
    assert r.status_code == 200
    data = r.json()["data"]
    health = data["account_health"]
    assert health["account_id"] == "acc-health"
    assert health["policy"]["effective"]["browser_action_seconds"] == 25.0
    assert health["safe_mode"]["active"] is True
    assert health["engagement_pause"]["paused"] is True
    assert health["remaining_ban_seconds"] > 0
    assert health["last_risk_hit"] is not None
