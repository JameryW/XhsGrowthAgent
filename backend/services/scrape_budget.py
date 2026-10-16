"""Per-account daily scrape budgets + minimized scrape cache (P1-2).

Caps (env / account overridable):
- XHS_SCRAPE_HOMEFEED_DAILY_LIMIT (default 50)
- XHS_SCRAPE_SEARCH_DAILY_LIMIT (default 50)
- XHS_SCRAPE_COMMENTS_DAILY_LIMIT (default 100)

On exhaust: serve recent account cache when present; otherwise raise
``ScrapeBudgetExhaustedError`` with ``error_code=scrape_budget_exhausted``.
Never invent fake platform rows.
"""

from __future__ import annotations

import logging
import math
import os
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("xhs_growth.scrape_budget")

ERROR_SCRAPE_BUDGET_EXHAUSTED = "scrape_budget_exhausted"

_KINDS = ("homefeed", "search", "comments")

# account_id -> {day_key: {kind: count}}
_daily_counts: dict[str, dict[str, dict[str, int]]] = {}
# account_id -> {kind: {"at": iso, "payload": list}}
_recent_cache: dict[str, dict[str, dict[str, Any]]] = {}
# optional per-account limit overrides: account_id -> {kind: int}
_account_limits: dict[str, dict[str, int]] = {}


class ScrapeBudgetExhaustedError(RuntimeError):
    """No remaining daily scrape budget and no usable cache."""

    error_code = ERROR_SCRAPE_BUDGET_EXHAUSTED

    def __init__(
        self,
        message: str = "抓取日预算已耗尽，且无近期缓存可回退",
        *,
        account_id: str = "",
        kind: str = "",
        limit: int = 0,
        used: int = 0,
    ) -> None:
        super().__init__(message)
        self.account_id = account_id
        self.kind = kind
        self.limit = limit
        self.used = used


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(float(value)):
        return default
    return max(0, value)


def _utc_day_key() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def default_limits() -> dict[str, int]:
    return {
        "homefeed": _env_int("XHS_SCRAPE_HOMEFEED_DAILY_LIMIT", 50),
        "search": _env_int("XHS_SCRAPE_SEARCH_DAILY_LIMIT", 50),
        "comments": _env_int("XHS_SCRAPE_COMMENTS_DAILY_LIMIT", 100),
    }


def set_account_limits(account_id: str, **limits: int | None) -> dict[str, int]:
    """Optional per-account overrides (None leaves existing / drops on replace)."""
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("account_id is required")
    current = dict(_account_limits.get(account_id) or {})
    for kind in _KINDS:
        if kind not in limits:
            continue
        value = limits[kind]
        if value is None:
            current.pop(kind, None)
            continue
        current[kind] = max(0, int(value))
    if current:
        _account_limits[account_id] = current
    else:
        _account_limits.pop(account_id, None)
    return get_limits(account_id)


def get_limits(account_id: str = "") -> dict[str, int]:
    limits = default_limits()
    account_id = (account_id or "").strip()
    if account_id:
        for kind, value in (_account_limits.get(account_id) or {}).items():
            if kind in _KINDS:
                limits[kind] = max(0, int(value))
    return limits


def _counts_for(account_id: str) -> dict[str, int]:
    day = _utc_day_key()
    by_day = _daily_counts.setdefault(account_id, {})
    bucket = by_day.setdefault(day, {k: 0 for k in _KINDS})
    for kind in _KINDS:
        bucket.setdefault(kind, 0)
    return bucket


def usage(account_id: str = "") -> dict[str, Any]:
    account_id = (account_id or "").strip()
    limits = get_limits(account_id)
    counts = _counts_for(account_id) if account_id else {k: 0 for k in _KINDS}
    return {
        "account_id": account_id or None,
        "day": _utc_day_key(),
        "limits": limits,
        "used": {k: int(counts.get(k) or 0) for k in _KINDS},
        "remaining": {k: max(0, int(limits[k]) - int(counts.get(k) or 0)) for k in _KINDS},
    }


def mask_nickname(value: str | None) -> str:
    """Mask another user's nickname for storage (keep first/last when long)."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 1:
        return "*"
    if len(text) == 2:
        return text[0] + "*"
    return text[0] + ("*" * min(4, len(text) - 2)) + text[-1]


def mask_user_id(value: str | None) -> str:
    """Mask platform user id — keep short prefix/suffix only."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "***"
    return text[:2] + "…" + text[-2:]


_ID_KEYS = frozenset(
    {
        "user_id",
        "userid",
        "uid",
        "author_id",
        "authorId",
        "userId",
        "red_id",
        "redId",
        "xsec_token",
    }
)
_NICK_KEYS = frozenset(
    {
        "nickname",
        "nick_name",
        "user_name",
        "username",
        "author_name",
        "authorName",
        "name",
        "display_name",
    }
)


def minimize_scrape_row(row: Any) -> Any:
    """Deep-copy a scrape row/list and mask others' nicknames / IDs by default."""
    if isinstance(row, list):
        return [minimize_scrape_row(item) for item in row]
    if not isinstance(row, dict):
        return row
    out: dict[str, Any] = {}
    for key, value in row.items():
        key_str = str(key)
        key_l = key_str.lower()
        if isinstance(value, (dict, list)):
            out[key_str] = minimize_scrape_row(value)
            continue
        if key_str in _ID_KEYS or key_l in {k.lower() for k in _ID_KEYS}:
            out[key_str] = mask_user_id(str(value) if value is not None else "")
        elif key_str in _NICK_KEYS or key_l in {k.lower() for k in _NICK_KEYS}:
            # Avoid masking our own generic title fields that share "name".
            if key_l == "name" and any(
                k in row for k in ("title", "topic", "heat_score", "note_id")
            ):
                out[key_str] = value
            else:
                out[key_str] = mask_nickname(str(value) if value is not None else "")
        else:
            out[key_str] = value
    return out


def store_cache(account_id: str, kind: str, payload: list[Any]) -> list[Any]:
    """Minimize + store recent scrape payload for budget fallback."""
    account_id = (account_id or "").strip()
    kind = (kind or "").strip()
    if kind not in _KINDS:
        raise ValueError(f"unknown scrape kind: {kind}")
    minimized_raw = minimize_scrape_row(list(payload or []))
    minimized: list[Any] = list(minimized_raw) if isinstance(minimized_raw, list) else []
    if account_id:
        _recent_cache.setdefault(account_id, {})[kind] = {
            "at": datetime.now(UTC).isoformat(),
            "payload": deepcopy(minimized),
        }
    return minimized


def get_cache(account_id: str, kind: str) -> list[Any] | None:
    account_id = (account_id or "").strip()
    kind = (kind or "").strip()
    if not account_id or kind not in _KINDS:
        return None
    entry = (_recent_cache.get(account_id) or {}).get(kind)
    if not isinstance(entry, dict):
        return None
    payload = entry.get("payload")
    if not isinstance(payload, list) or not payload:
        return None
    return deepcopy(payload)


def consume_or_cache(
    account_id: str,
    kind: str,
    *,
    fetch_fn_result: list[Any] | None = None,
    prefer_cache_on_exhaust: bool = True,
) -> list[Any]:
    """Record one scrape unit. On exhaust return cache or raise.

    Callers that already fetched should pass ``fetch_fn_result`` after a
    successful network read; this stores the minimized payload and increments.
    When budget is already exhausted, returns cache (if any) without increment
    and without accepting a new fetch result.
    """
    account_id = (account_id or "").strip()
    kind = (kind or "").strip()
    if kind not in _KINDS:
        raise ValueError(f"unknown scrape kind: {kind}")
    limits = get_limits(account_id)
    limit = int(limits[kind])
    counts = _counts_for(account_id) if account_id else {k: 0 for k in _KINDS}
    used = int(counts.get(kind) or 0)

    if account_id and used >= limit > 0:
        if prefer_cache_on_exhaust:
            cached = get_cache(account_id, kind)
            if cached is not None:
                logger.info(
                    "scrape budget exhausted account=%s kind=%s — serving cache (%s rows)",
                    account_id,
                    kind,
                    len(cached),
                )
                return cached
        raise ScrapeBudgetExhaustedError(
            account_id=account_id,
            kind=kind,
            limit=limit,
            used=used,
        )

    if fetch_fn_result is None:
        # Pre-check only (no increment) — used by gate helpers.
        return []

    if account_id:
        minimized = store_cache(account_id, kind, fetch_fn_result)
    else:
        minimized = minimize_scrape_row(list(fetch_fn_result))
    if account_id and limit > 0:
        counts[kind] = used + 1
    return minimized


def check_budget(account_id: str, kind: str) -> list[Any] | None:
    """Pre-flight: None if allowed; cache list if exhausted-with-cache; else raise."""
    account_id = (account_id or "").strip()
    kind = (kind or "").strip()
    if kind not in _KINDS:
        raise ValueError(f"unknown scrape kind: {kind}")
    if not account_id:
        return None
    limits = get_limits(account_id)
    limit = int(limits[kind])
    if limit <= 0:
        # 0 = hard-disabled: only cache, never live scrape.
        cached = get_cache(account_id, kind)
        if cached is not None:
            return cached
        raise ScrapeBudgetExhaustedError(account_id=account_id, kind=kind, limit=limit, used=0)
    used = int(_counts_for(account_id).get(kind) or 0)
    if used < limit:
        return None
    cached = get_cache(account_id, kind)
    if cached is not None:
        return cached
    raise ScrapeBudgetExhaustedError(account_id=account_id, kind=kind, limit=limit, used=used)


def record_success(account_id: str, kind: str, payload: list[Any]) -> list[Any]:
    """Increment usage after a live scrape and store minimized cache."""
    return consume_or_cache(account_id, kind, fetch_fn_result=list(payload or []))


def purge_cache_before(cutoff: datetime) -> int:
    """Drop cached scrape rows older than ``cutoff``. Returns removed entry count."""
    removed = 0
    for account_id, by_kind in list(_recent_cache.items()):
        for kind, entry in list(by_kind.items()):
            at_raw = str((entry or {}).get("at") or "")
            try:
                at = datetime.fromisoformat(at_raw.replace("Z", "+00:00"))
                if at.tzinfo is None:
                    at = at.replace(tzinfo=UTC)
            except ValueError:
                at = None
            if at is None or at < cutoff:
                by_kind.pop(kind, None)
                removed += 1
        if not by_kind:
            _recent_cache.pop(account_id, None)
    return removed


def reset_for_tests() -> None:
    _daily_counts.clear()
    _recent_cache.clear()
    _account_limits.clear()


# Keep regex available for future URL/id redaction helpers (imported by tests).
_USER_ID_RE = re.compile(r"^[0-9a-fA-F]{16,}$")

__all__ = [
    "ERROR_SCRAPE_BUDGET_EXHAUSTED",
    "ScrapeBudgetExhaustedError",
    "check_budget",
    "default_limits",
    "get_cache",
    "get_limits",
    "mask_nickname",
    "mask_user_id",
    "minimize_scrape_row",
    "purge_cache_before",
    "record_success",
    "reset_for_tests",
    "set_account_limits",
    "store_cache",
    "usage",
]
