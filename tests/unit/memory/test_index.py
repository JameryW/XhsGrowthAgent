"""Unit tests for store index configuration."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from backend.memory.index import get_prod_store_index, get_store_index


class TestGetStoreIndex:
    @patch.dict("os.environ", {}, clear=True)
    def test_returns_none_without_openai_key(self):
        result = get_store_index()
        assert result is None

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True)
    def test_returns_config_with_openai_key(self):
        result = get_store_index()
        assert result is not None
        assert result["dims"] == 1536
        # embed is now an Embeddings object, not a string
        assert result["embed"] is not None
        assert "title" in result["fields"]

    @patch.dict(
        "os.environ",
        {
            "OPENAI_API_KEY": "test-key",
            "XHS_EMBED_MODEL": "openai:text-embedding-3-large",
            "XHS_EMBED_DIMS": "3072",
        },
        clear=True,
    )
    def test_uses_custom_model_and_dims(self):
        result = get_store_index()
        assert result is not None
        assert result["dims"] == 3072
        # Verify the embeddings object was created with the right model
        embed_obj = result["embed"]
        assert embed_obj is not None

    @patch.dict(
        "os.environ",
        {
            "OPENAI_API_KEY": "test-key",
            "XHS_EMBED_MODEL": "openai_compatible:deepseek-embedding",
            "XHS_EMBED_BASE_URL": "https://api.deepseek.com",
            "XHS_EMBED_DIMS": "1536",
        },
        clear=True,
    )
    def test_openai_compatible_uses_base_url(self):
        result = get_store_index()
        assert result is not None
        assert result["dims"] == 1536
        embed_obj = result["embed"]
        assert embed_obj is not None

    @patch.dict("os.environ", {"XHS_EMBED_MODEL": "unsupported:model"}, clear=True)
    def test_returns_none_for_unsupported_provider(self):
        result = get_store_index()
        assert result is None

    @patch.dict("os.environ", {"XHS_EMBED_MODEL": "", "XHS_EMBED_DIMS": ""}, clear=True)
    def test_handles_empty_env_vars(self):
        # Empty strings should fall back to defaults, not crash
        # But without OPENAI_API_KEY, still returns None
        result = get_store_index()
        assert result is None


class TestLocalProvider:
    """local provider runs HuggingFaceEmbeddings on CPU — no API key needed."""

    @patch.dict(
        "os.environ",
        {"XHS_EMBED_MODEL": "local:BAAI/bge-small-zh-v1.5", "XHS_EMBED_DIMS": "512"},
        clear=True,
    )
    def test_local_provider_no_api_key(self):
        """local provider builds IndexConfig without any API key."""
        mock_module = MagicMock()
        mock_embeddings = MagicMock()
        mock_module.HuggingFaceEmbeddings = MagicMock(return_value=mock_embeddings)
        with patch.dict(sys.modules, {"langchain_huggingface": mock_module}):
            result = get_store_index()
        assert result is not None
        assert result["dims"] == 512
        assert result["embed"] is mock_embeddings
        assert "title" in result["fields"]
        mock_module.HuggingFaceEmbeddings.assert_called_once_with(
            model_name="BAAI/bge-small-zh-v1.5"
        )

    @patch.dict(
        "os.environ",
        {"XHS_EMBED_MODEL": "local:BAAI/bge-small-zh-v1.5", "XHS_EMBED_DIMS": "512"},
        clear=True,
    )
    def test_local_provider_does_not_need_openai_key(self):
        """Even with OPENAI_API_KEY unset, local provider works."""
        # clear=True already removes OPENAI_API_KEY — verify it still returns config
        mock_module = MagicMock()
        mock_module.HuggingFaceEmbeddings = MagicMock(return_value=MagicMock())
        with patch.dict(sys.modules, {"langchain_huggingface": mock_module}):
            result = get_store_index()
        assert result is not None

    @patch.dict(
        "os.environ",
        {"XHS_EMBED_MODEL": "local:BAAI/bge-small-zh-v1.5", "XHS_EMBED_DIMS": "512"},
        clear=True,
    )
    def test_local_provider_failure_returns_none(self):
        """Construction failure (e.g. model download error) returns None gracefully."""
        mock_module = MagicMock()
        mock_module.HuggingFaceEmbeddings = MagicMock(
            side_effect=RuntimeError("model download failed")
        )
        with patch.dict(sys.modules, {"langchain_huggingface": mock_module}):
            result = get_store_index()
        assert result is None

    @patch.dict(
        "os.environ",
        {"XHS_EMBED_MODEL": "local:BAAI/bge-small-zh-v1.5", "XHS_EMBED_DIMS": "512"},
        clear=True,
    )
    def test_local_provider_prod_index_adds_cosine(self):
        """get_prod_store_index adds distance_type=cosine for local provider."""
        mock_module = MagicMock()
        mock_module.HuggingFaceEmbeddings = MagicMock(return_value=MagicMock())
        with patch.dict(sys.modules, {"langchain_huggingface": mock_module}):
            result = get_prod_store_index()
        assert result is not None
        assert result["distance_type"] == "cosine"
        assert result["dims"] == 512


class TestGetProdStoreIndex:
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True)
    def test_adds_cosine_distance_type(self):
        result = get_prod_store_index()
        assert result is not None
        assert result["distance_type"] == "cosine"

    @patch.dict("os.environ", {}, clear=True)
    def test_returns_none_when_base_is_none(self):
        result = get_prod_store_index()
        assert result is None
