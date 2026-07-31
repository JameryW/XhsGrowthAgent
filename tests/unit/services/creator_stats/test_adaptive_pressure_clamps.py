"""Adaptive SAFE_MODE / pressure clamps on CdpTransport."""

from __future__ import annotations

from backend.services.creator_stats.client import CdpTransport


def test_pressure_one_applies_safe_mode_clamps(monkeypatch):
    monkeypatch.delenv("CREATOR_STATS_SAFE_MODE", raising=False)
    t0 = CdpTransport(cdp_endpoint="http://127.0.0.1:9222", risk_pressure=0)
    t1 = CdpTransport(cdp_endpoint="http://127.0.0.1:9222", risk_pressure=1)
    assert t1._max_list_pages <= t0._max_list_pages
    assert t1._max_detail_visits <= t0._max_detail_visits
    assert t1._light_run_chance >= t0._light_run_chance


def test_pressure_two_forces_list_only(monkeypatch):
    monkeypatch.delenv("CREATOR_STATS_SAFE_MODE", raising=False)
    t2 = CdpTransport(cdp_endpoint="http://127.0.0.1:9222", risk_pressure=2)
    assert t2._max_detail_visits == 0
    assert t2._light_run_chance == 1.0
    assert t2._max_list_pages <= 2
