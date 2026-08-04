"""Unit tests for QR / sync anti-risk gates."""

from __future__ import annotations

import time

import pytest

from backend.services import xhs_risk_gate as gate


@pytest.fixture(autouse=True)
def _reset_gates(monkeypatch):
    gate.reset_gates_for_tests()
    monkeypatch.setenv("XHS_QR_LOGIN_COOLDOWN_SECONDS", "60")
    monkeypatch.setenv("XHS_QR_RISK_BLOCK_SECONDS", "120")
    monkeypatch.setenv("CREATOR_STATS_AUTH_FAIL_COOLDOWN_MINUTES", "30")
    yield
    gate.reset_gates_for_tests()


def test_qr_cooldown_blocks_second_attempt():
    assert gate.check_qr_start_allowed("acc-1") is None
    gate.note_qr_attempt("acc-1")
    blocked = gate.check_qr_start_allowed("acc-1")
    assert blocked is not None
    assert blocked.risk_code == "qr_cooldown"
    assert blocked.retry_after_seconds > 0


def test_qr_risk_block_after_security_hit():
    gate.note_qr_risk_block("acc-2", reason="300012")
    blocked = gate.check_qr_start_allowed("acc-2")
    assert blocked is not None
    assert blocked.risk_code == "300012"
    assert "安全限制" in blocked.message or "冷却" in blocked.message


def test_is_security_risk_message():
    assert gate.is_security_risk_message("error_code=300012 IP at risk")
    assert gate.is_security_risk_message("小红书安全限制：当前网络")
    assert not gate.is_security_risk_message("playwright not installed")


def test_nonfinite_gate_config_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("XHS_QR_LOGIN_COOLDOWN_SECONDS", "nan")
    monkeypatch.setenv("XHS_QR_RISK_BLOCK_SECONDS", "inf")
    monkeypatch.setenv("CREATOR_STATS_AUTH_FAIL_COOLDOWN_MINUTES", "nan")

    assert gate.qr_cooldown_seconds() == 900.0
    assert gate.qr_risk_block_seconds() == 3600.0
    assert gate.sync_auth_fail_cooldown_minutes() == 120.0


def test_sync_auth_fail_cooldown():
    assert gate.check_sync_auth_cooldown("acc-3") is None
    gate.note_sync_auth_failure("acc-3", reason="AUTH_EXPIRED")
    blocked = gate.check_sync_auth_cooldown("acc-3")
    assert blocked is not None
    assert blocked.risk_code == "AUTH_EXPIRED"
    # Global check also sees the block
    global_block = gate.check_sync_auth_cooldown()
    assert global_block is not None
    gate.clear_sync_auth_failure("acc-3")
    assert gate.check_sync_auth_cooldown("acc-3") is None


def test_qr_cooldown_expires(monkeypatch):
    monkeypatch.setenv("XHS_QR_LOGIN_COOLDOWN_SECONDS", "0.01")
    gate.note_qr_attempt("acc-exp")
    assert gate.check_qr_start_allowed("acc-exp") is not None
    time.sleep(0.02)
    assert gate.check_qr_start_allowed("acc-exp") is None
