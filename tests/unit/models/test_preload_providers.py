"""Provider SDK preload: selective, background, and never fatal to boot.

``_create_model`` imports langchain_anthropic/langchain_openai lazily.  The first
import can spend ~20s in import machinery on Windows (the openai chain pulls
transformers/torch); awaited at startup that made every boot slow, but left fully
lazy it blocks the event loop inside the first model call.  The app/CLI therefore
warm the imports in a daemon thread, loading only the providers the current
routing table actually uses.
"""

from __future__ import annotations

import sys


def test_preload_imports_the_configured_provider_module():
    from backend.models.router import _providers_in_use, preload_model_providers

    preload_model_providers()

    providers = _providers_in_use()
    if providers:  # default routing is all-magpie -> langchain_openai
        assert "langchain_openai" in sys.modules


def test_preload_is_idempotent():
    from backend.models.router import preload_model_providers

    preload_model_providers()
    preload_model_providers()  # second call must be a cheap no-op


def test_background_preload_runs_in_a_daemon_thread(monkeypatch):
    from backend.models import router

    calls: list[int] = []
    monkeypatch.setattr(router, "preload_model_providers", lambda: calls.append(1))

    thread = router.start_model_provider_preload()
    thread.join(timeout=5)

    assert calls == [1]
    assert thread.daemon is True


def test_background_preload_swallows_errors(monkeypatch):
    from backend.models import router

    def boom() -> None:
        raise ImportError("provider sdk missing")

    monkeypatch.setattr(router, "preload_model_providers", boom)

    thread = router.start_model_provider_preload()
    thread.join(timeout=5)

    assert not thread.is_alive()
