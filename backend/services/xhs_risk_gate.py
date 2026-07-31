"""Process-local risk gates for QR login, browser CDP actions, and sync.

Keeps short-term cooldowns in memory so operators cannot hammer XHS with
repeated QR starts, back-to-back browser features, or auth-failed crawls
after a risk hit (300012) / expired creator session.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


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


def browser_action_cooldown_seconds() -> float:
    """Min gap after any CDP session ends before another feature starts (0 disables)."""
    return max(0.0, _env_float("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", 20.0))


def publish_cooldown_seconds() -> float:
    """Min gap between publish attempts for the same account (0 disables)."""
    return max(0.0, _env_float("XHS_PUBLISH_COOLDOWN_SECONDS", 90.0))


def engagement_account_cooldown_seconds() -> float:
    """Min gap between engagement sessions for the same account (0 disables).

    Complements the per-action pacing inside XHSEngagement.
    """
    return max(0.0, _env_float("XHS_ENGAGEMENT_ACCOUNT_COOLDOWN_SECONDS", 30.0))


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
# Cross-feature browser CDP cool-down (key -> last release mono + owner)
_browser_action_last_at: dict[str, float] = {}
_browser_action_last_owner: dict[str, str] = {}
_publish_last_at: dict[str, float] = {}
_engagement_last_at: dict[str, float] = {}


def _now() -> float:
    return time.monotonic()


def _remaining(deadline: float) -> int:
    return max(0, int(deadline - _now() + 0.999))


def _profile_key(*, account_id: str = "", cdp_endpoint: str = "") -> str:
    account_id = (account_id or "").strip()
    if account_id:
        return f"account:{account_id}"
    endpoint = (cdp_endpoint or "").strip()
    if not endpoint:
        return "default"
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname or "localhost"
        port = parsed.port
        if port is not None:
            return f"cdp:{host}:{port}"
    except ValueError:
        pass
    return f"cdp:{endpoint}"


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


def note_browser_action(
    *,
    account_id: str = "",
    cdp_endpoint: str = "",
    owner: str = "unknown",
) -> None:
    """Record that a CDP session for this profile just ended."""
    key = _profile_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    _browser_action_last_at[key] = _now()
    _browser_action_last_owner[key] = (owner or "unknown").strip() or "unknown"


def check_browser_action_allowed(
    *,
    account_id: str = "",
    cdp_endpoint: str = "",
    owner: str = "",
) -> GateBlock | None:
    """Block rapid successive CDP features on the same profile.

    Same-owner re-entry (e.g. engagement actions in one session) is not gated
    here — the CDP lock already serializes. This gap applies after a session
    releases, before a *different* feature attaches.
    """
    cooldown = browser_action_cooldown_seconds()
    if cooldown <= 0:
        return None
    key = _profile_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    last = _browser_action_last_at.get(key, 0.0)
    if last <= 0:
        return None
    last_owner = _browser_action_last_owner.get(key, "")
    owner_norm = (owner or "").strip()
    # Same feature back-to-back still cools down, but shorter (0.4×) — humans
    # sometimes retry the same action quickly; full gap is for feature switches.
    effective = cooldown if (not owner_norm or owner_norm != last_owner) else cooldown * 0.4
    elapsed = _now() - last
    if elapsed >= effective:
        return None
    wait = int(effective - elapsed + 0.999)
    return GateBlock(
        reason="browser_action_cooldown",
        risk_code="browser_action_cooldown",
        message=(
            f"浏览器操作冷却中：上一任务（{last_owner or 'unknown'}）刚结束，"
            f"请 {wait} 秒后再切换功能，避免连续占用创作者中心触发风控。"
        ),
        retry_after_seconds=wait,
    )


def note_publish(account_id: str = "", *, cdp_endpoint: str = "") -> None:
    key = _profile_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    _publish_last_at[key] = _now()


def check_publish_allowed(account_id: str = "", *, cdp_endpoint: str = "") -> GateBlock | None:
    """Min gap between publishes for one account/profile."""
    cooldown = publish_cooldown_seconds()
    if cooldown <= 0:
        return None
    key = _profile_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    last = _publish_last_at.get(key, 0.0)
    if last <= 0:
        return None
    elapsed = _now() - last
    if elapsed >= cooldown:
        return None
    wait = int(cooldown - elapsed + 0.999)
    return GateBlock(
        reason="publish_cooldown",
        risk_code="publish_cooldown",
        message=f"发布冷却中：同一账号请 {wait} 秒后再发，连续发布容易触发平台限制。",
        retry_after_seconds=wait,
    )


def note_engagement(account_id: str = "", *, cdp_endpoint: str = "") -> None:
    key = _profile_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    _engagement_last_at[key] = _now()


def check_engagement_allowed(
    account_id: str = "", *, cdp_endpoint: str = ""
) -> GateBlock | None:
    """Min gap between engagement *sessions* for one account/profile."""
    cooldown = engagement_account_cooldown_seconds()
    if cooldown <= 0:
        return None
    key = _profile_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    last = _engagement_last_at.get(key, 0.0)
    if last <= 0:
        return None
    elapsed = _now() - last
    if elapsed >= cooldown:
        return None
    wait = int(cooldown - elapsed + 0.999)
    return GateBlock(
        reason="engagement_cooldown",
        risk_code="engagement_cooldown",
        message=f"互动冷却中：同一账号请 {wait} 秒后再进行评论/私信操作。",
        retry_after_seconds=wait,
    )


def snapshot_risk_gates() -> dict[str, Any]:
    """Compact operator-facing gate snapshot for /health."""
    now = _now()
    browser_active = 0
    for last in _browser_action_last_at.values():
        if now - last < browser_action_cooldown_seconds():
            browser_active += 1
    auth_active = sum(1 for until in _sync_auth_blocked_until.values() if until > now)
    qr_risk_active = sum(1 for until in _qr_risk_blocked_until.values() if until > now)
    return {
        "browser_action_cooldown_seconds": browser_action_cooldown_seconds(),
        "publish_cooldown_seconds": publish_cooldown_seconds(),
        "engagement_account_cooldown_seconds": engagement_account_cooldown_seconds(),
        "active_browser_cooldowns": browser_active,
        "active_sync_auth_blocks": auth_active,
        "active_qr_risk_blocks": qr_risk_active,
    }


def reset_gates_for_tests() -> None:
    """Test helper — clear all in-memory gates."""
    _qr_last_attempt_at.clear()
    _qr_risk_blocked_until.clear()
    _qr_risk_reason.clear()
    _sync_auth_blocked_until.clear()
    _sync_auth_reason.clear()
    _browser_action_last_at.clear()
    _browser_action_last_owner.clear()
    _publish_last_at.clear()
    _engagement_last_at.clear()


__all__ = [
    "GateBlock",
    "browser_action_cooldown_seconds",
    "check_browser_action_allowed",
    "check_engagement_allowed",
    "check_publish_allowed",
    "check_qr_start_allowed",
    "check_sync_auth_cooldown",
    "clear_qr_risk_block",
    "clear_sync_auth_failure",
    "engagement_account_cooldown_seconds",
    "is_security_risk_message",
    "note_browser_action",
    "note_engagement",
    "note_publish",
    "note_qr_attempt",
    "note_qr_risk_block",
    "note_sync_auth_failure",
    "publish_cooldown_seconds",
    "qr_cooldown_seconds",
    "qr_risk_block_seconds",
    "reset_gates_for_tests",
    "snapshot_risk_gates",
    "sync_auth_fail_cooldown_minutes",
]
