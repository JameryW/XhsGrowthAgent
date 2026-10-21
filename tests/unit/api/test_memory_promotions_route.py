"""Read-only promotion ledger surface (Slice B2, 票 5t).

The endpoint exists so an operator can see *what was decided and why*. What is
pinned here: it never writes, an unavailable store is reported as such instead
of as "no decisions", records are returned losslessly and newest-first, limits
are validated, and the account scope is enforced before the ledger is read.
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
from backend.memory.promotion import PromotionCandidate, SourceCheck, decide_promotion
from backend.memory.promotion_ledger import PromotionLedger

_ACCOUNT = "account-a"
_VERSION = "2026-10-01T00:00:00Z"
_NEWER = "2026-10-02T00:00:00Z"


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


def test_the_surface_has_no_write_verb() -> None:
    """A read-only management face is a fact about the router, not a promise."""
    methods = {
        method
        for route in router.routes
        if getattr(route, "path", "") == "/memory-promotions"
        for method in getattr(route, "methods", set())
    }
    assert methods == {"GET"}
