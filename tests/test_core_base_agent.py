"""Tests for core.base_agent module."""
import pytest
from backend.core.base_agent import BaseAgent


def test_base_agent_import():
    """Verify BaseAgent can be imported from core."""
    assert BaseAgent is not None


def test_base_agent_is_abstract():
    """Verify BaseAgent is abstract class."""
    with pytest.raises(TypeError):
        BaseAgent()  # Cannot instantiate abstract class