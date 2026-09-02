"""Contract tests for OpenAPI specification validation.

These tests verify that the OpenAPI spec:
1. Exists at the expected location
2. Is valid YAML
3. Contains all required endpoints
4. Has unified ApiResponse wrapper
"""

from pathlib import Path

import pytest
import yaml

# Path to OpenAPI spec (relative to project root)
OPENAPI_SPEC_PATH = Path(__file__).resolve().parent.parent.parent / "api" / "spec" / "openapi.yaml"


@pytest.fixture(scope="session")
def _spec():
    """Parse the 1387-line openapi.yaml once per session, not per test.

    The five per-class fixtures below previously each ran ``yaml.safe_load``
    on every test (function-scoped), adding ~0.13s of repeated parse cost per
    test. Request this session-scoped fixture and slice from the cached dict.
    """
    with open(OPENAPI_SPEC_PATH) as f:
        return yaml.safe_load(f)


class TestOpenAPISpecExists:
    """Tests for OpenAPI spec file existence."""

    def test_spec_file_exists(self):
        """Verify OpenAPI spec file exists at expected location."""
        assert OPENAPI_SPEC_PATH.exists(), f"OpenAPI spec not found at {OPENAPI_SPEC_PATH}"

    def test_spec_file_is_yaml(self):
        """Verify spec file has .yaml extension."""
        assert OPENAPI_SPEC_PATH.suffix in (".yaml", ".yml"), (
            f"Expected .yaml extension, got {OPENAPI_SPEC_PATH.suffix}"
        )


class TestOpenAPISpecValidYAML:
    """Tests for YAML validity."""

    @pytest.fixture
    def spec_content(self, _spec):
        """Load OpenAPI spec content (cached at session scope via _spec)."""
        return _spec

    def test_spec_loads_as_yaml(self, spec_content):
        """Verify spec loads without YAML parsing errors."""
        assert spec_content is not None, "Spec content is None (empty or invalid)"

    def test_spec_has_openapi_version(self, spec_content):
        """Verify spec declares openapi version."""
        assert "openapi" in spec_content, "Missing 'openapi' field"
        assert spec_content["openapi"].startswith("3."), (
            f"Expected OpenAPI 3.x, got {spec_content['openapi']}"
        )

    def test_spec_has_info_section(self, spec_content):
        """Verify spec has required info section."""
        assert "info" in spec_content, "Missing 'info' section"
        assert "title" in spec_content["info"], "Missing 'title' in info"
        assert "version" in spec_content["info"], "Missing 'version' in info"


class TestOpenAPIRequiredEndpoints:
    """Tests for required API endpoints."""

    @pytest.fixture
    def paths(self, _spec):
        """Get paths from OpenAPI spec (cached at session scope via _spec)."""
        return _spec.get("paths", {})

    def test_workflow_start_endpoint_exists(self, paths):
        """Verify /workflow/start endpoint exists."""
        assert "/workflow/start" in paths, "Missing /workflow/start endpoint"
        assert "post" in paths["/workflow/start"], "Missing POST method for /workflow/start"

    def test_workflow_status_endpoint_exists(self, paths):
        """Verify /workflow/status/{thread_id} endpoint exists."""
        assert "/workflow/status/{thread_id}" in paths, (
            "Missing /workflow/status/{thread_id} endpoint"
        )
        assert "get" in paths["/workflow/status/{thread_id}"], (
            "Missing GET method for /workflow/status/{thread_id}"
        )

    def test_workflow_pause_endpoint_exists(self, paths):
        """Verify /workflow/pause/{thread_id} endpoint exists."""
        assert "/workflow/pause/{thread_id}" in paths, (
            "Missing /workflow/pause/{thread_id} endpoint"
        )

    def test_workflow_resume_endpoint_exists(self, paths):
        """Verify /workflow/resume/{thread_id} endpoint exists."""
        assert "/workflow/resume/{thread_id}" in paths, (
            "Missing /workflow/resume/{thread_id} endpoint"
        )

    def test_review_pending_endpoint_exists(self, paths):
        """Verify /review/pending/{thread_id} endpoint exists."""
        assert "/review/pending/{thread_id}" in paths, (
            "Missing /review/pending/{thread_id} endpoint"
        )

    def test_review_submit_endpoint_exists(self, paths):
        """Verify /review/submit/{thread_id} endpoint exists."""
        assert "/review/submit/{thread_id}" in paths, "Missing /review/submit/{thread_id} endpoint"

    def test_analytics_report_endpoint_exists(self, paths):
        """Verify /analytics/report/{account_id} endpoint exists."""
        assert "/analytics/report/{account_id}" in paths, (
            "Missing /analytics/report/{account_id} endpoint"
        )

    def test_analytics_performance_endpoint_exists(self, paths):
        """Verify /analytics/performance/{account_id} endpoint exists."""
        assert "/analytics/performance/{account_id}" in paths, (
            "Missing /analytics/performance/{account_id} endpoint"
        )

    def test_analytics_costs_endpoint_exists(self, paths):
        """Verify /analytics/costs endpoint exists."""
        assert "/analytics/costs" in paths, "Missing /analytics/costs endpoint"

    def test_creator_agent_endpoints_exist(self, paths):
        """Creator Agent routes must be represented in the checked-in contract."""
        expected = {
            "/creator-agent/model": {"get", "put"},
            "/creator-agent/decisions": {"post"},
            "/creator-agent/decisions/{decision_id}": {"get"},
            "/creator-agent/decisions/{decision_id}/feedback": {"post"},
            "/creator-agent/relationships/{audience_id}": {"get"},
            "/creator-agent/learning-signals": {"get"},
            "/creator-agent/learning-signals/{signal_id}/review": {"post"},
        }
        for path, methods in expected.items():
            assert path in paths, f"Missing {path} endpoint"
            assert methods <= set(paths[path]), f"Missing methods for {path}"


class TestOpenAPIUnifiedResponse:
    """Tests for unified ApiResponse wrapper."""

    @pytest.fixture
    def schemas(self, _spec):
        """Get schemas from OpenAPI spec (cached at session scope via _spec)."""
        return _spec.get("components", {}).get("schemas", {})

    def test_api_response_schema_exists(self, schemas):
        """Verify ApiResponse schema exists."""
        assert "ApiResponse" in schemas, "Missing ApiResponse schema"

    def test_api_response_has_required_fields(self, schemas):
        """Verify ApiResponse has required fields."""
        api_response = schemas.get("ApiResponse", {})
        required_fields = api_response.get("required", [])
        assert "success" in required_fields, "ApiResponse missing required 'success' field"
        assert "timestamp" in required_fields, "ApiResponse missing required 'timestamp' field"
        assert "request_id" in required_fields, "ApiResponse missing required 'request_id' field"

    def test_api_response_has_data_field(self, schemas):
        """Verify ApiResponse has data field."""
        api_response = schemas.get("ApiResponse", {})
        properties = api_response.get("properties", {})
        assert "data" in properties, "ApiResponse missing 'data' property"

    def test_api_response_has_error_field(self, schemas):
        """Verify ApiResponse has error field."""
        api_response = schemas.get("ApiResponse", {})
        properties = api_response.get("properties", {})
        assert "error" in properties, "ApiResponse missing 'error' property"

    def test_error_detail_schema_exists(self, schemas):
        """Verify ErrorDetail schema exists."""
        assert "ErrorDetail" in schemas, "Missing ErrorDetail schema"

    def test_error_detail_has_code_and_message(self, schemas):
        """Verify ErrorDetail has code and message fields."""
        error_detail = schemas.get("ErrorDetail", {})
        required_fields = error_detail.get("required", [])
        assert "code" in required_fields, "ErrorDetail missing required 'code' field"
        assert "message" in required_fields, "ErrorDetail missing required 'message' field"


class TestOpenAPITypedResponseWrappers:
    """Tests for typed ApiResponse wrappers."""

    @pytest.fixture
    def schemas(self, _spec):
        """Get schemas from OpenAPI spec (cached at session scope via _spec)."""
        return _spec.get("components", {}).get("schemas", {})

    def test_workflow_response_wrapper_exists(self, schemas):
        """Verify ApiResponse_WorkflowResponse wrapper exists."""
        assert "ApiResponse_WorkflowResponse" in schemas, "Missing ApiResponse_WorkflowResponse"

    def test_workflow_state_wrapper_exists(self, schemas):
        """Verify ApiResponse_WorkflowState wrapper exists."""
        assert "ApiResponse_WorkflowState" in schemas, "Missing ApiResponse_WorkflowState"

    def test_pending_review_wrapper_exists(self, schemas):
        """Verify ApiResponse_PendingReview wrapper exists."""
        assert "ApiResponse_PendingReview" in schemas, "Missing ApiResponse_PendingReview"

    def test_review_submit_wrapper_exists(self, schemas):
        """Verify ApiResponse_ReviewSubmitResponse wrapper exists."""
        assert "ApiResponse_ReviewSubmitResponse" in schemas, (
            "Missing ApiResponse_ReviewSubmitResponse"
        )

    def test_growth_report_wrapper_exists(self, schemas):
        """Verify ApiResponse_GrowthReport wrapper exists."""
        assert "ApiResponse_GrowthReport" in schemas, "Missing ApiResponse_GrowthReport"

    def test_performance_list_wrapper_exists(self, schemas):
        """Verify ApiResponse_PerformanceList wrapper exists."""
        assert "ApiResponse_PerformanceList" in schemas, "Missing ApiResponse_PerformanceList"

    def test_cost_report_wrapper_exists(self, schemas):
        """Verify ApiResponse_CostReport wrapper exists."""
        assert "ApiResponse_CostReport" in schemas, "Missing ApiResponse_CostReport"


class TestOpenAPIEnums:
    """Tests for enum definitions in OpenAPI spec."""

    @pytest.fixture
    def schemas(self, _spec):
        """Get schemas from OpenAPI spec (cached at session scope via _spec)."""
        return _spec.get("components", {}).get("schemas", {})

    def test_workflow_phase_enum_exists(self, schemas):
        """Verify WorkflowPhase enum exists."""
        assert "WorkflowPhase" in schemas, "Missing WorkflowPhase enum"

    def test_workflow_phase_enum_values(self, schemas):
        """Verify WorkflowPhase has all required values."""
        workflow_phase = schemas.get("WorkflowPhase", {})
        enum_values = workflow_phase.get("enum", [])
        expected_values = [
            "idle",
            "scouting",
            "planning",
            "creating",
            "reviewing",
            "publishing",
            "analyzing",
            "engaging",
            "completed",
            "error",
        ]
        for value in expected_values:
            assert value in enum_values, f"WorkflowPhase missing '{value}'"

    def test_content_status_enum_exists(self, schemas):
        """Verify ContentStatus enum exists."""
        assert "ContentStatus" in schemas, "Missing ContentStatus enum"

    def test_content_status_enum_values(self, schemas):
        """Verify ContentStatus has all required values."""
        content_status = schemas.get("ContentStatus", {})
        enum_values = content_status.get("enum", [])
        expected_values = [
            "approved",
            "needs_revision",
            "rejected",
            "draft",
            "pending_review",
            "published",
            "failed",
        ]
        for value in expected_values:
            assert value in enum_values, f"ContentStatus missing '{value}'"

    def test_content_type_enum_exists(self, schemas):
        """Verify ContentType enum exists."""
        assert "ContentType" in schemas, "Missing ContentType enum"

    def test_urgency_enum_exists(self, schemas):
        """Verify Urgency enum exists."""
        assert "Urgency" in schemas, "Missing Urgency enum"

    def test_workflow_status_enum_exists(self, schemas):
        """Verify WorkflowStatus enum exists."""
        assert "WorkflowStatus" in schemas, "Missing WorkflowStatus enum"

    def test_workflow_state_has_account_id(self, schemas):
        """Multi-account UI needs account_id on workflow status/state payloads."""
        workflow_state = schemas.get("WorkflowState") or {}
        props = workflow_state.get("properties") or {}
        assert "account_id" in props, "WorkflowState must expose account_id for multi-account UI"

    def test_review_decision_enum_exists(self, schemas):
        """Verify ReviewDecision enum exists."""
        assert "ReviewDecision" in schemas, "Missing ReviewDecision enum"
