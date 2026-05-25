"""Contract tests conftest - overrides parent to avoid langgraph dependency."""

import pytest

# Block parent conftest from loading by providing empty fixtures
# This allows contract tests to run without langgraph installed


@pytest.fixture
def initial_state():
    """Placeholder - not used in contract tests."""
    pass


@pytest.fixture
def mock_llm():
    """Placeholder - not used in contract tests."""
    pass


@pytest.fixture
def mock_store():
    """Placeholder - not used in contract tests."""
    pass