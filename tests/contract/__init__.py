"""Contract tests package.

This package contains tests for verifying OpenAPI spec validity
and type synchronization between backend, frontend, and OpenAPI.
"""

import pytest

# Override parent conftest to avoid langgraph imports
pytest_plugins = []