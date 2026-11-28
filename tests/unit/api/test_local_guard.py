from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import local_guard
from backend.api.local_guard import (
    allowed_origins,
    boot_token_path,
    ensure_boot_token,
    evaluate_guard_request,
    guard_enabled,
    install_local_guard,
    local_guard_middleware,
    read_boot_token,
    token_required,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        local_guard.LOCAL_GUARD_ENV,
        local_guard.LOCAL_GUARD_TOKEN_ENV,
        local_guard.BOOT_TOKEN_PATH_ENV,
        local_guard.ALLOWED_ORIGINS_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def _app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(local_guard_middleware)

    @app.post("/api/mutate")
    async def _mutate() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/read")
    async def _read() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_guard_flags_are_off_by_default() -> None:
    assert guard_enabled() is False
    assert token_required() is False


def test_guard_flags_accept_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv(local_guard.LOCAL_GUARD_ENV, value)
        assert guard_enabled() is True
    monkeypatch.setenv(local_guard.LOCAL_GUARD_ENV, "off")
    assert guard_enabled() is False
    monkeypatch.setenv(local_guard.LOCAL_GUARD_TOKEN_ENV, "1")
    assert token_required() is True


def test_boot_token_is_created_reused_and_private(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "boot.token"
    token = ensure_boot_token(target)
    assert len(token) == 64
    assert target.read_text(encoding="utf-8").strip() == token
    if sys.platform != "win32":
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600
    assert ensure_boot_token(target) == token
    assert read_boot_token(target) == token
    assert read_boot_token(tmp_path / "missing.token") == ""


def test_boot_token_path_honours_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom.token"
    monkeypatch.setenv(local_guard.BOOT_TOKEN_PATH_ENV, str(custom))
    assert boot_token_path() == custom


def test_allowed_origins_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "http://localhost:5173" in allowed_origins()
    monkeypatch.setenv(
        local_guard.ALLOWED_ORIGINS_ENV,
        "http://localhost:3000, http://127.0.0.1:3000 ,",
    )
    assert allowed_origins() == ("http://localhost:3000", "http://127.0.0.1:3000")


def test_rebinding_host_is_rejected_with_421() -> None:
    decision = evaluate_guard_request(
        method="GET",
        host="attacker.example.com",
        origin="",
    )
    assert decision.allowed is False
    assert decision.status_code == 421
    assert decision.reason == "host_not_loopback"


def test_loopback_host_state_change_needs_allowed_origin() -> None:
    rejected = evaluate_guard_request(
        method="POST",
        host="127.0.0.1:8000",
        origin="http://evil.example.com",
    )
    assert rejected.status_code == 403
    assert rejected.reason == "origin_not_allowed"
    allowed = evaluate_guard_request(
        method="POST",
        host="127.0.0.1:8000",
        origin="http://localhost:8000",
    )
    assert allowed.allowed is True


def test_get_without_origin_is_allowed() -> None:
    decision = evaluate_guard_request(method="GET", host="localhost:8000", origin="")
    assert decision.allowed is True
    assert decision.status_code == 200


def test_websocket_without_origin_is_rejected() -> None:
    decision = evaluate_guard_request(
        method="GET",
        host="127.0.0.1:8000",
        origin="",
        websocket=True,
    )
    assert decision.allowed is False
    assert decision.status_code == 403
    assert decision.reason == "websocket_origin_missing"


def test_boot_token_gate_only_applies_when_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(local_guard.BOOT_TOKEN_PATH_ENV, str(tmp_path / "boot.token"))
    token = ensure_boot_token()
    unrequired = evaluate_guard_request(method="POST", host="localhost:8000")
    assert unrequired.allowed is True
    monkeypatch.setenv(local_guard.LOCAL_GUARD_TOKEN_ENV, "1")
    missing = evaluate_guard_request(method="POST", host="localhost:8000")
    assert missing.status_code == 403
    assert missing.reason == "boot_token_mismatch"
    wrong = evaluate_guard_request(method="POST", host="localhost:8000", presented_token="nope")
    assert wrong.status_code == 403
    ok = evaluate_guard_request(method="POST", host="localhost:8000", presented_token=token)
    assert ok.allowed is True


def test_middleware_rejects_cross_site_post_with_envelope() -> None:
    client = TestClient(_app(Path(".")))
    response = client.post("/api/mutate", headers={"origin": "http://evil.example.com"})
    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "ERROR_LOCAL_REQUEST_REJECTED"
    assert "origin_not_allowed" in payload["error"]["message"]


def test_middleware_allows_same_origin_and_reads() -> None:
    client = TestClient(_app(Path(".")))
    allowed = client.post("/api/mutate", headers={"origin": "http://localhost:8000"})
    assert allowed.status_code == 200
    read = client.get("/api/read")
    assert read.status_code == 200


def test_middleware_rejects_rebound_host() -> None:
    client = TestClient(_app(Path(".")))
    response = client.get("/api/read", headers={"host": "evil.example.com"})
    assert response.status_code == 421
    payload = response.json()
    assert payload["error"]["code"] == "ERROR_LOCAL_REQUEST_REJECTED"


def test_install_local_guard_is_inert_when_disabled() -> None:
    app = FastAPI()
    assert install_local_guard(app) is False
