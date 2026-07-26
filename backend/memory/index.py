"""Store index configuration — enables semantic search via vector embeddings.

Without an index, store.asearch() returns items by namespace recency only.
With an index, asearch() performs true semantic similarity search.

Configuration via environment variables:
  XHS_EMBED_MODEL: embedding provider string (default: "openai:text-embedding-3-small")
    Supported: "openai:<model>", "openai_compatible:<model>", "local:<model>"
  XHS_EMBED_DIMS: embedding dimensions (default: 1536)
  OPENAI_API_KEY: required for OpenAI / OpenAI-compatible embeddings
  XHS_EMBED_BASE_URL: optional base URL for OpenAI-compatible APIs (e.g. DeepSeek)

For OpenAI-compatible providers (DeepSeek, etc.), set:
  XHS_EMBED_MODEL=openai_compatible:<model_name>
  XHS_EMBED_BASE_URL=https://api.deepseek.com  (or other compatible endpoint)
  OPENAI_API_KEY=sk-...  (the key for that endpoint)

For local (CPU) embedding providers, set:
  XHS_EMBED_MODEL=local:<huggingface_model_name>
  XHS_EMBED_DIMS=<model_dims>  (e.g. 512 for bge-small-zh-v1.5)

  The local provider runs inference on-device via sentence-transformers /
  langchain-huggingface. No API key is required. Model weights are downloaded
  on first use (cached under HF_HOME / ~/.cache/huggingface). Set HF_ENDPOINT
  to a mirror (e.g. https://hf-mirror.com) if HuggingFace Hub is unreachable.

If the embedding provider is unavailable (e.g. missing API key, model download
failure), get_store_index() returns None and the store operates without
semantic search.
"""

from __future__ import annotations

import logging
import os
from typing import Any, cast

from langgraph.store.base import IndexConfig

logger = logging.getLogger("xhs_growth.memory.index")

# Default embedding configuration
_DEFAULT_EMBED_MODEL = "openai:text-embedding-3-small"
_DEFAULT_EMBED_DIMS = 1536

# Provider → required env var for API key
_PROVIDER_KEY_MAP: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openai_compatible": "OPENAI_API_KEY",
}

# Fields to index across all namespace value shapes
_INDEX_FIELDS = [
    "title",
    "body",
    "insight",
    "note",
    "preference",
    "content",
    "tone",
    "visual_style",
    # Creative memory fields
    "topic",
    "tags",
    "hashtag_style",
    "trigger_condition",
    "title_formula",
    "opening_hook",
    "niche",
    "category",
    "voice_patterns",
    "layout_preference",
]


def _resolve_provider(embed_model: str) -> str:
    """Extract provider prefix from embed model string."""
    if ":" in embed_model:
        return embed_model.split(":", 1)[0]
    return ""


def _build_embeddings(provider: str, model_name: str) -> Any:
    """Build a langchain Embeddings object for the given provider.

    Returns the Embeddings object directly, bypassing the string-based
    resolution that requires the langchain meta-package.
    """
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=model_name)
    elif provider == "openai_compatible":
        from langchain_openai import OpenAIEmbeddings

        base_url = os.environ.get("XHS_EMBED_BASE_URL", "")
        kwargs: dict[str, Any] = {"model": model_name}
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAIEmbeddings(**kwargs)
    elif provider == "local":
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(model_name=model_name)
    else:
        raise ValueError(
            f"Unsupported embed provider: {provider!r}. "
            "Use 'openai', 'openai_compatible', or 'local'."
        )


# Cache IndexConfig by env fingerprint so health checks and repeated
# compile_graph_* calls do not rebuild HuggingFace/OpenAI embeddings.
_index_cache: dict[str, IndexConfig | None] = {}


def _index_cache_key() -> str:
    """Fingerprint of env that affects index construction (no secret values)."""
    embed_model = os.environ.get("XHS_EMBED_MODEL") or _DEFAULT_EMBED_MODEL
    embed_dims = os.environ.get("XHS_EMBED_DIMS", str(_DEFAULT_EMBED_DIMS))
    base_url = os.environ.get("XHS_EMBED_BASE_URL", "")
    provider = _resolve_provider(embed_model)
    required_key = _PROVIDER_KEY_MAP.get(provider)
    # Presence only — never put API key material into the cache key.
    key_present = bool(required_key and os.environ.get(required_key))
    return f"{embed_model}|{embed_dims}|{provider}|{key_present}|{base_url}"


def clear_store_index_cache() -> None:
    """Drop cached IndexConfig entries (tests / env changes in-process)."""
    _index_cache.clear()


def semantic_index_status() -> dict[str, Any]:
    """Lightweight semantic-index readiness without constructing Embeddings.

    Used by ``/system/health`` so page-load health checks never pay for
    HuggingFace model load or OpenAI client init.
    """
    embed_model = os.environ.get("XHS_EMBED_MODEL") or _DEFAULT_EMBED_MODEL
    embed_dims_str = os.environ.get("XHS_EMBED_DIMS", str(_DEFAULT_EMBED_DIMS))
    try:
        embed_dims = int(embed_dims_str) if embed_dims_str else _DEFAULT_EMBED_DIMS
    except ValueError:
        embed_dims = _DEFAULT_EMBED_DIMS

    provider = _resolve_provider(embed_model)
    if not provider:
        return {
            "enabled": False,
            "embed_model": embed_model,
            "embed_dims": embed_dims,
            "reason": "invalid_provider",
        }

    required_key = _PROVIDER_KEY_MAP.get(provider)
    if required_key and not os.environ.get(required_key):
        return {
            "enabled": False,
            "embed_model": embed_model,
            "embed_dims": embed_dims,
            "reason": "missing_api_key",
        }

    if provider not in ("openai", "openai_compatible", "local"):
        return {
            "enabled": False,
            "embed_model": embed_model,
            "embed_dims": embed_dims,
            "reason": "unsupported_provider",
        }

    return {
        "enabled": True,
        "embed_model": embed_model,
        "embed_dims": embed_dims,
        "reason": "ok",
    }


def get_store_index() -> IndexConfig | None:
    """Build an IndexConfig for LangGraph store semantic search.

    Builds Embeddings object directly (requires langchain-openai) instead of
    passing a string that would need the langchain meta-package.

    Results are cached per env fingerprint so repeated calls (health checks,
    graph compile) do not re-download / re-init embedding models.

    Returns None if the embedding provider is not available (e.g. missing API key).
    """
    cache_key = _index_cache_key()
    if cache_key in _index_cache:
        return _index_cache[cache_key]

    embed_model = os.environ.get("XHS_EMBED_MODEL") or _DEFAULT_EMBED_MODEL
    embed_dims_str = os.environ.get("XHS_EMBED_DIMS", str(_DEFAULT_EMBED_DIMS))
    embed_dims = int(embed_dims_str) if embed_dims_str else _DEFAULT_EMBED_DIMS

    # Check if the embedding provider has required credentials
    provider = _resolve_provider(embed_model)
    required_key = _PROVIDER_KEY_MAP.get(provider)

    if required_key and not os.environ.get(required_key):
        logger.warning(
            f"{required_key} not set — store semantic search disabled. "
            f"Set {required_key} or XHS_EMBED_MODEL to enable."
        )
        _index_cache[cache_key] = None
        return None

    if not provider:
        logger.warning(
            f"Cannot determine provider from XHS_EMBED_MODEL={embed_model!r} — "
            "store semantic search disabled. Use format 'provider:model' "
            "(e.g. 'openai:text-embedding-3-small' or 'local:BAAI/bge-small-zh-v1.5')."
        )
        _index_cache[cache_key] = None
        return None

    # Build Embeddings object directly
    model_name = embed_model.split(":", 1)[1] if ":" in embed_model else embed_model
    try:
        embeddings = _build_embeddings(provider, model_name)
    except Exception as e:
        logger.warning(f"Failed to create embeddings ({provider}:{model_name}): {e}")
        # Do not cache hard failures permanently — model download may succeed later.
        return None

    index_config: IndexConfig = {
        "embed": embeddings,
        "dims": embed_dims,
        "fields": _INDEX_FIELDS,
    }

    logger.info(f"Store semantic search enabled: model={embed_model}, dims={embed_dims}")
    _index_cache[cache_key] = index_config
    return index_config


def get_prod_store_index() -> IndexConfig | None:
    """Build a PostgresIndexConfig for AsyncPostgresStore.

    Same as get_store_index() but with additional Postgres-specific settings.
    Returns an IndexConfig (TypedDict subclass) compatible with PostgresIndexConfig.
    """
    base = get_store_index()
    if base is None:
        return None

    # Copy so distance_type does not pollute the shared get_store_index cache.
    # Postgres store supports cosine distance for better semantic similarity.
    prod: dict[str, Any] = dict(cast("dict[str, Any]", base))
    prod["distance_type"] = "cosine"
    return cast("IndexConfig", prod)
