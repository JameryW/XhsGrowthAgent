"""Process-local risk gates for QR login and creator-stats sync.

Keeps short-term cooldowns in memory so operators cannot hammer XHS with
repeated QR starts or auth-failed crawls after a risk hit (300012) or
expired creator session.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return value if math.isfinite(value) else default


def qr_cooldown_seconds() -> float:
    """Min gap between QR start attempts for the same account (0 disables)."""
    return max(0.0, _env_float("XHS_QR_LOGIN_COOLDOWN_SECONDS", 900.0))


def qr_risk_block_seconds() -> float:
    """How long to block QR after a security/IP risk hit (0 disables)."""
    return max(0.0, _env_float("XHS_QR_RISK_BLOCK_SECONDS", 3600.0))


def sync_auth_fail_cooldown_minutes() -> float:
    """Extra cooldown after creator auth failure / empty-shell risk (0 disables)."""
    return max(0.0, _env_float("CREATOR_STATS_AUTH_FAIL_COOLDOWN_MINUTES", 120.0))


@dataclass(frozen=True)
class GateBlock:
    """A temporary block with operator-facing metadata."""

    reason: str
    risk_code: str
    message: str
    retry_after_seconds: int

    def to_details(self, account_id: str = "") -> dict[str, Any]:
        details: dict[str, Any] = {
            "risk_code": self.risk_code,
            "reason": self.reason,
            "retry_after_seconds": self.retry_after_seconds,
        }
        if account_id:
            details["account_id"] = account_id
        return details


# account_id -> monotonic deadline / last attempt
_qr_last_attempt_at: dict[str, float] = {}
_qr_risk_blocked_until: dict[str, float] = {}
_qr_risk_reason: dict[str, str] = {}
_sync_auth_blocked_until: dict[str, float] = {}
_sync_auth_reason: dict[str, str] = {}


def _now() -> float:
    return time.monotonic()


def _remaining(deadline: float) -> int:
    return max(0, int(deadline - _now() + 0.999))


def check_qr_start_allowed(account_id: str) -> GateBlock | None:
    """Return a GateBlock if QR start must be refused right now."""
    account_id = (account_id or "").strip()
    if not account_id:
        return None

    risk_until = _qr_risk_blocked_until.get(account_id, 0.0)
    if risk_until > _now():
        reason = _qr_risk_reason.get(account_id) or "security_risk"
        return GateBlock(
            reason="qr_risk_block",
            risk_code="300012" if "300012" in reason else "security_risk",
            message=(
                "小红书安全限制冷却中：近期检测到 IP/环境风控，"
                f"请 {_remaining(risk_until)} 秒后再试，并优先切换家庭宽带或手机热点。"
            ),
            retry_after_seconds=_remaining(risk_until),
        )

    cooldown = qr_cooldown_seconds()
    if cooldown <= 0:
        return None
    last = _qr_last_attempt_at.get(account_id, 0.0)
    if last <= 0:
        return None
    elapsed = _now() - last
    if elapsed >= cooldown:
        return None
    wait = int(cooldown - elapsed + 0.999)
    return GateBlock(
        reason="qr_cooldown",
        risk_code="qr_cooldown",
        message=(f"扫码登录冷却中：同一账号请 {wait} 秒后再试，短时间反复弹码会触发风控。"),
        retry_after_seconds=wait,
    )


def note_qr_attempt(account_id: str) -> None:
    account_id = (account_id or "").strip()
    if account_id:
        _qr_last_attempt_at[account_id] = _now()


def note_qr_risk_block(account_id: str, *, reason: str = "300012") -> None:
    """Block further QR starts after a confirmed security hit."""
    account_id = (account_id or "").strip()
    if not account_id:
        return
    block_s = qr_risk_block_seconds()
    if block_s <= 0:
        return
    _qr_risk_blocked_until[account_id] = _now() + block_s
    _qr_risk_reason[account_id] = reason
    # Also push the attempt clock so cooldown stacks with the risk block.
    _qr_last_attempt_at[account_id] = _now()


def clear_qr_risk_block(account_id: str) -> None:
    account_id = (account_id or "").strip()
    _qr_risk_blocked_until.pop(account_id, None)
    _qr_risk_reason.pop(account_id, None)


def is_security_risk_message(message: str) -> bool:
    text = (message or "").lower()
    markers = (
        "300012",
        "ip at risk",
        "secure network",
        "安全限制",
        "website-login/error",
        "风控",
    )
    return any(m in text or m in (message or "") for m in markers)


def check_sync_auth_cooldown(account_id: str = "") -> GateBlock | None:
    """Block creator-stats crawl after recent AUTH_EXPIRED / shell risk.

    When ``account_id`` is empty, any active global auth block applies
    (single active-account sync path).
    """
    now = _now()
    if account_id:
        until = _sync_auth_blocked_until.get(account_id.strip(), 0.0)
        if until > now:
            return GateBlock(
                reason="sync_auth_cooldown",
                risk_code="AUTH_EXPIRED",
                message=(
                    "创作者中心鉴权失败冷却中："
                    f"请 {_remaining(until)} 秒后再同步，并先重新扫码登录。"
                ),
                retry_after_seconds=_remaining(until),
            )
        return None

    # Global: earliest active block across accounts (active-account sync).
    active = [(aid, until) for aid, until in _sync_auth_blocked_until.items() if until > now]
    if not active:
        return None
    aid, until = min(active, key=lambda item: item[1])
    return GateBlock(
        reason="sync_auth_cooldown",
        risk_code="AUTH_EXPIRED",
        message=(f"账号 {aid[:8]}… 创作者中心鉴权失败冷却中：请 {_remaining(until)} 秒后再同步。"),
        retry_after_seconds=_remaining(until),
    )


def note_sync_auth_failure(account_id: str, *, reason: str = "AUTH_EXPIRED") -> None:
    account_id = (account_id or "").strip()
    if not account_id:
        return
    minutes = sync_auth_fail_cooldown_minutes()
    if minutes <= 0:
        return
    _sync_auth_blocked_until[account_id] = _now() + minutes * 60.0
    _sync_auth_reason[account_id] = reason


def clear_sync_auth_failure(account_id: str) -> None:
    account_id = (account_id or "").strip()
    _sync_auth_blocked_until.pop(account_id, None)
    _sync_auth_reason.pop(account_id, None)


def reset_gates_for_tests() -> None:
    """Test helper — clear all in-memory gates."""
    _qr_last_attempt_at.clear()
    _qr_risk_blocked_until.clear()
    _qr_risk_reason.clear()
    _sync_auth_blocked_until.clear()
    _sync_auth_reason.clear()


__all__ = [
    "GateBlock",
    "check_qr_start_allowed",
    "check_sync_auth_cooldown",
    "clear_qr_risk_block",
    "clear_sync_auth_failure",
    "is_security_risk_message",
    "note_qr_attempt",
    "note_qr_risk_block",
    "note_sync_auth_failure",
    "qr_cooldown_seconds",
    "qr_risk_block_seconds",
    "reset_gates_for_tests",
    "sync_auth_fail_cooldown_minutes",
]
