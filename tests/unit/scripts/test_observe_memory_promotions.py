"""Observe-only promotion CLI pass (Slice B2, 票 5t).

The pass is the first *real* caller of the observe channel. What is pinned: it
decides and records through the ledger, dry-run reads the ledger but writes
nothing, an absent store is reported rather than faked, the input validation is
explicit, and the CLI refuses to run without a durable (Postgres) store instead
of silently losing records in an in-process one.
"""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from backend.creator_agent.models import (
    ContentObservation,
    ContentObservationKind,
    ContentObservationScan,
)
from backend.memory.promotion_ledger import PromotionLedger
from scripts.observe_memory_promotions import main, run_observation_pass

_ACCOUNT = "acc-1"
_VERSION = "2026-10-01T00:00:00Z"


class _Source:
    def __init__(self, observations: list[ContentObservation], *, saturated: bool = False) -> None:
        self._observations = observations
        self._saturated = saturated
        self.calls: list[tuple[str, int]] = []

    async def observations(self, account_id: str, *, window: int) -> ContentObservationScan:
        self.calls.append((account_id, window))
        return ContentObservationScan(
            observations=list(self._observations), saturated=self._saturated
        )


def _style(source_id: str = "style_1", *, samples: int = 10) -> ContentObservation:
    return ContentObservation(
        kind=ContentObservationKind.STYLE,
        source_id=source_id,
        description="治愈/温暖治愈",
        measured_rate=0.4,
        sample_count=samples,
        observed_at=_VERSION,
    )


@pytest.mark.asyncio
async def test_a_pass_records_the_verdicts() -> None:
    store = InMemoryStore()
    source = _Source([_style()])

    summary = await run_observation_pass(store=store, account_id=_ACCOUNT, window=25, source=source)

    assert source.calls == [(_ACCOUNT, 25)]
    assert summary["scanned"] == 1
    assert summary["style_candidates"] == 1
    assert summary["ledger_available"] is True
    assert summary["recorded"] == 1
    assert summary["scan_saturated"] is False
    assert summary["decisions"][0]["disposition"] == "promote"
    assert summary["decisions"][0]["reason"] == "verified_internal_fact"

    page = await PromotionLedger(store).records(_ACCOUNT)
    assert len(page.records) == 1

    # Observe-only: the target namespace is still untouched.
    target = await store.asearch(("accounts", _ACCOUNT, "strategy_notes"))
    assert list(target) == []


@pytest.mark.asyncio
async def test_dry_run_decides_but_writes_nothing() -> None:
    store = InMemoryStore()
    source = _Source([_style()])

    summary = await run_observation_pass(
        store=store, account_id=_ACCOUNT, dry_run=True, source=source
    )

    assert summary["dry_run"] is True
    assert summary["style_candidates"] == 1
    assert summary["recorded"] == 0
    assert summary["decisions"][0]["disposition"] == "promote"
    assert (await PromotionLedger(store).records(_ACCOUNT)).records == ()


@pytest.mark.asyncio
async def test_an_unavailable_ledger_is_reported_not_faked() -> None:
    source = _Source([_style()])

    summary = await run_observation_pass(store=None, account_id=_ACCOUNT, source=source)

    assert summary["ledger_available"] is False
    assert summary["recorded"] == 0
    assert summary["style_candidates"] == 1


@pytest.mark.asyncio
async def test_a_saturated_scan_says_so() -> None:
    summary = await run_observation_pass(
        store=InMemoryStore(),
        account_id=_ACCOUNT,
        source=_Source([_style()], saturated=True),
    )
    assert summary["scan_saturated"] is True


@pytest.mark.asyncio
async def test_no_observations_is_zero_not_an_error() -> None:
    summary = await run_observation_pass(
        store=InMemoryStore(), account_id=_ACCOUNT, source=_Source([])
    )
    assert summary["scanned"] == 0
    assert summary["style_candidates"] == 0
    assert summary["recorded"] == 0


@pytest.mark.asyncio
async def test_a_blank_account_is_rejected_by_this_layer() -> None:
    """Outcome-valued: a downstream store error would be the wrong proof.

    Without this guard the empty namespace may still be rejected by the store
    itself, which would make the test pass for a reason this layer does not own.
    """
    outcome: object = "no error"
    try:
        await run_observation_pass(
            store=InMemoryStore(), account_id="  ", source=_Source([_style()])
        )
    except Exception as exc:
        outcome = exc
    assert isinstance(outcome, ValueError), outcome
    assert "account_id" in str(outcome), outcome


@pytest.mark.asyncio
async def test_a_zero_window_is_rejected() -> None:
    outcome: object = "no error"
    try:
        await run_observation_pass(
            store=InMemoryStore(), account_id=_ACCOUNT, window=0, source=_Source([_style()])
        )
    except Exception as exc:
        outcome = exc
    assert isinstance(outcome, ValueError), outcome
    assert "window" in str(outcome), outcome


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
