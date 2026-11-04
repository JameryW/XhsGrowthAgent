"""Provider SDKs are imported once, off the event loop, before graph nodes run.

``_create_model`` imports langchain_anthropic/langchain_openai lazily.  When the
first import happened inside an async node it blocked the loop for seconds, which
stalled API requests and checkpoint writes; the API lifespan and ``xhs-growth
run`` now call :func:`preload_model_providers` in a worker thread at startup.
"""

from __future__ import annotations

import sys


def test_preload_imports_both_provider_sdks():
    from backend.models.router import preload_model_providers

    preload_model_providers()

    assert "langchain_openai" in sys.modules
    assert "langchain_anthropic" in sys.modules


def test_preload_is_idempotent():
    from backend.models.router import preload_model_providers

    preload_model_providers()
    preload_model_providers()  # second call must be a cheap no-op
