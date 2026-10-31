"""Promotion ledger management surface (Slice B2 + 票 5y human review).

GET remains the read-only ledger page. POST
``/memory-promotions/{id}/review`` is the human write path: approve appends a
human PROMOTE and writes ``strategy_notes``; dismiss appends REFUSE only.
Missing → 404, already closed → 409, no store → 503 (never a success envelope).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes.creator_agent import router
from backend.context.models import TrustClass
from backend.memory.promotion import (
    DedupeVerdict,
    PromotionCandidate,
    PromotionDecision,
    PromotionDisposition,
    PromotionReason,
    SourceCheck,
    decide_promotion,
)
from backend.memory.promotion_ledger import PromotionLedger, promotion_id_for

_ACCOUNT = "account-a"
_VERSION = "2026-10-01T00:00:00Z"
_NEWER = "2026-10-02T00:00:00Z"
_TARGET_NS = ("accounts", _ACCOUNT, "strategy_notes")


def _client(store: Any = None, *, with_graph: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/creator-agent")
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "owner-a", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    if with_graph:
        app.state.graph = SimpleNamespace(store=store)
    return TestClient(app)


@pytest.fixture
def _owned(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def _require(user_id: str, account_id: str) -> object:
        calls.append((user_id, account_id))
        return object()

    monkeypatch.setattr("backend.api.routes.creator_agent.require_owned_account", _require)
    return calls


def _seed(
    store: InMemoryStore, *, version: str = _VERSION, recorded_at: str = "2026-10-21T10:00:00+00:00"
) -> str:
    candidate = PromotionCandidate(
        namespace="strategy_notes",
        key="style:style_1",
        body="风格「治愈/温暖治愈」历史互动率 0.400（样本 10）",
        trust_class=TrustClass.INTERNAL_FACT,
        source_ref="creative-memory://style/style_1",
        source_version=version,
        observed_at=version,
        evidence_ids=("ev_style_style_1",),
        sample_count=10,
        measured_rate=0.4,
    )
    decision = decide_promotion(
        candidate,
        source=SourceCheck(present=True, version=version, evidence_found=candidate.evidence_ids),
    )
    asyncio.run(
        PromotionLedger(store).append(_ACCOUNT, candidate, decision, recorded_at=recorded_at)
    )
    return decision.candidate_id


def _seed_review(store: InMemoryStore) -> str:
    candidate = PromotionCandidate(
        namespace="strategy_notes",
        key="style:style_1",
        body="风格「治愈/温暖治愈」历史互动率 0.400（样本 10）",
        trust_class=TrustClass.MEMORY,
        source_ref="creative-memory://style/style_1",
        source_version=_VERSION,
        observed_at=_VERSION,
        evidence_ids=("ev_style_style_1",),
        sample_count=10,
        measured_rate=0.4,
        proposed_by="hy-memory",
    )
    decision = PromotionDecision(
        candidate_id=candidate.id,
        disposition=PromotionDisposition.REVIEW,
        reason=PromotionReason.NEEDS_HUMAN_REVIEW,
        dedupe=DedupeVerdict.NEW,
        verified=True,
        supersedes=(),
        decided_by="machine",
        policy_version="v1",
    )
    asyncio.run(
        PromotionLedger(store).append(
            _ACCOUNT, candidate, decision, recorded_at="2026-10-29T10:00:00+00:00"
        )
    )
    return promotion_id_for(decision, source_version=candidate.source_version)


def test_an_empty_ledger_is_available_and_empty(_owned: list[tuple[str, str]]) -> None:
    with _client(InMemoryStore()) as client:
        resp = client.get("/api/creator-agent/memory-promotions", params={"account_id": _ACCOUNT})

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["account_id"] == _ACCOUNT
    assert data["available"] is True
    assert data["complete"] is True
    assert data["records"] == []
    assert _owned == [("owner-a", _ACCOUNT)]


def test_a_record_is_returned_losslessly(_owned: list[tuple[str, str]]) -> None:
    store = InMemoryStore()
    candidate_id = _seed(store)
    with _client(store) as client:
        resp = client.get("/api/creator-agent/memory-promotions", params={"account_id": _ACCOUNT})

    records = resp.json()["data"]["records"]
    assert len(records) == 1
    record = records[0]
    assert record["candidate_id"] == candidate_id
    assert record["namespace"] == "strategy_notes"
    assert record["key"] == "style:style_1"
    assert record["source_ref"] == "creative-memory://style/style_1"
    assert record["source_version"] == _VERSION
    assert record["disposition"] == "promote"
    assert record["reason"] == "verified_internal_fact"
    assert record["dedupe"] == "new"
    assert record["verified"] is True
    assert record["supersedes"] == []
    assert record["decided_by"] == "machine"
    assert record["policy_version"] == "v1"
    assert record["recorded_at"] == "2026-10-21T10:00:00+00:00"


def test_an_unavailable_store_is_not_an_empty_history(
    _owned: list[tuple[str, str]],
) -> None:
    # No graph on app.state at all: this deployment has no memory store.
    with _client(with_graph=False) as client:
        resp = client.get("/api/creator-agent/memory-promotions", params={"account_id": _ACCOUNT})

    data = resp.json()["data"]
    assert data["available"] is False
    assert data["records"] == []


def test_the_limit_is_validated(_owned: list[tuple[str, str]]) -> None:
    with _client(InMemoryStore()) as client:
        too_small = client.get(
            "/api/creator-agent/memory-promotions",
            params={"account_id": _ACCOUNT, "limit": 0},
        )
        too_big = client.get(
            "/api/creator-agent/memory-promotions",
            params={"account_id": _ACCOUNT, "limit": 201},
        )
        invalid_account = client.get(
            "/api/creator-agent/memory-promotions", params={"account_id": "   "}
        )

    assert too_small.status_code == 400, too_small.text
    assert too_big.status_code == 400, too_big.text
    assert invalid_account.status_code in (400, 422), invalid_account.text


def test_records_are_newest_first(_owned: list[tuple[str, str]]) -> None:
    store = InMemoryStore()
    _seed(store, version=_VERSION, recorded_at="2026-10-21T10:00:00+00:00")
    _seed(store, version=_NEWER, recorded_at="2026-10-21T11:00:00+00:00")
    with _client(store) as client:
        resp = client.get("/api/creator-agent/memory-promotions", params={"account_id": _ACCOUNT})

    records = resp.json()["data"]["records"]
    assert [record["source_version"] for record in records] == [_NEWER, _VERSION]


def test_list_is_get_and_review_is_post() -> None:
    """Management surface: GET list + POST review (append-only; no PATCH/DELETE)."""
    list_methods = {
        method
        for route in router.routes
        if getattr(route, "path", "") == "/memory-promotions"
        for method in getattr(route, "methods", set())
    }
    review_methods = {
        method
        for route in router.routes
        if getattr(route, "path", "") == "/memory-promotions/{promotion_id}/review"
        for method in getattr(route, "methods", set())
    }
    assert list_methods == {"GET"}
    assert review_methods == {"POST"}


def _seed_hy_review(store: InMemoryStore) -> str:
    candidate = PromotionCandidate(
        namespace="strategy_notes",
        key="hy:deadbeef",
        body="一条待人审的 hy 记忆",
        trust_class=TrustClass.MEMORY,
        source_ref="hy-memory://chat/mem_1",
        source_version=_VERSION,
        observed_at=_VERSION,
        evidence_ids=("ev_hy_deadbeef",),
        proposed_by="hy-memory",
    )
    decision = PromotionDecision(
        candidate_id=candidate.id,
        disposition=PromotionDisposition.REVIEW,
        reason=PromotionReason.NEEDS_HUMAN_REVIEW,
        dedupe=DedupeVerdict.NEW,
        verified=True,
        supersedes=(),
        decided_by="machine",
        policy_version="v1",
    )
    asyncio.run(
        PromotionLedger(store).append(
            _ACCOUNT, candidate, decision, recorded_at="2026-10-29T10:00:00+00:00"
        )
    )
    return promotion_id_for(decision, source_version=candidate.source_version)


def test_approve_hy_uses_snapshotted_body(_owned: list[tuple[str, str]]) -> None:
    """hy REVIEW approve must not require a style re-read (no trusted SDK reader)."""
    store = InMemoryStore()
    review_id = _seed_hy_review(store)

    with _client(store) as client:
        resp = client.post(
            f"/api/creator-agent/memory-promotions/{review_id}/review",
            json={
                "account_id": _ACCOUNT,
                "disposition": "approved",
                "review_note": "hy 可以",
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["applied"] is True
    assert data["closure"]["reason"] == "human_approved"
    written = asyncio.run(store.aget(_TARGET_NS, "hy:deadbeef"))
    assert written is not None
    assert written.value["note"] == "一条待人审的 hy 记忆"
    assert written.value["trust_class"] == TrustClass.MEMORY.value


def test_approve_writes_ledger_and_target(
    _owned: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = InMemoryStore()
    review_id = _seed_review(store)

    async def _reader(account_id: str, style_id: str) -> dict[str, Any]:
        return {
            "style_id": style_id,
            "tone": "治愈",
            "visual_style": "温暖治愈",
            "engagement_rate": 0.4,
            "sample_count": 10,
            "last_used": _VERSION,
        }

    monkeypatch.setattr("backend.memory.promotion_review.read_style_row", _reader)

    with _client(store) as client:
        resp = client.post(
            f"/api/creator-agent/memory-promotions/{review_id}/review",
            json={
                "account_id": _ACCOUNT,
                "disposition": "approved",
                "review_note": "可以发",
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["disposition"] == "approved"
    assert data["applied"] is True
    assert data["closure"]["disposition"] == "promote"
    assert data["closure"]["reason"] == "human_approved"
    assert data["closure"]["decided_by"] == "human"
    assert data["review"]["promotion_id"] == review_id
    assert _owned == [("owner-a", _ACCOUNT)]

    written = asyncio.run(store.aget(_TARGET_NS, "style:style_1"))
    assert written is not None
    assert "治愈" in written.value["note"]


def test_dismiss_refuses_without_target_write(_owned: list[tuple[str, str]]) -> None:
    store = InMemoryStore()
    review_id = _seed_review(store)

    with _client(store) as client:
        resp = client.post(
            f"/api/creator-agent/memory-promotions/{review_id}/review",
            json={"account_id": _ACCOUNT, "disposition": "dismissed"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["disposition"] == "dismissed"
    assert data["applied"] is False
    assert data["closure"]["disposition"] == "refuse"
    assert data["closure"]["reason"] == "human_dismissed"
    assert asyncio.run(store.aget(_TARGET_NS, "style:style_1")) is None


def test_review_missing_is_404(_owned: list[tuple[str, str]]) -> None:
    with _client(InMemoryStore()) as client:
        resp = client.post(
            "/api/creator-agent/memory-promotions/promo_missing/review",
            json={"account_id": _ACCOUNT, "disposition": "dismissed"},
        )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "ERROR_CREATOR_MEMORY_PROMOTION_NOT_FOUND"


def test_review_conflict_is_409(_owned: list[tuple[str, str]]) -> None:
    store = InMemoryStore()
    review_id = _seed_review(store)
    with _client(store) as client:
        first = client.post(
            f"/api/creator-agent/memory-promotions/{review_id}/review",
            json={"account_id": _ACCOUNT, "disposition": "dismissed"},
        )
        second = client.post(
            f"/api/creator-agent/memory-promotions/{review_id}/review",
            json={"account_id": _ACCOUNT, "disposition": "approved"},
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "ERROR_CREATOR_MEMORY_PROMOTION_CONFLICT"


def test_review_without_store_is_not_success(_owned: list[tuple[str, str]]) -> None:
    with _client(with_graph=False) as client:
        resp = client.post(
            "/api/creator-agent/memory-promotions/promo_x/review",
            json={"account_id": _ACCOUNT, "disposition": "dismissed"},
        )
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] == "ERROR_SERVICE_UNAVAILABLE"
    assert resp.json()["success"] is False


def test_approve_without_body_is_validation_error(
    _owned: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approve must fail closed when neither style re-read nor body snapshot exists."""
    store = InMemoryStore()
    review_id = _seed_review(store)
    # Drop the snapshotted body so the default rebuilder has nothing to fall back to.
    page = asyncio.run(PromotionLedger(store).records(_ACCOUNT))
    review = next(r for r in page.records if r.promotion_id == review_id)
    emptied = review.to_dict()
    emptied["body"] = ""
    asyncio.run(
        store.aput(("accounts", _ACCOUNT, "memory_promotions"), key=review_id, value=emptied)
    )

    async def _missing(account_id: str, style_id: str) -> None:
        return None

    monkeypatch.setattr("backend.memory.promotion_review.read_style_row", _missing)

    with _client(store) as client:
        resp = client.post(
            f"/api/creator-agent/memory-promotions/{review_id}/review",
            json={"account_id": _ACCOUNT, "disposition": "approved"},
        )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "ERROR_VALIDATION"
    assert resp.json()["success"] is False
    assert asyncio.run(store.aget(_TARGET_NS, "style:style_1")) is None
