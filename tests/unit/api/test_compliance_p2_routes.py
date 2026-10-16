"""P2 API surfaces: niche-compliance, acceptance-signoff, learning-recommendations."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.deps import get_current_user
from backend.services.creator_stats.types import NoteStats


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "username": "ops"}
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_niche_compliance_route_high_risk(client):
    r = client.get("/api/system/niche-compliance", params={"niche": "医美"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["is_high_risk"] is True
    assert data["lexicon_stricter"] is True
    assert data["lexicon_overlay"] == "niche_aesthetic.yaml"
    assert "医美" in data["high_risk_niches"]
    assert data["qualification_hint"]


def test_acceptance_signoff_route_readonly(client):
    r = client.get("/api/system/acceptance-signoff")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["ok"] is True
    assert data["replaces_human_signoff"] is False
    ids = {g["id"] for g in data["gates"]}
    assert {"G1", "G2", "G3", "G4", "G5"}.issubset(ids)
    # Waived risk acceptance must never look like a signed pass via API.
    for gate in data["gates"]:
        if gate.get("status") in {"waived_risk_accepted", "waived"}:
            assert gate.get("is_passed") is False
            assert gate.get("is_waived") is True
            assert gate.get("next_review_at")
    waiver = data.get("waiver") or {}
    if waiver:
        assert waiver.get("replaces_signoff") is False



def test_learning_recommendations_route(client, monkeypatch):
    async def _owned(user_id: str, account_id: str) -> None:
        return None

    async def _notes(account_id: str, *, limit: int = 100, order_by: str = "engagement"):
        return [
            NoteStats.from_dict(
                {
                    "note_id": "n-top",
                    "account_id": account_id,
                    "title": "爆款标题",
                    "tags": ["夏日护肤"],
                    "views": 2000,
                    "likes": 100,
                    "comments": 20,
                    "collects": 40,
                    "shares": 10,
                    "engagement_rate": 0.085,
                }
            )
        ]

    monkeypatch.setattr(
        "backend.api.routes.analytics.require_owned_account",
        _owned,
    )
    monkeypatch.setattr(
        "backend.db.creator_stats.list_note_stats",
        _notes,
    )

    r = client.get(
        "/api/analytics/creator-stats/acc-learn/learning-recommendations",
        params={"limit": 5},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["empty"] is False
    assert data["recommendations"][0]["topic"] == "夏日护肤"
    assert data["recommendations"][0]["related_note_id"] == "n-top"
