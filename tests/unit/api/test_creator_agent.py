from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes.creator_agent import router
from backend.creator_agent import (
    ActionCapability,
    CreatorModelDefinition,
    DecisionCandidate,
    DecisionPolicy,
    DecisionRequest,
    Evidence,
    EvidenceReferenceType,
    EvidenceSource,
    FeedbackInput,
    FeedbackOutcome,
)
from backend.db import creator_agent as creator_agent_db


@pytest.fixture(autouse=True)
def _reset_store():
    creator_agent_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/creator-agent")
    app.middleware("http")(error_handler_middleware)

    async def _user():
        return {"id": "owner-a", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def _model_payload(account_id: str = "account-a") -> dict:
    return {
        "account_id": account_id,
        "expected_revision": 0,
        "model": CreatorModelDefinition(
            identity_summary="一个重视证据的创作者",
            domains=["家居"],
            policies=[
                DecisionPolicy(
                    policy_id="p1",
                    label="耐用优先",
                    signal_weights={"durability": 1.0},
                    rationale="耐用性更重要。",
                    evidence_ids=["e1"],
                )
            ],
            evidence=[
                Evidence(
                    evidence_id="e1",
                    source_kind=EvidenceSource.CREATOR_STATEMENT,
                    source_ref="creator://statement/1",
                    claim="我优先耐用性",
                )
            ],
        ).model_dump(mode="json"),
    }


def test_model_write_and_decision_route(client, monkeypatch):
    async def _owned(_user_id: str, account_id: str):
        assert account_id == "account-a"
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _owned)
    created = client.put("/api/creator-agent/model", json=_model_payload())
    assert created.status_code == 200
    assert created.json()["data"]["creator_id"].startswith("creator_")

    decision = client.post(
        "/api/creator-agent/decisions",
        json=DecisionRequest(
            account_id="account-a",
            audience_id="audience-a",
            goal="选耐用品",
            candidates=[
                DecisionCandidate(candidate_id="a", label="A", signals={"durability": 0.9}),
                DecisionCandidate(candidate_id="b", label="B", signals={"durability": 0.2}),
            ],
        ).model_dump(mode="json"),
    )
    assert decision.status_code == 200
    assert decision.json()["data"]["status"] == "recommended"


def test_model_revision_conflict_returns_409(client, monkeypatch):
    async def _owned(_user_id: str, _account_id: str):
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _owned)
    assert client.put("/api/creator-agent/model", json=_model_payload()).status_code == 200
    stale = client.put("/api/creator-agent/model", json=_model_payload())
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "ERROR_CREATOR_MODEL_REVISION_CONFLICT"


def test_feedback_route_is_scoped_to_decision_audience(client, monkeypatch):
    async def _owned(_user_id: str, _account_id: str):
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _owned)
    client.put("/api/creator-agent/model", json=_model_payload())
    response = client.post(
        "/api/creator-agent/decisions/missing/feedback",
        json={
            "account_id": "account-a",
            "feedback": FeedbackInput(
                feedback_id="f1",
                audience_id="audience-a",
                outcome=FeedbackOutcome.ACCEPTED,
            ).model_dump(mode="json"),
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ERROR_CREATOR_DECISION_NOT_FOUND"


def test_learning_signal_routes_list_and_review(client, monkeypatch):
    async def _owned(_user_id: str, _account_id: str):
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _owned)
    assert client.put("/api/creator-agent/model", json=_model_payload()).status_code == 200
    decision = client.post(
        "/api/creator-agent/decisions",
        json={
            "account_id": "account-a",
            "audience_id": "audience-a",
            "goal": "选耐用品",
            "candidates": [
                {"candidate_id": "a", "label": "A", "signals": {"durability": 0.9}},
                {"candidate_id": "b", "label": "B", "signals": {"durability": 0.2}},
            ],
        },
    ).json()["data"]

    feedback = client.post(
        f"/api/creator-agent/decisions/{decision['decision_id']}/feedback",
        json={
            "account_id": "account-a",
            "feedback": {
                "feedback_id": "feedback-route-1",
                "audience_id": "audience-a",
                "outcome": "dissatisfied",
                "correction": "希望更轻便",
            },
        },
    )
    signal = feedback.json()["data"]["learning_signal"]
    assert feedback.status_code == 200
    assert signal["status"] == "pending_creator_review"

    listed = client.get("/api/creator-agent/learning-signals?account_id=account-a")
    assert listed.status_code == 200
    assert listed.json()["data"][0]["signal_id"] == signal["signal_id"]

    reviewed = client.post(
        f"/api/creator-agent/learning-signals/{signal['signal_id']}/review",
        json={
            "account_id": "account-a",
            "disposition": "dismissed",
            "review_note": "保留为一次性反馈",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["data"]["signal"]["status"] == "dismissed"


def test_action_routes_require_resolution_and_remain_account_scoped(client, monkeypatch):
    async def _owned(_user_id: str, _account_id: str):
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _owned)
    assert client.put("/api/creator-agent/model", json=_model_payload()).status_code == 200
    decision = client.post(
        "/api/creator-agent/decisions",
        json={
            "account_id": "account-a",
            "audience_id": "audience-a",
            "goal": "选耐用品",
            "candidates": [
                {"candidate_id": "a", "label": "A", "signals": {"durability": 0.9}},
                {"candidate_id": "b", "label": "B", "signals": {"durability": 0.2}},
            ],
        },
    ).json()["data"]
    request = {
        "account_id": "account-a",
        "decision_id": decision["decision_id"],
        "action_kind": ActionCapability.COMPARE_OPTIONS.value,
        "candidate_ids": ["a", "b"],
        "idempotency_key": "api-action-1",
    }
    created = client.post("/api/creator-agent/actions", json=request)
    assert created.status_code == 200
    action = created.json()["data"]
    assert action["status"] == "pending_confirmation"

    listed = client.get(
        "/api/creator-agent/actions?account_id=account-a&status=pending_confirmation"
    )
    assert listed.status_code == 200
    assert listed.json()["data"][0]["action_id"] == action["action_id"]

    resolved = client.post(
        f"/api/creator-agent/actions/{action['action_id']}/resolve",
        json={"account_id": "account-a", "disposition": "confirmed"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == "confirmed"
    conflict = client.post(
        f"/api/creator-agent/actions/{action['action_id']}/resolve",
        json={"account_id": "account-a", "disposition": "cancelled"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "ERROR_CREATOR_ACTION_CONFLICT"


def test_evidence_graph_routes_filter_and_scope_missing(client, monkeypatch):
    async def _owned(_user_id: str, _account_id: str):
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _owned)
    assert client.put("/api/creator-agent/model", json=_model_payload()).status_code == 200
    decision = client.post(
        "/api/creator-agent/decisions",
        json={
            "account_id": "account-a",
            "audience_id": "audience-a",
            "goal": "选耐用品",
            "candidates": [
                {
                    "candidate_id": "a",
                    "label": "A",
                    "signals": {"durability": 0.9},
                    "evidence": [
                        {
                            "evidence_id": "candidate-e1",
                            "source_kind": "product_fact",
                            "source_ref": "product://a",
                            "claim": "产品 A 更耐用",
                        }
                    ],
                },
                {"candidate_id": "b", "label": "B", "signals": {"durability": 0.2}},
            ],
        },
    ).json()["data"]

    listed = client.get(
        "/api/creator-agent/evidence",
        params={"account_id": "account-a", "source_kind": "product_fact"},
    )
    assert listed.status_code == 200
    assert [entry["evidence"]["evidence_id"] for entry in listed.json()["data"]] == ["candidate-e1"]

    detail = client.get(
        "/api/creator-agent/evidence/candidate-e1",
        params={"account_id": "account-a"},
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["evidence"]["evidence_id"] == "candidate-e1"

    missing = client.get(
        "/api/creator-agent/evidence/missing",
        params={"account_id": "account-a"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ERROR_CREATOR_EVIDENCE_NOT_FOUND"
    assert decision["account_id"] == "account-a"


def test_evidence_reference_type_matches_dynamic_http_enum():
    from backend.api.app import app

    values = app.openapi()["components"]["schemas"]["EvidenceReferenceType"]["enum"]
    assert values == [item.value for item in EvidenceReferenceType]
    assert len(values) == len(set(values))
