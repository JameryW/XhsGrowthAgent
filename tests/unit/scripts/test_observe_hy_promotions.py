"""hy-memory observation CLI pass (Slice D, 票 5v).

The pass is the durable caller for hy candidates: it records REVIEW verdicts and
a degraded batch's refusal, writes nothing into memory namespaces, and refuses to
run without a durable ledger store or an enabled hy-memory bridge.
"""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from backend.memory.hy.bridge import reset_hy_memory_bridge
from backend.memory.promotion_hy import HyMemoryBatch
from backend.memory.promotion_ledger import PromotionLedger
from scripts.observe_hy_promotions import main, run_hy_pass

_ACCOUNT = "acc-1"


def _row(content: str = "用户偏好测评体标题", *, memory_id: str = "mem_1") -> dict[str, object]:
    return {"content": content, "memory_id": memory_id}


def _batch(*rows: dict[str, object], scene: str = "chat") -> HyMemoryBatch:
    return HyMemoryBatch(account_id=_ACCOUNT, scene=scene, memories=tuple(rows))


@pytest.fixture(autouse=True)
def _fresh_bridge() -> None:
    reset_hy_memory_bridge()
    yield
    reset_hy_memory_bridge()


async def test_a_pass_records_review_verdicts() -> None:
    store = InMemoryStore()
    summary = await run_hy_pass(
        store=store, account_id=_ACCOUNT, batch=_batch(_row(), _row(memory_id="m2"))
    )

    assert summary["scanned"] == 2
    assert summary["reviewed"] == 2
    assert summary["recorded"] == 2
    assert summary["refused_batch"] is False
    assert {item["disposition"] for item in summary["decisions"]} == {"review"}
    assert {item["reason"] for item in summary["decisions"]} == {"needs_human_review"}
    assert len((await PromotionLedger(store).records(_ACCOUNT)).records) == 2


async def test_dry_run_records_nothing() -> None:
    store = InMemoryStore()
    summary = await run_hy_pass(
        store=store, account_id=_ACCOUNT, batch=_batch(_row()), dry_run=True
    )
    assert summary["reviewed"] == 1
    assert summary["recorded"] == 0
    assert (await PromotionLedger(store).records(_ACCOUNT)).records == ()


async def test_a_degraded_batch_is_reported_and_recorded() -> None:
    store = InMemoryStore()
    batch = HyMemoryBatch(
        account_id=_ACCOUNT, scene="working", degraded=True, error="TimeoutError: slow"
    )
    summary = await run_hy_pass(store=store, account_id=_ACCOUNT, batch=batch)

    assert summary["refused_batch"] is True
    assert summary["degraded_reason"] == "TimeoutError: slow"
    assert summary["recorded"] == 1
    assert summary["batch_refusal"]["reason"] == "source_degraded"
    assert summary["decisions"] == []
    records = (await PromotionLedger(store).records(_ACCOUNT)).records
    assert records[0].detail == "TimeoutError: slow"


async def test_an_empty_batch_is_zero_not_an_error() -> None:
    summary = await run_hy_pass(store=InMemoryStore(), account_id=_ACCOUNT, batch=_batch())
    assert summary["scanned"] == 0
    assert summary["reviewed"] == 0
    assert summary["recorded"] == 0


async def test_a_blank_account_is_rejected() -> None:
    outcome: object = "accepted"
    try:
        await run_hy_pass(store=InMemoryStore(), account_id="  ", batch=_batch())
    except Exception as exc:
        outcome = exc
    assert isinstance(outcome, ValueError), outcome


def test_the_cli_refuses_without_a_durable_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("XHS_POSTGRES_URI", raising=False)
    monkeypatch.delenv("POSTGRES_URI", raising=False)

    code = main(["--account-id", _ACCOUNT])

    captured = capsys.readouterr()
    assert code == 2
    assert "POSTGRES_URI" in captured.err
    assert captured.out == ""


def test_the_cli_refuses_when_hy_memory_is_disabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XHS_POSTGRES_URI", "postgresql://not-opened-in-this-test")
    monkeypatch.delenv("POSTGRES_URI", raising=False)

    code = main(["--account-id", _ACCOUNT])

    captured = capsys.readouterr()
    assert code == 2
    assert "disabled" in captured.err
    assert captured.out == ""
