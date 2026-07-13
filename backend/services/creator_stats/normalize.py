"""Pure normalize: creator-center raw JSON → internal DTOs.

Maps field aliases used by the creator statistics surface and related
galaxy/datacenter APIs into stable internal names. No I/O.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from backend.services.creator_stats.types import (
    AccountStatsOverview,
    CreatorStatsBundle,
    NoteStats,
)

# Strip HTML so niche keywords like 育</b>儿 still match after normalize.
# Block/break tags → space (avoid gluing English tokens: my<br/>OOTD).
# Inline tags → empty (keep 育</b>儿 as 育儿 for Chinese keyword match).
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_BLOCK_RE = re.compile(
    r"<br\s*/?>|</?(?:p|div|li|tr|td|h[1-6]|section|article)(?:\s[^>]*)?/?>",
    re.IGNORECASE,
)
_HTML_WS_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    if not text or "<" not in text:
        return text
    cleaned = _HTML_BLOCK_RE.sub(" ", text)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = (
        cleaned.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return _HTML_WS_RE.sub(" ", cleaned).strip()


# Postgres INTEGER range — clamp metrics so live upserts never overflow INT4.
_MAX_METRIC_INT = 2_147_483_647


def _int_field(data: dict[str, Any], *keys: str, default: int = 0) -> int:
    """Parse a non-negative int metric (counts never go below zero)."""
    for key in keys:
        if key in data and data[key] is not None:
            val = data[key]
            try:
                if isinstance(val, bool):
                    continue
                if isinstance(val, str):
                    val = val.strip().replace(",", "")
                    if not val:
                        continue
                    # Creator APIs may serialize counts as "1234.0"
                    n = int(float(val))
                else:
                    n = int(val)
                return max(0, min(n, _MAX_METRIC_INT))
            except (TypeError, ValueError, OverflowError):
                continue
    return default


def _note_id_str(raw_id: Any) -> str:
    """Stable string note id — ints/whole floats become '123' not '123.0'."""
    if raw_id is None or isinstance(raw_id, (bool, list, dict)):
        return ""
    if isinstance(raw_id, int) and not isinstance(raw_id, bool):
        return str(raw_id)
    if isinstance(raw_id, float):
        if raw_id != raw_id:  # NaN
            return ""
        # Whole floats from JSON numbers (and 1e2 → 100.0)
        try:
            if abs(raw_id) < 1e15 and raw_id == int(raw_id):
                return str(int(raw_id))
        except (OverflowError, ValueError):
            return ""
        return str(raw_id).strip()
    s = str(raw_id).strip()
    if not s or s.lower() in ("none", "null"):
        return ""
    # Stringified whole floats: "123.0"
    if s.count(".") == 1 and s.replace(".", "", 1).isdigit():
        try:
            f = float(s)
            if f == int(f) and abs(f) < 1e15:
                return str(int(f))
        except (TypeError, ValueError, OverflowError):
            pass
    return s


def _str_field(data: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        if key in data and data[key] is not None:
            return str(data[key]).strip()
    return default


_PROFILE_FIELD_KEYS: tuple[str, ...] = (
    "userId",
    "user_id",
    "userName",
    "user_name",
    "redId",
    "red_id",
    "userAvatar",
    "user_avatar",
    "userDesc",
    "user_desc",
    "role",
    "zone",
)


def _profile_text(data: dict[str, Any], *keys: str) -> str:
    """Return a scalar profile field without serializing nested API metadata."""
    for key in keys:
        value = data.get(key)
        if value is None or isinstance(value, (bool, dict, list)):
            continue
        return str(value).strip()
    return ""


def normalize_account_profile(raw: dict[str, Any] | None) -> dict[str, str]:
    """Whitelist public Creator Center identity fields from a current-user payload."""
    if not isinstance(raw, dict):
        return {
            "creator_user_id": "",
            "creator_name": "",
            "red_id": "",
            "avatar_url": "",
            "bio": "",
            "creator_role": "",
            "zone": "",
        }

    candidates = [raw]
    for candidate in candidates:
        for key in ("data", "result", "profile", "user", "user_info", "userInfo"):
            nested = candidate.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)
    data = next(
        (
            candidate
            for candidate in candidates
            if any(key in candidate for key in _PROFILE_FIELD_KEYS)
        ),
        {},
    )
    return {
        "creator_user_id": _profile_text(data, "userId", "user_id", "uid"),
        "creator_name": _profile_text(data, "userName", "user_name", "nickname", "name"),
        "red_id": _profile_text(data, "redId", "red_id"),
        "avatar_url": _profile_text(data, "userAvatar", "user_avatar", "avatar", "avatar_url"),
        "bio": _profile_text(data, "userDesc", "user_desc", "description", "desc"),
        "creator_role": _profile_text(data, "role", "user_role"),
        "zone": _profile_text(data, "zone", "location", "region"),
    }


# Keys used by creator-center note list envelopes (galaxy/datacenter variants)
_NOTE_LIST_KEYS: tuple[str, ...] = (
    "notes",
    "note_list",
    "note_infos",
    "noteInfos",
    "list",
    "items",
    "records",
    "data",
)


def extract_note_items(raw: Any) -> list[Any]:
    """Extract a flat list of note dict-ish items from list or envelope payloads.

    Shared by the HTTP client pagination loop and normalize_note_list so field
    aliases stay in one place.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []
    for key in _NOTE_LIST_KEYS:
        val = raw.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            for sub in _NOTE_LIST_KEYS:
                if sub == "data":
                    continue
                nested = val.get(sub)
                if isinstance(nested, list):
                    return nested
    # Single note object
    if raw.get("note_id") or raw.get("id") or raw.get("noteId"):
        return [raw]
    return []


def _clean_tag_token(item: Any) -> str | None:
    if item is None or isinstance(item, bool):
        return None
    if isinstance(item, dict):
        name = item.get("name") or item.get("tag") or item.get("title")
        text = str(name).strip() if name is not None else ""
    else:
        text = str(item).strip()
    if not text or text.lower() == "none":
        return None
    return text


def _list_str_field(data: dict[str, Any], *keys: str) -> list[str]:
    """Extract string list fields (tags/topics); order-preserving de-dupe."""
    for key in keys:
        val = data.get(key)
        if val is None:
            continue
        out: list[str] = []
        seen: set[str] = set()
        if isinstance(val, list):
            for item in val:
                token = _clean_tag_token(item)
                if token and token not in seen:
                    seen.add(token)
                    out.append(token)
            return out
        if isinstance(val, str) and val.strip():
            for p in (t.strip() for t in val.split(",")):
                if p and p not in seen:
                    seen.add(p)
                    out.append(p)
            return out
    return []


def _content_type(raw: Any) -> str:
    if raw is None:
        return "note"
    s = str(raw).lower()
    if s in ("video", "1", "v"):
        return "video"
    if s in ("carousel", "multi", "2"):
        return "carousel"
    if s in ("normal", "0", "image", "note", ""):
        return "note"
    # Unknown numeric types from APIs → generic note rather than "3"
    if s.isdigit():
        return "note"
    return s if s else "note"


def _unix_to_iso(ts: float) -> str:
    # Creator APIs often use ms timestamps
    if ts > 1e12:
        ts = ts / 1000.0
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def _publish_time(data: dict[str, Any]) -> str:
    """Normalize publish timestamps (unix ms/s or ISO strings) to ISO-ish text."""
    raw = (
        data.get("published_at")
        or data.get("publish_time")
        or data.get("create_time")
        or data.get("time")
        or data.get("post_time")
        or ""
    )
    if raw is None or raw == "":
        return ""
    if isinstance(raw, bool):
        return ""
    if isinstance(raw, (int, float)):
        try:
            return _unix_to_iso(float(raw))
        except (OverflowError, OSError, ValueError):
            return str(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return ""
        # Numeric string timestamps (seconds or ms)
        if s.isdigit() or (s.replace(".", "", 1).isdigit() and s.count(".") <= 1):
            try:
                return _unix_to_iso(float(s))
            except (OverflowError, OSError, ValueError):
                return s
        return s
    return str(raw)


def compute_engagement_rate(
    views: int, likes: int, comments: int, collects: int, shares: int
) -> float:
    if views <= 0:
        return 0.0
    return round((likes + comments + collects + shares) / views, 4)


def normalize_account_overview(
    raw: dict[str, Any],
    account_id: str,
    *,
    period: str = "30d",
    synced_at: str | None = None,
    profile_raw: dict[str, Any] | None = None,
) -> AccountStatsOverview:
    """Map a creator-center account overview payload to AccountStatsOverview."""
    # Current Creator Center returns ``data.seven`` / ``data.thirty`` from
    # /api/galaxy/v2/creator/datacenter/account/base.  Select the requested
    # bucket before the generic envelope aliases below; otherwise the outer
    # envelope has no metric keys and every account total silently becomes 0.
    data = raw
    root_data = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(root_data, dict):
        bucket_key = "seven" if period == "7d" else "thirty"
        bucket = root_data.get(bucket_key)
        if isinstance(bucket, dict):
            data = bucket
        elif any(
            k in root_data
            for k in (
                "view_count",
                "viewCount",
                "views",
                "like_count",
                "likeCount",
                "likes",
                "fans_count",
                "note_count",
            )
        ):
            data = root_data

    # Nested data envelopes used by older galaxy APIs.
    for key in ("data", "result", "account_data", "overview"):
        if data is not raw:
            break
        nested = data.get(key) if isinstance(data, dict) else None
        if isinstance(nested, dict) and any(
            k in nested
            for k in (
                "view_count",
                "viewCount",
                "views",
                "like_count",
                "likeCount",
                "likes",
                "fans_count",
                "note_count",
            )
        ):
            data = nested
            break

    profile = normalize_account_profile(profile_raw if profile_raw is not None else raw)
    now = synced_at or datetime.now(UTC).isoformat()
    return AccountStatsOverview(
        account_id=account_id,
        **profile,
        views=_int_field(
            data, "views", "view_count", "viewCount", "home_view_count", "impression_count"
        ),
        likes=_int_field(data, "likes", "like_count", "likeCount", "liked_count"),
        comments=_int_field(data, "comments", "comment_count", "commentCount", "comments_count"),
        collects=_int_field(
            data,
            "collects",
            "collect_count",
            "collectCount",
            "collected_count",
            "fav_count",
            "favorite_count",
        ),
        shares=_int_field(data, "shares", "share_count", "shareCount", "shared_count"),
        fans=_int_field(
            data, "fans", "fans_count", "fansCount", "follower_count", "net_rise_fans_count"
        ),
        # Avoid generic "total" — galaxy payloads often use total for page size/total hits
        note_count=_int_field(
            data,
            "note_count",
            "noteCount",
            "notes_count",
            "note_number",
            "publish_count",
            "publish_note_num",
        ),
        period=period,
        synced_at=now,
        source="creator_statistics",
    )


def normalize_note(
    raw: dict[str, Any],
    account_id: str,
    *,
    synced_at: str | None = None,
) -> NoteStats | None:
    """Map a single creator-center note stats row. Returns None if no note id."""
    data = raw
    # Some list items nest metrics under interact_info / data
    metrics = data
    for key in ("interact_info", "data", "note_card", "stat"):
        nested = data.get(key) if isinstance(data, dict) else None
        if isinstance(nested, dict):
            # Prefer nested for metrics but keep outer for title/id
            metrics = {**nested, **{k: v for k, v in data.items() if k not in nested}}
            break

    note_id = ""
    for src in (data, metrics):
        for key in ("note_id", "id", "noteId", "note_id_str"):
            raw_id = src.get(key) if isinstance(src, dict) else None
            note_id = _note_id_str(raw_id)
            if note_id:
                break
        if note_id:
            break
    if not note_id:
        return None

    views = _int_field(metrics, "views", "view_count", "viewCount", "read_count", "impression")
    likes = _int_field(metrics, "likes", "like_count", "likeCount", "liked_count")
    comments = _int_field(metrics, "comments", "comment_count", "commentCount", "comments_count")
    collects = _int_field(
        metrics,
        "collects",
        "collect_count",
        "collectCount",
        "collected_count",
        "fav_count",
        "favorite_count",
    )
    shares = _int_field(metrics, "shares", "share_count", "shareCount", "shared_count")

    title = _str_field(data, "title", "display_title", "note_title", "name")
    if not title:
        title = _str_field(metrics, "title", "display_title")

    # Body snippet for niche infer / analysis — truncate to keep rows small
    body_text = _str_field(
        data,
        "body_text",
        "body",
        "content",
        "desc",
        "description",
        "note_desc",
        "text",
    )
    if not body_text:
        body_text = _str_field(metrics, "body", "content", "desc", "description")
    body_text = _strip_html(body_text)
    if len(body_text) > 2000:
        body_text = body_text[:2000]

    content_type = _content_type(
        data.get("content_type")
        or data.get("note_type")
        or data.get("type")
        or metrics.get("note_type")
    )
    tags = _list_str_field(data, "tags", "tag_list", "topics", "hashtags")
    cover = _str_field(data, "cover_url", "cover", "image", "cover_image")
    if not cover:
        images = data.get("images_list")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                cover = _str_field(first, "url", "image_url", "origin_url", "preview_url")
            elif isinstance(first, str):
                cover = first.strip()
    published = _publish_time(data) or _publish_time(metrics)
    now = synced_at or datetime.now(UTC).isoformat()

    note = NoteStats(
        note_id=note_id,
        account_id=account_id,
        title=title,
        body_text=body_text,
        views=views,
        likes=likes,
        comments=comments,
        collects=collects,
        shares=shares,
        published_at=published,
        content_type=content_type,
        tags=tags,
        cover_url=cover,
        engagement_rate=compute_engagement_rate(views, likes, comments, collects, shares),
        synced_at=now,
        source="creator_statistics",
    )
    return note


def normalize_note_list(
    raw: Any,
    account_id: str,
    *,
    synced_at: str | None = None,
) -> list[NoteStats]:
    """Map a creator-center note list payload (list or envelope) to NoteStats rows.

    Duplicate note_ids keep the **last** occurrence (later pagination pages
    overwrite earlier ones so fresher metrics win).
    """
    items = extract_note_items(raw)

    by_id: dict[str, NoteStats] = {}
    order: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        note = normalize_note(item, account_id, synced_at=synced_at)
        if note is None:
            continue
        if note.note_id not in by_id:
            order.append(note.note_id)
        by_id[note.note_id] = note
    return [by_id[nid] for nid in order]


def normalize_bundle(
    account_raw: dict[str, Any] | None,
    notes_raw: Any,
    account_id: str,
    *,
    period: str = "30d",
    synced_at: str | None = None,
    profile_raw: dict[str, Any] | None = None,
) -> CreatorStatsBundle:
    """Build a full CreatorStatsBundle from raw account + notes payloads."""
    now = synced_at or datetime.now(UTC).isoformat()
    account = normalize_account_overview(
        account_raw or {},
        account_id,
        period=period,
        synced_at=now,
        profile_raw=profile_raw,
    )
    notes = normalize_note_list(notes_raw, account_id, synced_at=now)
    if account.note_count == 0 and notes:
        account.note_count = len(notes)
    # Fill account totals from notes when overview is empty
    if account.views == 0 and notes:
        account.views = sum(n.views for n in notes)
        account.likes = sum(n.likes for n in notes)
        account.comments = sum(n.comments for n in notes)
        account.collects = sum(n.collects for n in notes)
        account.shares = sum(n.shares for n in notes)
    return CreatorStatsBundle(account=account, notes=notes)
