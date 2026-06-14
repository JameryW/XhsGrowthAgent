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
        assert result["embed"] == "openai:text-embedding-3-small"
        assert "title" in result["fields"]

    @patch.dict("os.environ", {
        "OPENAI_API_KEY": "test-key",
        "XHS_EMBED_MODEL": "openai:text-embedding-3-large",
        "XHS_EMBED_DIMS": "3072",
    })
    def test_uses_custom_model_and_dims(self):
        result = get_store_index()
        assert result["embed"] == "openai:text-embedding-3-large"
        assert result["dims"] == 3072

    @patch.dict("os.environ", {"XHS_EMBED_MODEL": "cohere:embed-english-v3.0"})
    def test_returns_config_without_openai_prefix(self):
        result = get_store_index()
        assert result is not None
        assert result["embed"] == "cohere:embed-english-v3.0"


class TestGetProdStoreIndex:
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    def test_adds_cosine_distance_type(self):
        result = get_prod_store_index()
        assert result is not None
        assert result["distance_type"] == "cosine"

    def test_returns_none_when_base_is_none(self):
        result = get_prod_store_index()
        assert result is None
