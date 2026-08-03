"""Process-local risk gates for QR login, browser CDP actions, and sync.

Keeps short-term cooldowns in memory so operators cannot hammer XHS with
repeated QR starts, back-to-back browser features, or auth-failed crawls
after a risk hit (300012) / expired creator session.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("xhs_growth.risk_gate")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return value if math.isfinite(value) else default


# Per-account override keys (seconds unless *_minutes / min_risk_pressure).
_POLICY_FIELDS = (
    "browser_action_seconds",
    "publish_seconds",
    "engagement_seconds",
    "sync_auth_minutes",
    "qr_cooldown_seconds",
    "qr_risk_block_seconds",
    # Floor for creator-stats crawl clamps (0=normal, 1=SAFE_MODE, 2=list-only).
    "min_risk_pressure",
)

# account_id -> partial policy overrides
_policies: dict[str, dict[str, float]] = {}


def global_cooldown_defaults() -> dict[str, float]:
    """Global env-backed defaults (not including per-account overrides)."""
    # SAFE_MODE env acts as a global floor of 1 when enabled.
    env_safe = 1.0 if _env_float("CREATOR_STATS_SAFE_MODE", 0) >= 1 else 0.0
    return {
        "browser_action_seconds": max(0.0, _env_float("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", 20.0)),
        "publish_seconds": max(0.0, _env_float("XHS_PUBLISH_COOLDOWN_SECONDS", 90.0)),
        "engagement_seconds": max(0.0, _env_float("XHS_ENGAGEMENT_ACCOUNT_COOLDOWN_SECONDS", 30.0)),
        "sync_auth_minutes": max(
            0.0, _env_float("CREATOR_STATS_AUTH_FAIL_COOLDOWN_MINUTES", 120.0)
        ),
        "qr_cooldown_seconds": max(0.0, _env_float("XHS_QR_LOGIN_COOLDOWN_SECONDS", 900.0)),
        "qr_risk_block_seconds": max(0.0, _env_float("XHS_QR_RISK_BLOCK_SECONDS", 3600.0)),
        "min_risk_pressure": env_safe,
    }


def get_cooldown_policy(account_id: str = "") -> dict[str, Any]:
    """Effective policy for an account = globals + optional overrides."""
    account_id = (account_id or "").strip()
    defaults = global_cooldown_defaults()
    overrides = dict(_policies.get(account_id) or {}) if account_id else {}
    effective = dict(defaults)
    for key, value in overrides.items():
        if key in _POLICY_FIELDS:
            try:
                num = max(0.0, float(value))
            except (TypeError, ValueError):
                continue
            if key == "min_risk_pressure":
                num = max(0.0, min(2.0, num))
            effective[key] = num
    # Always clamp pressure fields for display.
    try:
        effective["min_risk_pressure"] = max(
            0.0, min(2.0, float(effective.get("min_risk_pressure") or 0))
        )
    except (TypeError, ValueError):
        effective["min_risk_pressure"] = 0.0
    return {
        "account_id": account_id or None,
        "defaults": defaults,
        "overrides": overrides,
        "effective": effective,
    }


def set_cooldown_policy(
    account_id: str,
    *,
    browser_action_seconds: float | None = None,
    publish_seconds: float | None = None,
    engagement_seconds: float | None = None,
    sync_auth_minutes: float | None = None,
    qr_cooldown_seconds: float | None = None,
    qr_risk_block_seconds: float | None = None,
    min_risk_pressure: float | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Set per-account cool-down overrides. ``None`` fields leave existing values.

    Pass ``replace=True`` to replace the whole override map (missing fields = default).
    ``min_risk_pressure`` is clamped to 0–2 (creator-stats SAFE_MODE floor).
    """
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("account_id is required")
    incoming = {
        "browser_action_seconds": browser_action_seconds,
        "publish_seconds": publish_seconds,
        "engagement_seconds": engagement_seconds,
        "sync_auth_minutes": sync_auth_minutes,
        "qr_cooldown_seconds": qr_cooldown_seconds,
        "qr_risk_block_seconds": qr_risk_block_seconds,
        "min_risk_pressure": min_risk_pressure,
    }
    current: dict[str, float] = {} if replace else dict(_policies.get(account_id) or {})
    for key, value in incoming.items():
        if value is None:
            if replace:
                current.pop(key, None)
            continue
        try:
            num = max(0.0, float(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {key}: {value!r}") from exc
        if key == "min_risk_pressure":
            num = max(0.0, min(2.0, num))
        current[key] = num
    if current:
        _policies[account_id] = current
    else:
        _policies.pop(account_id, None)
    _schedule_persist()
    return get_cooldown_policy(account_id)


def account_min_risk_pressure(account_id: str = "") -> int:
    """Per-account floor for creator-stats risk pressure (0–2)."""
    value = _policy_value(
        account_id,
        "min_risk_pressure",
        1.0 if _env_float("CREATOR_STATS_SAFE_MODE", 0) >= 1 else 0.0,
    )
    try:
        return max(0, min(2, int(value)))
    except (TypeError, ValueError):
        return 0


def clear_cooldown_policy(account_id: str = "") -> dict[str, Any]:
    """Remove per-account overrides (empty account_id clears all policies)."""
    account_id = (account_id or "").strip()
    removed = 0
    if not account_id:
        removed = len(_policies)
        _policies.clear()
    elif account_id in _policies:
        _policies.pop(account_id, None)
        removed = 1
    if removed:
        _schedule_persist()
    return {"account_id": account_id or None, "removed": removed}


def _policy_value(account_id: str, field: str, global_default: float) -> float:
    account_id = (account_id or "").strip()
    if account_id:
        raw = (_policies.get(account_id) or {}).get(field)
        if raw is not None:
            try:
                return max(0.0, float(raw))
            except (TypeError, ValueError):
                pass
    return max(0.0, float(global_default))


def qr_cooldown_seconds(account_id: str = "") -> float:
    """Min gap between QR start attempts for the same account (0 disables)."""
    return _policy_value(
        account_id,
        "qr_cooldown_seconds",
        _env_float("XHS_QR_LOGIN_COOLDOWN_SECONDS", 900.0),
    )


def qr_risk_block_seconds(account_id: str = "") -> float:
    """How long to block QR after a security/IP risk hit (0 disables)."""
    return _policy_value(
        account_id,
        "qr_risk_block_seconds",
        _env_float("XHS_QR_RISK_BLOCK_SECONDS", 3600.0),
    )


def sync_auth_fail_cooldown_minutes(account_id: str = "") -> float:
    """Extra cooldown after creator auth failure / empty-shell risk (0 disables)."""
    return _policy_value(
        account_id,
        "sync_auth_minutes",
        _env_float("CREATOR_STATS_AUTH_FAIL_COOLDOWN_MINUTES", 120.0),
    )


def browser_action_cooldown_seconds(account_id: str = "") -> float:
    """Min gap after any CDP session ends before another feature starts (0 disables)."""
    return _policy_value(
        account_id,
        "browser_action_seconds",
        _env_float("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", 20.0),
    )


def publish_cooldown_seconds(account_id: str = "") -> float:
    """Min gap between publish attempts for the same account (0 disables)."""
    return _policy_value(
        account_id,
        "publish_seconds",
        _env_float("XHS_PUBLISH_COOLDOWN_SECONDS", 90.0),
    )


def engagement_account_cooldown_seconds(account_id: str = "") -> float:
    """Min gap between engagement sessions for the same account (0 disables).

    Complements the per-action pacing inside XHSEngagement.
    """
    return _policy_value(
        account_id,
        "engagement_seconds",
        _env_float("XHS_ENGAGEMENT_ACCOUNT_COOLDOWN_SECONDS", 30.0),
    )


def _account_id_from_profile_key(key: str) -> str:
    text = str(key or "")
    if text.startswith("account:"):
        return text[len("account:") :]
    return ""


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
# Wall-clock ISO mirrors for durable persistence across restarts.
_qr_last_attempt_wall: dict[str, str] = {}
_qr_risk_until_wall: dict[str, str] = {}
_sync_auth_until_wall: dict[str, str] = {}
_browser_action_wall: dict[str, str] = {}
_publish_wall: dict[str, str] = {}
_engagement_wall: dict[str, str] = {}
_persist_task: asyncio.Task[None] | None = None
_hydrated = False


def _now() -> float:
    return time.monotonic()


def _wall_now() -> str:
    return datetime.now(UTC).isoformat()


def _remaining(deadline: float) -> int:
    return max(0, int(deadline - _now() + 0.999))


def _parse_wall(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)
    except ValueError:
        return None


def _mono_from_wall_event(raw: str) -> float | None:
    """Map a past wall-clock event onto the current monotonic clock."""
    ts = _parse_wall(raw)
    if ts is None:
        return None
    age = (datetime.now(UTC) - ts).total_seconds()
    if age < 0:
        age = 0.0
    return _now() - age


def _mono_deadline_from_wall(raw: str) -> float | None:
    """Map a future wall-clock deadline onto the current monotonic clock."""
    ts = _parse_wall(raw)
    if ts is None:
        return None
    remaining = (ts - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        return None
    return _now() + remaining


def _schedule_persist() -> None:
    """Debounced best-effort durable write (no-op outside a running loop)."""
    global _persist_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run() -> None:
        await asyncio.sleep(0.05)
        try:
            await persist_risk_gates()
        except Exception:
            logger.debug("risk gate persist failed", exc_info=True)

    if _persist_task is not None and not _persist_task.done():
        _persist_task.cancel()
    _persist_task = loop.create_task(_run())


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

    cooldown = qr_cooldown_seconds(account_id)
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
        _qr_last_attempt_wall[account_id] = _wall_now()
        _schedule_persist()


def note_qr_risk_block(account_id: str, *, reason: str = "300012") -> None:
    """Block further QR starts after a confirmed security hit."""
    account_id = (account_id or "").strip()
    if not account_id:
        return
    block_s = qr_risk_block_seconds(account_id)
    if block_s <= 0:
        return
    _qr_risk_blocked_until[account_id] = _now() + block_s
    _qr_risk_reason[account_id] = reason
    _qr_risk_until_wall[account_id] = (datetime.now(UTC) + timedelta(seconds=block_s)).isoformat()
    # Also push the attempt clock so cooldown stacks with the risk block.
    _qr_last_attempt_at[account_id] = _now()
    _qr_last_attempt_wall[account_id] = _wall_now()
    _schedule_persist()


def clear_qr_risk_block(account_id: str) -> None:
    account_id = (account_id or "").strip()
    _qr_risk_blocked_until.pop(account_id, None)
    _qr_risk_reason.pop(account_id, None)
    _qr_risk_until_wall.pop(account_id, None)
    _schedule_persist()


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
    minutes = sync_auth_fail_cooldown_minutes(account_id)
    if minutes <= 0:
        return
    block_s = minutes * 60.0
    _sync_auth_blocked_until[account_id] = _now() + block_s
    _sync_auth_reason[account_id] = reason
    _sync_auth_until_wall[account_id] = (datetime.now(UTC) + timedelta(seconds=block_s)).isoformat()
    _schedule_persist()


def clear_sync_auth_failure(account_id: str) -> None:
    account_id = (account_id or "").strip()
    _sync_auth_blocked_until.pop(account_id, None)
    _sync_auth_reason.pop(account_id, None)
    _sync_auth_until_wall.pop(account_id, None)
    _schedule_persist()


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
    _browser_action_wall[key] = _wall_now()
    _schedule_persist()


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
    aid = (account_id or "").strip() or _account_id_from_profile_key(
        _profile_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    )
    cooldown = browser_action_cooldown_seconds(aid)
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
    _publish_wall[key] = _wall_now()
    _schedule_persist()


def check_publish_allowed(account_id: str = "", *, cdp_endpoint: str = "") -> GateBlock | None:
    """Min gap between publishes for one account/profile."""
    aid = (account_id or "").strip() or _account_id_from_profile_key(
        _profile_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    )
    cooldown = publish_cooldown_seconds(aid)
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
    _engagement_wall[key] = _wall_now()
    _schedule_persist()


def check_engagement_allowed(account_id: str = "", *, cdp_endpoint: str = "") -> GateBlock | None:
    """Min gap between engagement *sessions* for one account/profile."""
    aid = (account_id or "").strip() or _account_id_from_profile_key(
        _profile_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    )
    cooldown = engagement_account_cooldown_seconds(aid)
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


def list_active_cooldowns(*, account_id: str = "") -> list[dict[str, Any]]:
    """Return active cool-downs with remaining seconds (newest first).

    When ``account_id`` is set, only entries for that account/profile are
    returned (``account:{id}`` keys and bare account-id auth/QR blocks).
    """
    now = _now()
    account_id = (account_id or "").strip()
    account_key = f"account:{account_id}" if account_id else ""
    rows: list[dict[str, Any]] = []

    def _want_key(key: str) -> bool:
        if not account_id:
            return True
        return key in (account_key, account_id) or key.endswith(f":{account_id}")

    def _want_aid(aid: str) -> bool:
        if not account_id:
            return True
        return aid == account_id

    # browser action (event-based cool-down)
    for key, last in list(_browser_action_last_at.items()):
        if not _want_key(key):
            continue
        aid = _account_id_from_profile_key(key)
        browser_cd = browser_action_cooldown_seconds(aid)
        if browser_cd <= 0:
            continue
        owner = _browser_action_last_owner.get(key, "unknown")
        # Report full gap remaining (feature-switch baseline).
        remaining = browser_cd - (now - last)
        if remaining <= 0:
            continue
        rows.append(
            {
                "kind": "browser_action",
                "key": key,
                "owner": owner,
                "retry_after_seconds": int(remaining + 0.999),
                "message": f"浏览器操作冷却（上一任务 {owner}）",
            }
        )

    # publish / engagement (event-based)
    for key, last in list(_publish_last_at.items()):
        if not _want_key(key):
            continue
        aid = _account_id_from_profile_key(key)
        pub_cd = publish_cooldown_seconds(aid)
        if pub_cd <= 0:
            continue
        remaining = pub_cd - (now - last)
        if remaining <= 0:
            continue
        rows.append(
            {
                "kind": "publish",
                "key": key,
                "retry_after_seconds": int(remaining + 0.999),
                "message": "发布冷却",
            }
        )
    for key, last in list(_engagement_last_at.items()):
        if not _want_key(key):
            continue
        aid = _account_id_from_profile_key(key)
        eng_cd = engagement_account_cooldown_seconds(aid)
        if eng_cd <= 0:
            continue
        remaining = eng_cd - (now - last)
        if remaining <= 0:
            continue
        rows.append(
            {
                "kind": "engagement",
                "key": key,
                "retry_after_seconds": int(remaining + 0.999),
                "message": "互动会话冷却",
            }
        )

    # deadline-based blocks
    for aid, until in list(_sync_auth_blocked_until.items()):
        if not _want_aid(aid) or until <= now:
            continue
        rows.append(
            {
                "kind": "sync_auth",
                "key": aid,
                "reason": _sync_auth_reason.get(aid, "AUTH_EXPIRED"),
                "retry_after_seconds": _remaining(until),
                "message": "创作者中心鉴权冷却",
            }
        )
    for aid, until in list(_qr_risk_blocked_until.items()):
        if not _want_aid(aid) or until <= now:
            continue
        rows.append(
            {
                "kind": "qr_risk",
                "key": aid,
                "reason": _qr_risk_reason.get(aid, "security_risk"),
                "retry_after_seconds": _remaining(until),
                "message": "扫码安全限制冷却",
            }
        )
    for aid, last in list(_qr_last_attempt_at.items()):
        if not _want_aid(aid):
            continue
        qr_cd = qr_cooldown_seconds(aid)
        if qr_cd <= 0:
            continue
        remaining = qr_cd - (now - last)
        if remaining <= 0:
            continue
        rows.append(
            {
                "kind": "qr_attempt",
                "key": aid,
                "retry_after_seconds": int(remaining + 0.999),
                "message": "扫码登录间隔冷却",
            }
        )

    rows.sort(key=lambda r: int(r.get("retry_after_seconds") or 0), reverse=True)
    return rows


def clear_account_cooldowns(
    account_id: str = "", *, kinds: list[str] | None = None
) -> dict[str, Any]:
    """Clear cool-downs for one account (or all keys when account_id empty).

    ``kinds`` optional filter: browser_action, publish, engagement, sync_auth,
    qr_risk, qr_attempt. None/empty clears all kinds.
    """
    account_id = (account_id or "").strip()
    kind_set = {k.strip() for k in (kinds or []) if k and str(k).strip()}
    clear_all_kinds = not kind_set
    account_key = f"account:{account_id}" if account_id else ""
    cleared: dict[str, int] = {}

    def _match_profile_key(key: str) -> bool:
        if not account_id:
            return True
        return key in (account_key, account_id)

    def _match_aid(aid: str) -> bool:
        if not account_id:
            return True
        return aid == account_id

    def _do(kind: str) -> bool:
        return clear_all_kinds or kind in kind_set

    if _do("browser_action"):
        n = 0
        for key in list(_browser_action_last_at.keys()):
            if not _match_profile_key(key):
                continue
            _browser_action_last_at.pop(key, None)
            _browser_action_last_owner.pop(key, None)
            _browser_action_wall.pop(key, None)
            n += 1
        cleared["browser_action"] = n

    if _do("publish"):
        n = 0
        for key in list(_publish_last_at.keys()):
            if not _match_profile_key(key):
                continue
            _publish_last_at.pop(key, None)
            _publish_wall.pop(key, None)
            n += 1
        cleared["publish"] = n

    if _do("engagement"):
        n = 0
        for key in list(_engagement_last_at.keys()):
            if not _match_profile_key(key):
                continue
            _engagement_last_at.pop(key, None)
            _engagement_wall.pop(key, None)
            n += 1
        cleared["engagement"] = n

    if _do("sync_auth"):
        n = 0
        for aid in list(_sync_auth_blocked_until.keys()):
            if not _match_aid(aid):
                continue
            _sync_auth_blocked_until.pop(aid, None)
            _sync_auth_reason.pop(aid, None)
            _sync_auth_until_wall.pop(aid, None)
            n += 1
        cleared["sync_auth"] = n

    if _do("qr_risk"):
        n = 0
        for aid in list(_qr_risk_blocked_until.keys()):
            if not _match_aid(aid):
                continue
            _qr_risk_blocked_until.pop(aid, None)
            _qr_risk_reason.pop(aid, None)
            _qr_risk_until_wall.pop(aid, None)
            n += 1
        cleared["qr_risk"] = n

    if _do("qr_attempt"):
        n = 0
        for aid in list(_qr_last_attempt_at.keys()):
            if not _match_aid(aid):
                continue
            _qr_last_attempt_at.pop(aid, None)
            _qr_last_attempt_wall.pop(aid, None)
            n += 1
        cleared["qr_attempt"] = n

    _schedule_persist()
    total = sum(cleared.values())
    return {
        "account_id": account_id or None,
        "cleared": cleared,
        "total": total,
    }


def snapshot_risk_gates() -> dict[str, Any]:
    """Compact operator-facing gate snapshot for /health."""
    now = _now()
    browser_active = 0
    for key, last in _browser_action_last_at.items():
        aid = _account_id_from_profile_key(key)
        if now - last < browser_action_cooldown_seconds(aid):
            browser_active += 1
    auth_active = sum(1 for until in _sync_auth_blocked_until.values() if until > now)
    qr_risk_active = sum(1 for until in _qr_risk_blocked_until.values() if until > now)
    active = list_active_cooldowns()
    defaults = global_cooldown_defaults()
    return {
        "browser_action_cooldown_seconds": defaults["browser_action_seconds"],
        "publish_cooldown_seconds": defaults["publish_seconds"],
        "engagement_account_cooldown_seconds": defaults["engagement_seconds"],
        "active_browser_cooldowns": browser_active,
        "active_sync_auth_blocks": auth_active,
        "active_qr_risk_blocks": qr_risk_active,
        "durable": _hydrated,
        "browser_action_keys": len(_browser_action_last_at),
        "publish_keys": len(_publish_last_at),
        "engagement_keys": len(_engagement_last_at),
        "policy_accounts": len(_policies),
        "active": active,
        "active_count": len(active),
        "max_retry_after_seconds": (
            max((int(r.get("retry_after_seconds") or 0) for r in active), default=0)
        ),
    }


def export_risk_gate_state() -> dict[str, Any]:
    """Wall-clock snapshot suitable for durable storage."""
    browser: dict[str, Any] = {}
    for key, at in _browser_action_wall.items():
        browser[key] = {
            "at": at,
            "owner": _browser_action_last_owner.get(key, "unknown"),
        }
    sync_auth: dict[str, Any] = {}
    for aid, until in _sync_auth_until_wall.items():
        sync_auth[aid] = {
            "until": until,
            "reason": _sync_auth_reason.get(aid, "AUTH_EXPIRED"),
        }
    qr_risk: dict[str, Any] = {}
    for aid, until in _qr_risk_until_wall.items():
        qr_risk[aid] = {
            "until": until,
            "reason": _qr_risk_reason.get(aid, "security_risk"),
        }
    policies: dict[str, Any] = {}
    for aid, policy in _policies.items():
        policies[str(aid)] = dict(policy)
    return {
        "browser_action": browser,
        "publish": dict(_publish_wall),
        "engagement": dict(_engagement_wall),
        "sync_auth": sync_auth,
        "qr_risk": qr_risk,
        "qr_last_attempt": dict(_qr_last_attempt_wall),
        "policies": policies,
    }


async def persist_risk_gates() -> None:
    """Write current cool-downs to durable storage."""
    from backend.db.risk_gates import save_risk_gate_state

    await save_risk_gate_state(export_risk_gate_state())


async def hydrate_risk_gates() -> None:
    """Load durable cool-downs into process memory (call once at app start)."""
    global _hydrated
    from backend.db.risk_gates import load_risk_gate_state

    data = await load_risk_gate_state()
    # browser_action
    for key, raw in (data.get("browser_action") or {}).items():
        if not isinstance(raw, dict):
            continue
        at = _mono_from_wall_event(str(raw.get("at") or ""))
        if at is None:
            continue
        _browser_action_last_at[str(key)] = at
        _browser_action_last_owner[str(key)] = str(raw.get("owner") or "unknown")
        _browser_action_wall[str(key)] = str(raw.get("at") or "")
    for key, raw_at in (data.get("publish") or {}).items():
        at = _mono_from_wall_event(str(raw_at or ""))
        if at is None:
            continue
        _publish_last_at[str(key)] = at
        _publish_wall[str(key)] = str(raw_at or "")
    for key, raw_at in (data.get("engagement") or {}).items():
        at = _mono_from_wall_event(str(raw_at or ""))
        if at is None:
            continue
        _engagement_last_at[str(key)] = at
        _engagement_wall[str(key)] = str(raw_at or "")
    for aid, raw in (data.get("sync_auth") or {}).items():
        if not isinstance(raw, dict):
            continue
        until = _mono_deadline_from_wall(str(raw.get("until") or ""))
        if until is None:
            continue
        _sync_auth_blocked_until[str(aid)] = until
        _sync_auth_reason[str(aid)] = str(raw.get("reason") or "AUTH_EXPIRED")
        _sync_auth_until_wall[str(aid)] = str(raw.get("until") or "")
    for aid, raw in (data.get("qr_risk") or {}).items():
        if not isinstance(raw, dict):
            continue
        until = _mono_deadline_from_wall(str(raw.get("until") or ""))
        if until is None:
            continue
        _qr_risk_blocked_until[str(aid)] = until
        _qr_risk_reason[str(aid)] = str(raw.get("reason") or "security_risk")
        _qr_risk_until_wall[str(aid)] = str(raw.get("until") or "")
    for aid, raw_at in (data.get("qr_last_attempt") or {}).items():
        at = _mono_from_wall_event(str(raw_at or ""))
        if at is None:
            continue
        _qr_last_attempt_at[str(aid)] = at
        _qr_last_attempt_wall[str(aid)] = str(raw_at or "")
    for aid, raw_policy in (data.get("policies") or {}).items():
        if not isinstance(raw_policy, dict):
            continue
        cleaned: dict[str, float] = {}
        for field in _POLICY_FIELDS:
            if field not in raw_policy:
                continue
            try:
                num = max(0.0, float(raw_policy[field]))
            except (TypeError, ValueError):
                continue
            if field == "min_risk_pressure":
                num = max(0.0, min(2.0, num))
            cleaned[field] = num
        if cleaned:
            _policies[str(aid)] = cleaned
    _hydrated = True
    logger.info(
        "risk gates hydrated: browser=%s publish=%s engagement=%s auth=%s qr_risk=%s policies=%s",
        len(_browser_action_last_at),
        len(_publish_last_at),
        len(_engagement_last_at),
        len(_sync_auth_blocked_until),
        len(_qr_risk_blocked_until),
        len(_policies),
    )


def reset_gates_for_tests() -> None:
    """Test helper — clear all in-memory gates."""
    global _hydrated, _persist_task
    _qr_last_attempt_at.clear()
    _qr_risk_blocked_until.clear()
    _qr_risk_reason.clear()
    _sync_auth_blocked_until.clear()
    _sync_auth_reason.clear()
    _browser_action_last_at.clear()
    _browser_action_last_owner.clear()
    _publish_last_at.clear()
    _engagement_last_at.clear()
    _qr_last_attempt_wall.clear()
    _qr_risk_until_wall.clear()
    _sync_auth_until_wall.clear()
    _browser_action_wall.clear()
    _publish_wall.clear()
    _engagement_wall.clear()
    _policies.clear()
    _hydrated = False
    if _persist_task is not None and not _persist_task.done():
        _persist_task.cancel()
    _persist_task = None


__all__ = [
    "GateBlock",
    "browser_action_cooldown_seconds",
    "check_browser_action_allowed",
    "check_engagement_allowed",
    "check_publish_allowed",
    "check_qr_start_allowed",
    "check_sync_auth_cooldown",
    "clear_account_cooldowns",
    "clear_cooldown_policy",
    "clear_qr_risk_block",
    "clear_sync_auth_failure",
    "engagement_account_cooldown_seconds",
    "export_risk_gate_state",
    "get_cooldown_policy",
    "global_cooldown_defaults",
    "hydrate_risk_gates",
    "is_security_risk_message",
    "list_active_cooldowns",
    "note_browser_action",
    "note_engagement",
    "note_publish",
    "note_qr_attempt",
    "note_qr_risk_block",
    "note_sync_auth_failure",
    "persist_risk_gates",
    "publish_cooldown_seconds",
    "qr_cooldown_seconds",
    "qr_risk_block_seconds",
    "reset_gates_for_tests",
    "account_min_risk_pressure",
    "set_cooldown_policy",
    "snapshot_risk_gates",
    "sync_auth_fail_cooldown_minutes",
]
