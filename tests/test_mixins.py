"""Tests for agent mixins."""

import pytest

from backend.agents.mixins.retry_mixin import RetryMixin
from backend.agents.mixins.validation_mixin import ValidationMixin


class TestRetryMixin:
    def test_execute_with_retry_success(self):
        """Verify RetryMixin executes action on success."""

        class MockAgent(RetryMixin):
            pass

        agent = MockAgent()
        result = agent.execute_with_retry(lambda: "success")
        assert result == "success"

    def test_execute_with_retry_retries_on_timeout(self):
        """Verify RetryMixin retries on TimeoutError."""

        class MockAgent(RetryMixin):
            pass

        call_count = 0

        def failing_action():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("timeout")
            return "success"

        agent = MockAgent()
        result = agent.execute_with_retry(failing_action, max_retries=3)
        assert result == "success"
        assert call_count == 3

    def test_execute_with_retry_raises_after_max_retries(self):
        """Verify RetryMixin raises after max retries."""

        class MockAgent(RetryMixin):
            pass

        def always_fails():
            raise TimeoutError("always timeout")

        agent = MockAgent()
        with pytest.raises(TimeoutError):
            agent.execute_with_retry(always_fails, max_retries=2)


class TestValidationMixin:
    def test_validate_state_update_valid_field(self):
        """Verify ValidationMixin passes valid fields."""
        from backend.state.schema import XHSGrowthState

        class MockAgent(ValidationMixin):
            pass

        agent = MockAgent()
        agent.validate_state_update({"phase": "testing"}, XHSGrowthState)
        # Should not raise

    def test_validate_state_update_invalid_field(self):
        """Verify ValidationMixin raises on invalid field."""
        from backend.state.schema import XHSGrowthState

        class MockAgent(ValidationMixin):
            pass

        agent = MockAgent()
        with pytest.raises(ValueError, match="Invalid field"):
            agent.validate_state_update({"invalid_field": "value"}, XHSGrowthState)
