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
from typing import Any

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


def get_store_index() -> IndexConfig | None:
    """Build an IndexConfig for LangGraph store semantic search.

    Builds Embeddings object directly (requires langchain-openai) instead of
    passing a string that would need the langchain meta-package.

    Returns None if the embedding provider is not available (e.g. missing API key).
    """
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
        return None

    if not provider:
        logger.warning(
            f"Cannot determine provider from XHS_EMBED_MODEL={embed_model!r} — "
            "store semantic search disabled. Use format 'provider:model' "
            "(e.g. 'openai:text-embedding-3-small' or 'local:BAAI/bge-small-zh-v1.5')."
        )
        return None

    # Build Embeddings object directly
    model_name = embed_model.split(":", 1)[1] if ":" in embed_model else embed_model
    try:
        embeddings = _build_embeddings(provider, model_name)
    except Exception as e:
        logger.warning(f"Failed to create embeddings ({provider}:{model_name}): {e}")
        return None

    index_config: IndexConfig = {
        "embed": embeddings,
        "dims": embed_dims,
        "fields": _INDEX_FIELDS,
    }

    logger.info(f"Store semantic search enabled: model={embed_model}, dims={embed_dims}")
    return index_config


def get_prod_store_index() -> dict | None:
    """Build a PostgresIndexConfig for AsyncPostgresStore.

    Same as get_store_index() but with additional Postgres-specific settings.
    Returns a plain dict (TypedDict subclass) compatible with PostgresIndexConfig.
    """
    base = get_store_index()
    if base is None:
        return None

    # Postgres store supports cosine distance for better semantic similarity
    base["distance_type"] = "cosine"
    return base
