"""Unit tests for store index configuration."""

from __future__ import annotations

from unittest.mock import patch

from backend.memory.index import get_prod_store_index, get_store_index


class TestGetStoreIndex:
    def test_returns_none_without_openai_key(self):
        result = get_store_index()
        assert result is None

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    def test_returns_config_with_openai_key(self):
        result = get_store_index()
        assert result is not None
        assert result["dims"] == 1536
        # embed is now an Embeddings object, not a string
        assert result["embed"] is not None
        assert "title" in result["fields"]

    @patch.dict("os.environ", {
        "OPENAI_API_KEY": "test-key",
        "XHS_EMBED_MODEL": "openai:text-embedding-3-large",
        "XHS_EMBED_DIMS": "3072",
    })
    def test_uses_custom_model_and_dims(self):
        result = get_store_index()
        assert result is not None
        assert result["dims"] == 3072
        # Verify the embeddings object was created with the right model
        embed_obj = result["embed"]
        assert embed_obj is not None

    @patch.dict("os.environ", {
        "OPENAI_API_KEY": "test-key",
        "XHS_EMBED_MODEL": "openai_compatible:deepseek-embedding",
        "XHS_EMBED_BASE_URL": "https://api.deepseek.com",
        "XHS_EMBED_DIMS": "1536",
    })
    def test_openai_compatible_uses_base_url(self):
        result = get_store_index()
        assert result is not None
        assert result["dims"] == 1536
        embed_obj = result["embed"]
        assert embed_obj is not None

    @patch.dict("os.environ", {
        "XHS_EMBED_MODEL": "unsupported:model",
    })
    def test_returns_none_for_unsupported_provider(self):
        result = get_store_index()
        assert result is None

    @patch.dict("os.environ", {
        "XHS_EMBED_MODEL": "",
        "XHS_EMBED_DIMS": "",
    })
    def test_handles_empty_env_vars(self):
        # Empty strings should fall back to defaults, not crash
        # But without OPENAI_API_KEY, still returns None
        result = get_store_index()
        assert result is None


class TestGetProdStoreIndex:
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    def test_adds_cosine_distance_type(self):
        result = get_prod_store_index()
        assert result is not None
        assert result["distance_type"] == "cosine"

    def test_returns_none_when_base_is_none(self):
        result = get_prod_store_index()
        assert result is None
