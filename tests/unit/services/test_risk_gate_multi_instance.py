"""P1-5: risk-gate cooldowns shared via DB KV across process instances."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.db.risk_gates import reset_risk_gate_memory_for_tests
from backend.services.xhs_risk_gate import (
    check_publish_allowed,
    export_risk_gate_state,
    hydrate_risk_gates,
    note_publish,
    note_qr_risk_block,
    reset_gates_for_tests,
    snapshot_risk_gates,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("XHS_PUBLISH_COOLDOWN_SECONDS", "120")
    monkeypatch.setenv("XHS_QR_RISK_BLOCK_SECONDS", "3600")
    reset_gates_for_tests()
    reset_risk_gate_memory_for_tests()
    yield
    reset_gates_for_tests()
    reset_risk_gate_memory_for_tests()


@pytest.mark.asyncio
async def test_cooldown_shared_via_db_kv_across_instances(monkeypatch):
    """Instance A notes a publish + QR risk; instance B hydrates the same KV."""
    # --- Instance A ---
    note_publish(account_id="acc-shared")
    note_qr_risk_block("acc-shared", reason="300012")
    exported = export_risk_gate_state()
    assert "account:acc-shared" in exported["publish"]
    assert "acc-shared" in exported["qr_risk"]
    assert "acc-shared" in exported["last_risk_hit"]

    # Persist into the durable KV (memory path when pool not ready).
    from backend.db.risk_gates import save_risk_gate_state

    await save_risk_gate_state(exported)

    # --- Instance B (fresh process memory) ---
    reset_gates_for_tests()
    assert check_publish_allowed(account_id="acc-shared") is None

    monkeypatch.setattr(
        "backend.db.risk_gates.load_risk_gate_state",
        AsyncMock(return_value=exported),
    )
    await hydrate_risk_gates()

    assert check_publish_allowed(account_id="acc-shared") is not None
    snap = snapshot_risk_gates()
    assert snap["durable"] is True
    assert snap["active_qr_risk_blocks"] >= 1
