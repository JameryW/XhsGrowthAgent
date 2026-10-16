"""Authentication utilities — token generation and validation.

P1-5: Prefer Redis (+ TTL) when ``REDIS_URI`` / ``Settings().database.redis_uri``
is reachable; otherwise fall back to process memory. Logs
``backend=redis|memory`` so operators can see which store is active.
"""

from __future__ import annotations

import contextlib
import json
import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel

logger = logging.getLogger("xhs_growth.auth")

TokenBackend = Literal["redis", "memory"]


class TokenData(BaseModel):
    """Token payload data."""

    token: str
    user_id: str
    username: str
    created_at: datetime
    expires_at: datetime


# In-memory token store (fallback when Redis is unavailable)
_active_tokens: dict[str, TokenData] = {}
_backend: TokenBackend = "memory"
_redis_client: Any | None = None
_redis_lock = threading.Lock()
_TOKEN_KEY_PREFIX = "xhs:auth:token:"
_USER_INDEX_PREFIX = "xhs:auth:user:"


def _redis_uri() -> str:
    import os

    from backend.config.settings import Settings

    env_uri = (os.environ.get("REDIS_URI") or "").strip()
    if env_uri:
        return env_uri
    try:
        return str(Settings().database.redis_uri or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _expire_hours() -> int:
    from backend.config.settings import Settings

    try:
        hours = int(Settings().auth.token_expire_hours)
    except Exception:  # noqa: BLE001
        hours = 24
    return max(1, hours)


def _token_key(token: str) -> str:
    return f"{_TOKEN_KEY_PREFIX}{token}"


def _user_index_key(user_id: str) -> str:
    return f"{_USER_INDEX_PREFIX}{user_id}"


def _serialize(token_data: TokenData) -> str:
    return json.dumps(
        {
            "token": token_data.token,
            "user_id": token_data.user_id,
            "username": token_data.username,
            "created_at": token_data.created_at.isoformat(),
            "expires_at": token_data.expires_at.isoformat(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _deserialize(raw: str | bytes | None) -> TokenData | None:
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        data = json.loads(text)
        return TokenData(
            token=str(data["token"]),
            user_id=str(data["user_id"]),
            username=str(data["username"]),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            expires_at=datetime.fromisoformat(str(data["expires_at"])),
        )
    except Exception:  # noqa: BLE001
        return None


def _try_connect_redis() -> Any | None:
    """Best-effort sync Redis client. Returns None on any failure."""
    uri = _redis_uri()
    if not uri:
        return None
    # Skip obvious localhost placeholders when host looks unset — still try connect.
    try:
        import redis

        client = redis.Redis.from_url(
            uri,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=1.0,
        )
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        logger.info("auth token store redis unavailable (%s) — using memory", exc)
        return None


def _ensure_backend() -> TokenBackend:
    """Lazy-init Redis; degrade to memory. Thread-safe."""
    global _backend, _redis_client
    if _backend == "redis" and _redis_client is not None:
        return _backend
    with _redis_lock:
        if _backend == "redis" and _redis_client is not None:
            return _backend
        client = _try_connect_redis()
        if client is not None:
            _redis_client = client
            _backend = "redis"
            host = urlparse(_redis_uri()).hostname or "redis"
            logger.info("auth token store backend=redis host=%s", host)
        else:
            _redis_client = None
            _backend = "memory"
            logger.info("auth token store backend=memory")
    return _backend


def get_token_backend() -> TokenBackend:
    """Return the active token store backend (redis|memory)."""
    return _ensure_backend()


def reset_token_store_for_tests() -> None:
    """Test helper — clear memory tokens and force re-detect backend."""
    global _backend, _redis_client
    _active_tokens.clear()
    with _redis_lock:
        if _redis_client is not None:
            with contextlib.suppress(Exception):
                _redis_client.close()
        _redis_client = None
        _backend = "memory"


def generate_token(user_id: str, username: str) -> TokenData:
    """Generate a new authentication token and store it (Redis or memory)."""
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires_at = now + timedelta(hours=_expire_hours())
    token_data = TokenData(
        token=token,
        user_id=user_id,
        username=username,
        created_at=now,
        expires_at=expires_at,
    )

    backend = _ensure_backend()
    ttl_seconds = max(1, int((expires_at - now).total_seconds()))
    if backend == "redis" and _redis_client is not None:
        try:
            pipe = _redis_client.pipeline()
            pipe.set(_token_key(token), _serialize(token_data), ex=ttl_seconds)
            pipe.sadd(_user_index_key(user_id), token)
            pipe.expire(_user_index_key(user_id), ttl_seconds)
            pipe.execute()
            return token_data
        except Exception as exc:  # noqa: BLE001
            logger.warning("auth redis set failed (%s) — falling back to memory", exc)
            _fallback_memory()

    _active_tokens[token] = token_data
    return token_data


def _fallback_memory() -> None:
    global _backend, _redis_client
    with _redis_lock:
        _redis_client = None
        _backend = "memory"
    logger.info("auth token store backend=memory")


def validate_token(token: str) -> TokenData | None:
    """Validate an authentication token against Redis or memory."""
    if not token:
        return None
    backend = _ensure_backend()
    if backend == "redis" and _redis_client is not None:
        try:
            raw = _redis_client.get(_token_key(token))
            token_data = _deserialize(raw)
            if token_data is None:
                return None
            if token_data.expires_at < datetime.now():
                revoke_token(token)
                return None
            return token_data
        except Exception as exc:  # noqa: BLE001
            logger.warning("auth redis get failed (%s) — falling back to memory", exc)
            _fallback_memory()

    token_data = _active_tokens.get(token)
    if not token_data:
        return None
    if token_data.expires_at < datetime.now():
        _active_tokens.pop(token, None)
        return None
    return token_data


def revoke_token(token: str) -> bool:
    """Revoke (invalidate) a token."""
    backend = _ensure_backend()
    removed = False
    if backend == "redis" and _redis_client is not None:
        try:
            raw = _redis_client.get(_token_key(token))
            data = _deserialize(raw)
            deleted = bool(_redis_client.delete(_token_key(token)))
            if data is not None:
                _redis_client.srem(_user_index_key(data.user_id), token)
            removed = deleted
        except Exception as exc:  # noqa: BLE001
            logger.warning("auth redis delete failed (%s) — falling back to memory", exc)
            _fallback_memory()
    if token in _active_tokens:
        _active_tokens.pop(token, None)
        removed = True
    return removed


def revoke_user_tokens(user_id: str) -> int:
    """Revoke ALL active tokens belonging to a user."""
    backend = _ensure_backend()
    count = 0
    if backend == "redis" and _redis_client is not None:
        try:
            tokens = list(_redis_client.smembers(_user_index_key(user_id)) or [])
            for tok in tokens:
                if revoke_token(str(tok)):
                    count += 1
            _redis_client.delete(_user_index_key(user_id))
            return count
        except Exception as exc:  # noqa: BLE001
            logger.warning("auth redis revoke_user failed (%s) — falling back to memory", exc)
            _fallback_memory()

    victims = [tok for tok, data in _active_tokens.items() if data.user_id == user_id]
    for tok in victims:
        _active_tokens.pop(tok, None)
    return len(victims)


async def verify_credentials_async(username: str, password: str) -> dict[str, Any] | None:
    """DB-backed credential verification — the only auth path.

    Returns the user on match, None otherwise. Errors propagate so the route
    layer can return a real 5xx instead of silently letting a hardcoded
    admin slip through.
    """
    from backend.db.console_users import verify_login

    user = await verify_login(username, password)
    if user is None:
        return None
    return {"id": user.id, "username": user.username}


__all__ = [
    "TokenData",
    "generate_token",
    "get_token_backend",
    "reset_token_store_for_tests",
    "validate_token",
    "revoke_token",
    "revoke_user_tokens",
    "verify_credentials_async",
]
