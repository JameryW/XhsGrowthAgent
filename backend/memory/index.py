"""Store index configuration — enables semantic search via vector embeddings.

Without an index, store.asearch() returns items by namespace recency only.
With an index, asearch() performs true semantic similarity search.

Configuration via environment variables:
  XHS_EMBED_MODEL: embedding provider string (default: "openai:text-embedding-3-small")
  XHS_EMBED_DIMS: embedding dimensions (default: 1536)
  OPENAI_API_KEY: required for OpenAI embeddings
  DEEPSEEK_API_KEY: required when XHS_EMBED_MODEL starts with "deepseek:"
  DASHSCOPE_API_KEY: required when XHS_EMBED_MODEL starts with "dashscope:"

If the embedding provider is unavailable (e.g. missing API key), get_store_index()
returns None and the store operates without semantic search.
"""

from __future__ import annotations

import logging
import os

from langgraph.store.base import IndexConfig

logger = logging.getLogger("xhs_growth.memory.index")

# Default embedding configuration
_DEFAULT_EMBED_MODEL = "openai:text-embedding-3-small"
_DEFAULT_EMBED_DIMS = 1536

# Provider → required env var for API key
_PROVIDER_KEY_MAP: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
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
    """Extract provider prefix from embed model string (e.g. 'openai' from 'openai:text-embedding-3-small')."""
    if ":" in embed_model:
        return embed_model.split(":", 1)[0]
    return ""


def get_store_index() -> IndexConfig | None:
    """Build an IndexConfig for LangGraph store semantic search.

    Returns None if the embedding provider is not available (e.g. missing API key).
    """
    embed_model = os.environ.get("XHS_EMBED_MODEL", _DEFAULT_EMBED_MODEL)
    embed_dims = int(os.environ.get("XHS_EMBED_DIMS", str(_DEFAULT_EMBED_DIMS)))

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
            "store semantic search disabled. Use format 'provider:model' (e.g. 'openai:text-embedding-3-small')."
        )
        return None

    index_config: IndexConfig = {
        "embed": embed_model,
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
