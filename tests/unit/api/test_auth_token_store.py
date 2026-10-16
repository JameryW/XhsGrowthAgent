"""P1-5 auth token store: memory fallback + redis path when available."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.api import auth as auth_mod


@pytest.fixture(autouse=True)
def _reset():
    auth_mod.reset_token_store_for_tests()
    yield
    auth_mod.reset_token_store_for_tests()


def test_memory_backend_roundtrip(monkeypatch):
    monkeypatch.delenv("REDIS_URI", raising=False)
    monkeypatch.setattr(auth_mod, "_try_connect_redis", lambda: None)
    auth_mod.reset_token_store_for_tests()

    tok = auth_mod.generate_token("u-1", "alice")
    assert auth_mod.get_token_backend() == "memory"
    assert auth_mod.validate_token(tok.token) is not None
    assert auth_mod.validate_token(tok.token).username == "alice"
    assert auth_mod.revoke_token(tok.token) is True
    assert auth_mod.validate_token(tok.token) is None


def test_redis_backend_when_client_available(monkeypatch):
    store: dict[str, str] = {}
    sets: dict[str, set[str]] = {}

    client = MagicMock()

    def _set(key, value, ex=None):
        store[key] = value
        return True

    def _get(key):
        return store.get(key)

    def _delete(key):
        return 1 if store.pop(key, None) is not None else 0

    def _sadd(key, member):
        sets.setdefault(key, set()).add(member)
        return 1

    def _srem(key, member):
        if key in sets:
            sets[key].discard(member)
        return 1

    def _smembers(key):
        return set(sets.get(key) or set())

    pipe = MagicMock()
    pipe.set = MagicMock(side_effect=lambda *a, **k: _set(a[0], a[1], ex=k.get("ex")))
    pipe.sadd = MagicMock(side_effect=lambda *a, **k: _sadd(a[0], a[1]))
    pipe.expire = MagicMock(return_value=True)
    pipe.execute = MagicMock(return_value=[True, True, True])
    client.pipeline.return_value = pipe
    client.get.side_effect = _get
    client.delete.side_effect = _delete
    client.srem.side_effect = _srem
    client.smembers.side_effect = _smembers
    client.ping.return_value = True

    monkeypatch.setenv("REDIS_URI", "redis://localhost:6379/0")
    monkeypatch.setattr(auth_mod, "_try_connect_redis", lambda: client)
    auth_mod.reset_token_store_for_tests()

    tok = auth_mod.generate_token("u-9", "bob")
    assert auth_mod.get_token_backend() == "redis"
    # Simulate redis GET returning what pipeline stored.
    assert store  # pipeline.set should have written
    # Manually mirror into get path (pipeline already wrote via side_effect)
    assert auth_mod.validate_token(tok.token) is not None
    n = auth_mod.revoke_user_tokens("u-9")
    assert n >= 1
