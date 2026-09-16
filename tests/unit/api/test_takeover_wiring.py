"""The takeover scan's lifespan wiring (P2b-S3).

``takeover_scan``, ``takeover_scheduler`` and ``startup_takeover_scan`` are
tested directly next door. What this file pins is the layer those tests cannot
see: that a *booted service* calls them, and that ``WORKFLOW_TAKEOVER_ENABLED``
is the switch that decides. Both are gates -- drop the wiring and every unit
test next door still passes while no process ever takes over an orphan.

Booting the real lifespan is the only way to observe that, and it is cheap
(~2s): ``test_risk_gates_routes.py`` boots the same app the same way.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app


@pytest.fixture(autouse=True)
def _forget_the_previous_boot(monkeypatch: pytest.MonkeyPatch):
    """``app`` is a module-level singleton, so lifespan leftovers outlive a test."""
    monkeypatch.delattr(app.state, "takeover_status", raising=False)
    monkeypatch.delattr(app.state, "takeover_scheduler", raising=False)
    yield


class TestABootedService:
    def test_it_schedules_the_scan_and_runs_the_first_pass(self):
        with TestClient(app) as client:
            status = app.state.takeover_status
            task = app.state.takeover_scheduler

            assert status["enabled"] is True
            assert status["status"] == "scheduled"
            assert task is not None and not task.done()
            assert task.get_name() == "execution-takeover-scan"

            # The startup pass is the one that catches work lost while the
            # service was down, so it has run before the first request is served.
            assert status["run_count"] == 1
            assert status["last_source"] == "startup"
            assert status["last_newly_expired"] == 0
            assert status["last_error"] is None

            # And it is visible from outside, which is what the surface is for.
            payload = client.get("/health").json()["data"]
            assert payload["execution_takeover"]["status"] == "scheduled"
            assert payload["execution_takeover"]["run_count"] == 1

    def test_the_switch_turns_the_whole_scan_off(self, monkeypatch: pytest.MonkeyPatch):
        """``takeover_enabled = False`` has to mean "no scan at all", not "a scan
        that finds nothing" -- an operator reads those differently.

        Driven through the environment rather than by patching an object: the
        lifespan builds its own ``Settings()``, so the env var *is* the switch.
        """
        monkeypatch.setenv("WORKFLOW_TAKEOVER_ENABLED", "false")

        with TestClient(app):
            status = app.state.takeover_status

            assert status["enabled"] is False
            assert status["status"] == "disabled"
            assert status["run_count"] == 0
            assert status["last_source"] is None
            assert app.state.takeover_scheduler is None
