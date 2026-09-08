from __future__ import annotations

import asyncio

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


def test_action_execution_routes_require_confirmation_and_return_receipt(client, monkeypatch):
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
    action = client.post(
        "/api/creator-agent/actions",
        json={
            "account_id": "account-a",
            "decision_id": decision["decision_id"],
            "action_kind": "compare_options",
            "candidate_ids": ["a", "b"],
            "idempotency_key": "api-execution-1",
        },
    ).json()["data"]

    pending = client.post(
        f"/api/creator-agent/actions/{action['action_id']}/execute",
        json={"account_id": "account-a"},
    )
    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "ERROR_CREATOR_ACTION_EXECUTION_NOT_ALLOWED"

    assert (
        client.post(
            f"/api/creator-agent/actions/{action['action_id']}/resolve",
            json={"account_id": "account-a", "disposition": "confirmed"},
        ).status_code
        == 200
    )
    executed = client.post(
        f"/api/creator-agent/actions/{action['action_id']}/execute",
        json={"account_id": "account-a"},
    )
    assert executed.status_code == 200
    receipt = executed.json()["data"]
    assert receipt["action_id"] == action["action_id"]
    assert receipt["status"] == "succeeded"
    assert receipt["result"]["candidate_ids"] == ["a", "b"]

    repeated = client.post(
        f"/api/creator-agent/actions/{action['action_id']}/execute",
        json={"account_id": "account-a"},
    )
    fetched = client.get(
        f"/api/creator-agent/actions/{action['action_id']}/execution",
        params={"account_id": "account-a"},
    )
    assert repeated.json()["data"] == receipt
    assert fetched.json()["data"] == receipt
    missing = client.get(
        "/api/creator-agent/actions/missing/execution",
        params={"account_id": "account-a"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ERROR_CREATOR_ACTION_EXECUTION_NOT_FOUND"
    foreign_execute = client.post(
        f"/api/creator-agent/actions/{action['action_id']}/execute",
        json={"account_id": "account-b"},
    )
    assert foreign_execute.status_code == 404
    assert foreign_execute.json()["error"]["code"] == "ERROR_CREATOR_ACTION_NOT_FOUND"


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


def test_decision_dataset_route_returns_page_and_typed_validation(client, monkeypatch):
    async def _owned(_user_id: str, account_id: str):
        assert account_id == "account-a"
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _owned)
    empty = client.get("/api/creator-agent/dataset/decisions?account_id=account-a")
    assert empty.status_code == 200
    assert empty.json()["data"] == {
        "items": [],
        "total": 0,
        "limit": 20,
        "next_cursor": None,
    }

    invalid_cursor = client.get(
        "/api/creator-agent/dataset/decisions",
        params={"account_id": "account-a", "cursor": "invalid"},
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["error"]["code"] == "ERROR_VALIDATION"

    blank_audience = client.get(
        "/api/creator-agent/dataset/decisions",
        params={"account_id": "account-a", "audience_id": "   "},
    )
    assert blank_audience.status_code == 400
    assert blank_audience.json()["error"]["code"] == "ERROR_VALIDATION"

    invalid_limit = client.get(
        "/api/creator-agent/dataset/decisions",
        params={"account_id": "account-a", "limit": 101},
    )
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error"]["code"] == "ERROR_VALIDATION"


def _revise_model(client, account_id: str = "account-a") -> None:
    payload = _model_payload(account_id)
    payload["expected_revision"] = 1
    payload["model"]["identity_summary"] = "一个改过主意的创作者"
    assert client.put("/api/creator-agent/model", json=payload).status_code == 200


def test_model_revision_history_route_pages_newest_first(client, monkeypatch):
    async def _owned(_user_id: str, _account_id: str):
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _owned)
    assert client.put("/api/creator-agent/model", json=_model_payload()).status_code == 200
    _revise_model(client)

    history = client.get(
        "/api/creator-agent/model/revisions", params={"account_id": "account-a", "limit": 1}
    )
    assert history.status_code == 200
    page = history.json()["data"]
    assert page["total"] == 2
    assert page["limit"] == 1
    assert [item["revision"] for item in page["items"]] == [2]
    assert page["items"][0]["source"] == "creator_edit"
    assert page["items"][0]["source_signal_id"] is None
    assert page["next_cursor"]

    second = client.get(
        "/api/creator-agent/model/revisions",
        params={"account_id": "account-a", "limit": 1, "cursor": page["next_cursor"]},
    )
    assert second.status_code == 200
    assert [item["revision"] for item in second.json()["data"]["items"]] == [1]
    assert second.json()["data"]["next_cursor"] is None
    # total describes the complete history, not the remainder after the cursor.
    assert second.json()["data"]["total"] == 2


def test_model_revision_lookup_resolves_the_model_a_decision_used(client, monkeypatch):
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
    _revise_model(client)

    resolved = client.get(
        f"/api/creator-agent/decisions/{decision['decision_id']}/model-revision",
        params={"account_id": "account-a"},
    )
    current = client.get("/api/creator-agent/model", params={"account_id": "account-a"})
    assert resolved.status_code == 200
    assert resolved.json()["data"]["revision"] == decision["model_revision"] == 1
    assert resolved.json()["data"]["model"]["identity_summary"] == "一个重视证据的创作者"
    assert current.json()["data"]["revision"] == 2
    assert current.json()["data"]["identity_summary"] == "一个改过主意的创作者"

    single = client.get("/api/creator-agent/model/revisions/1", params={"account_id": "account-a"})
    assert single.status_code == 200
    assert single.json()["data"] == resolved.json()["data"]


def test_model_revision_routes_return_typed_not_found_and_validation(client, monkeypatch):
    async def _owned(_user_id: str, _account_id: str):
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _owned)
    assert client.put("/api/creator-agent/model", json=_model_payload()).status_code == 200

    missing = client.get(
        "/api/creator-agent/model/revisions/99", params={"account_id": "account-a"}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ERROR_CREATOR_MODEL_REVISION_NOT_FOUND"

    zero = client.get("/api/creator-agent/model/revisions/0", params={"account_id": "account-a"})
    assert zero.status_code == 400
    assert zero.json()["error"]["code"] == "ERROR_VALIDATION"

    foreign = client.get("/api/creator-agent/model/revisions/1", params={"account_id": "account-b"})
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "ERROR_CREATOR_MODEL_REVISION_NOT_FOUND"

    missing_decision = client.get(
        "/api/creator-agent/decisions/missing/model-revision", params={"account_id": "account-a"}
    )
    assert missing_decision.status_code == 404
    assert missing_decision.json()["error"]["code"] == "ERROR_CREATOR_DECISION_NOT_FOUND"

    invalid_cursor = client.get(
        "/api/creator-agent/model/revisions", params={"account_id": "account-a", "cursor": "bad"}
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["error"]["code"] == "ERROR_VALIDATION"

    invalid_limit = client.get(
        "/api/creator-agent/model/revisions", params={"account_id": "account-a", "limit": 0}
    )
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error"]["code"] == "ERROR_VALIDATION"

    blank_account = client.get("/api/creator-agent/model/revisions", params={"account_id": "   "})
    assert blank_account.status_code == 400
    assert blank_account.json()["error"]["code"] == "ERROR_VALIDATION"


def test_evidence_proposal_route_is_read_only_and_account_scoped(client, monkeypatch):
    from backend.db import creative_memory as creative_memory_db

    async def _owned(_user_id: str, _account_id: str):
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _owned)
    creative_memory_db._reset_memory_store()
    assert client.put("/api/creator-agent/model", json=_model_payload()).status_code == 200

    proposals_url = "/api/creator-agent/model/evidence-proposals"
    try:
        empty_page = client.get(proposals_url, params={"account_id": "account-a"})
        assert empty_page.json()["data"] == {
            "items": [],
            "total": 0,
            "limit": 50,
            "truncated": False,
        }

        asyncio.run(
            creative_memory_db.upsert_style(
                "account-a",
                "s-1",
                {
                    "tone": "治愈",
                    "visual_style": "温暖",
                    "engagement_rate": 0.9,
                    "sample_count": 30,
                },
            )
        )
        asyncio.run(
            creative_memory_db.upsert_style(
                "account-b",
                "s-other",
                {
                    "tone": "犀利",
                    "visual_style": "高冷",
                    "engagement_rate": 0.9,
                    "sample_count": 30,
                },
            )
        )

        response = client.get(proposals_url, params={"account_id": "account-a"})
        assert response.status_code == 200
        page = response.json()["data"]
        items = page["items"]
        assert [item["evidence"]["source_ref"] for item in items] == ["creative-memory://style/s-1"]
        assert (page["total"], page["limit"], page["truncated"]) == (1, 50, False)
        assert items[0]["evidence"]["source_kind"] == "creator_content"
        # 0.9 measured rate shrunk by 30/(30+5) samples.
        assert items[0]["evidence"]["confidence"] == 0.771
        assert items[0]["draft_preference"]["stance"] == "prefer"

        # Reading proposals must not adopt them: the model and its history are
        # untouched, so ADR-0002's explicit-approval invariant still holds.
        model = client.get("/api/creator-agent/model", params={"account_id": "account-a"})
        assert model.json()["data"]["revision"] == 1
        history = client.get(
            "/api/creator-agent/model/revisions", params={"account_id": "account-a"}
        )
        assert history.json()["data"]["total"] == 1

        foreign = client.get(proposals_url, params={"account_id": "account-b"})
        assert [item["evidence"]["source_ref"] for item in foreign.json()["data"]["items"]] == [
            "creative-memory://style/s-other"
        ]

        bad_limit = client.get(proposals_url, params={"account_id": "account-a", "limit": 200})
        assert bad_limit.status_code == 400
        assert bad_limit.json()["error"]["code"] == "ERROR_VALIDATION"

        bad_confidence = client.get(
            proposals_url, params={"account_id": "account-a", "min_confidence": 1.5}
        )
        assert bad_confidence.status_code == 400
        assert bad_confidence.json()["error"]["code"] == "ERROR_VALIDATION"
    finally:
        creative_memory_db._reset_memory_store()
