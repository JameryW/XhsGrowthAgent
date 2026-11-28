# backend/api/local_guard.py

"""Local request guard for the loopback-only API (ledger scheme #43).

The API binds to ``127.0.0.1`` and, by default, trusts every caller.  A browser
tab on any site can still reach that socket: cross-origin WebSocket handshakes
are not blocked by the same-origin policy, and DNS rebinding makes an attacker
domain resolve to ``127.0.0.1`` while the ``Host`` header keeps the attacker
name.  This module adds the deterministic Host/Origin/boot-token checks from
``backend.services.interaction_contracts`` to the HTTP and WebSocket entry
points.

Everything here is opt-in: with ``XHS_LOCAL_GUARD`` unset the middleware is not
registered at all and behaviour is byte-identical to before.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Any, Final

from fastapi import Request, Response, WebSocket
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from backend.api.errors import ErrorCode
from backend.api.responses import error
from backend.services.interaction_contracts import (
    DEFAULT_ALLOWED_ORIGINS,
    LocalRequestDecision,
    evaluate_local_request,
)

__all__ = [
    "ALLOWED_ORIGINS_ENV",
    "BOOT_TOKEN_HEADER",
    "BOOT_TOKEN_PATH_ENV",
    "LOCAL_GUARD_ENV",
    "LOCAL_GUARD_TOKEN_ENV",
    "allowed_origins",
    "boot_token_path",
    "ensure_boot_token",
    "evaluate_guard_request",
    "guard_enabled",
    "guard_websocket",
    "install_local_guard",
    "local_guard_middleware",
    "read_boot_token",
    "token_required",
]

logger = logging.getLogger("xhs_growth.api.local_guard")

LOCAL_GUARD_ENV: Final = "XHS_LOCAL_GUARD"
LOCAL_GUARD_TOKEN_ENV: Final = "XHS_LOCAL_GUARD_TOKEN_REQUIRED"
BOOT_TOKEN_PATH_ENV: Final = "XHS_LOCAL_BOOT_TOKEN_PATH"
ALLOWED_ORIGINS_ENV: Final = "XHS_LOCAL_ALLOWED_ORIGINS"
BOOT_TOKEN_HEADER: Final = "x-xhs-boot-token"

_TRUTHY: Final = frozenset({"1", "true", "yes", "on"})


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def guard_enabled() -> bool:
    """Return True when the opt-in local request guard is switched on."""

    return _flag(LOCAL_GUARD_ENV)


def token_required() -> bool:
    """Return True when state-changing requests must present the boot token."""

    return _flag(LOCAL_GUARD_TOKEN_ENV)


def boot_token_path() -> Path:
    """Resolve the boot-token file, honouring ``XHS_LOCAL_BOOT_TOKEN_PATH``."""

    override = os.environ.get(BOOT_TOKEN_PATH_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".xhs_growth_agent" / "boot.token"


def read_boot_token(path: Path | None = None) -> str:
    """Read the boot token; a missing or unreadable file yields an empty string."""

    target = path if path is not None else boot_token_path()
    try:
        return target.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ensure_boot_token(path: Path | None = None) -> str:
    """Return the boot token, creating a 0600 file with a fresh secret if absent."""

    target = path if path is not None else boot_token_path()
    existing = read_boot_token(target)
    if existing:
        return existing
    token = secrets.token_hex(32)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(token + "\n", encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError as exc:  # pragma: no cover - platform dependent
        logger.warning("could not restrict boot token permissions: %s", exc)
    return token


def allowed_origins() -> tuple[str, ...]:
    """Return the local Origin allow-list (env override, else built-in defaults)."""

    raw = os.environ.get(ALLOWED_ORIGINS_ENV, "")
    items = tuple(item.strip() for item in raw.split(",") if item.strip())
    return items or DEFAULT_ALLOWED_ORIGINS


def evaluate_guard_request(
    *,
    method: str,
    host: str,
    origin: str = "",
    presented_token: str = "",
    websocket: bool = False,
    expected_token: str = "",
) -> LocalRequestDecision:
    """Evaluate one request against the loopback Host/Origin/token rules."""

    expected = expected_token
    if not expected and token_required():
        expected = read_boot_token()
    return evaluate_local_request(
        host=host,
        origin=origin,
        method=method,
        is_websocket=websocket,
        boot_token=expected,
        presented_token=presented_token,
        allowed_origins=allowed_origins(),
    )


def _rejection(decision: LocalRequestDecision, path: str) -> JSONResponse:
    logger.warning(
        "local guard rejected %s: status=%s reason=%s",
        path,
        decision.status_code,
        decision.reason,
    )
    return JSONResponse(
        status_code=decision.status_code,
        content=error(
            code=ErrorCode.LOCAL_REQUEST_REJECTED.value,
            message=f"Local request rejected: {decision.reason}",
        ).model_dump(mode="json"),
    )


async def local_guard_middleware(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    """Reject non-loopback Host headers, cross-site Origins and bad boot tokens."""

    decision = evaluate_guard_request(
        method=request.method,
        host=request.headers.get("host", ""),
        origin=request.headers.get("origin", ""),
        presented_token=request.headers.get(BOOT_TOKEN_HEADER, ""),
    )
    if not decision.allowed:
        return _rejection(decision, request.url.path)
    return await call_next(request)


async def guard_websocket(websocket: WebSocket) -> bool:
    """Check a WebSocket handshake; close with 1008 when the guard rejects it."""

    if not guard_enabled():
        return True
    decision = evaluate_guard_request(
        method="GET",
        host=websocket.headers.get("host", ""),
        origin=websocket.headers.get("origin", ""),
        presented_token=websocket.headers.get(BOOT_TOKEN_HEADER, ""),
        websocket=True,
    )
    if decision.allowed:
        return True
    logger.warning(
        "local guard closed websocket %s: status=%s reason=%s",
        websocket.url.path,
        decision.status_code,
        decision.reason,
    )
    await websocket.close(code=1008)
    return False


def install_local_guard(app: Any) -> bool:
    """Register the HTTP middleware on ``app`` when the guard is enabled."""

    if not guard_enabled():
        return False
    app.middleware("http")(local_guard_middleware)
    return True
