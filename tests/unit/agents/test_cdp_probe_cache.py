"""The container-CDP probe is cached with a short TTL, not for the process lifetime.

``socket.gethostbyname('host.containers.internal')`` can block for the full DNS
timeout when the name does not exist, so publishing must not re-probe on every
attempt.  But Chrome may be started after the backend, so a negative answer must
expire: the cache is time-bounded instead of permanent.
"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    from backend.agents import publisher

    publisher._clear_cdp_probe_cache()
    yield
    publisher._clear_cdp_probe_cache()


def _fake_clock(monkeypatch, start: float = 1000.0):
    from backend.agents import publisher

    clock = {"now": start}
    monkeypatch.setattr(publisher, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    return clock


def test_negative_probe_is_cached_until_ttl(monkeypatch):
    from backend.agents import publisher

    clock = _fake_clock(monkeypatch)
    calls = {"n": 0}

    def failing_resolve(_host: str) -> str:
        calls["n"] += 1
        raise OSError("name does not exist")

    monkeypatch.setattr(publisher.socket, "gethostbyname", failing_resolve)

    assert publisher._probe_container_cdp_endpoint() == ""
    assert publisher._probe_container_cdp_endpoint() == ""
    assert calls["n"] == 1  # second call served from the cache

    clock["now"] += publisher._CDP_PROBE_TTL_SECONDS + 1
    assert publisher._probe_container_cdp_endpoint() == ""
    assert calls["n"] == 2  # TTL expired: Chrome appearing later is re-probed


def test_positive_probe_is_cached_and_returned(monkeypatch):
    from backend.agents import publisher

    clock = _fake_clock(monkeypatch)
    calls = {"n": 0}

    def resolving(_host: str) -> str:
        calls["n"] += 1
        return "10.0.0.7"

    monkeypatch.setattr(publisher.socket, "gethostbyname", resolving)
    monkeypatch.setattr(publisher.socket, "create_connection", lambda *a, **k: nullcontext())

    assert publisher._probe_container_cdp_endpoint() == "http://10.0.0.7:9223"
    clock["now"] += 10
    assert publisher._probe_container_cdp_endpoint() == "http://10.0.0.7:9223"
    assert calls["n"] == 1


def test_clear_cache_lets_a_new_chrome_be_found(monkeypatch):
    from backend.agents import publisher

    _fake_clock(monkeypatch)
    monkeypatch.setattr(
        publisher.socket, "gethostbyname", lambda _host: (_ for _ in ()).throw(OSError("no"))
    )
    assert publisher._probe_container_cdp_endpoint() == ""

    monkeypatch.setattr(publisher.socket, "gethostbyname", lambda _host: "10.0.0.9")
    monkeypatch.setattr(publisher.socket, "create_connection", lambda *a, **k: nullcontext())
    publisher._clear_cdp_probe_cache()

    assert publisher._probe_container_cdp_endpoint() == "http://10.0.0.9:9223"
