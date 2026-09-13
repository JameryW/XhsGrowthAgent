"""P0-W3: lightweight error taxonomy written to state by handle_agent_error.

handle_agent_error must classify the failure into the shared taxonomy
(transient / semantic / side_effect_unknown / policy_violation / auth_expired)
and record it in the new `error_class` state field. Routing behavior is NOT
changed in P0: unknown errors default to `transient` (old behavior).
"""

from backend.core.error_handling import classify_error, handle_agent_error


class TestErrorTaxonomy:
    def test_timeout_is_transient(self):
        assert classify_error(TimeoutError("read timed out")) == "transient"

    def test_connection_error_is_transient(self):
        assert classify_error(ConnectionResetError("reset")) == "transient"

    def test_rate_limit_message_is_transient(self):
        assert classify_error(RuntimeError("HTTP 429 Too Many Requests")) == "transient"

    def test_malformed_output_is_semantic(self):
        assert classify_error(ValueError("invalid JSON output from model")) == "semantic"

    def test_auth_expired_is_classified(self):
        assert classify_error(RuntimeError("401 unauthorized, cookie expired")) == "auth_expired"

    def test_default_is_transient_preserving_old_routing(self):
        assert classify_error(RuntimeError("something odd")) == "transient"

    def test_handle_agent_error_writes_error_class_field(self):
        result = handle_agent_error(TimeoutError("boom"), {"retry_count": 0}, agent_name="x")
        assert result["error_class"] == "transient"
        # Existing behavior must be untouched.
        assert result["phase"].value == "error"
        assert result["retry_count"] == 1
        assert result["current_agent"] == "x"

    def test_handle_agent_error_semantic_class(self):
        result = handle_agent_error(
            ValueError("could not parse model response"),
            {"retry_count": 1},
            agent_name="copywriter",
        )
        assert result["error_class"] == "semantic"
