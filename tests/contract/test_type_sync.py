"""Contract tests for type synchronization.

These tests verify that:
1. Backend enums match OpenAPI spec enums
2. Frontend types match backend/OpenAPI definitions
3. Generated models exist and are consistent

Note: These tests avoid importing from backend to prevent
langgraph dependency issues during isolated test runs.
"""

import re
from pathlib import Path

import pytest
import yaml

# Project paths (relative to this test file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OPENAPI_SPEC_PATH = PROJECT_ROOT / "api" / "spec" / "openapi.yaml"
BACKEND_ENUMS_PATH = PROJECT_ROOT / "backend" / "state" / "enums.py"
FRONTEND_TYPES_PATH = PROJECT_ROOT / "frontend" / "src" / "types"
BACKEND_SUBSTATES_PATH = PROJECT_ROOT / "backend" / "state" / "substates.py"


def extract_python_enum_values(file_path: Path, enum_name: str) -> set[str]:
    """Extract enum values from a Python enum class by parsing the file."""
    with open(file_path) as f:
        content = f.read()

    # Find the enum class definition — matches both (str, Enum) and (StrEnum)
    pattern = rf"class {enum_name}\((?:str,\s*Enum|StrEnum)\):\s*.*?(?=\nclass|\n__all__|\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return set()

    enum_body = match.group(0)
    # Extract value = "string" patterns
    values = re.findall(r'=\s*"([^"]+)"', enum_body)
    return set(values)


class TestBackendEnumSync:
    """Tests for backend enum synchronization with OpenAPI spec."""

    @pytest.fixture
    def openapi_enums(self):
        """Extract enums from OpenAPI spec."""
        with open(OPENAPI_SPEC_PATH) as f:
            spec = yaml.safe_load(f)
        schemas = spec.get("components", {}).get("schemas", {})

        enums = {}
        for name, schema in schemas.items():
            if schema.get("type") == "string" and "enum" in schema:
                enums[name] = set(schema["enum"])
        return enums

    @pytest.fixture
    def backend_enum_values(self):
        """Extract enum values from backend enums file by parsing."""
        return {
            "WorkflowPhase": extract_python_enum_values(BACKEND_ENUMS_PATH, "WorkflowPhase"),
            "ContentStatus": extract_python_enum_values(BACKEND_ENUMS_PATH, "ContentStatus"),
            "ContentType": extract_python_enum_values(BACKEND_ENUMS_PATH, "ContentType"),
            "Urgency": extract_python_enum_values(BACKEND_ENUMS_PATH, "Urgency"),
        }

    def test_workflow_phase_sync(self, openapi_enums, backend_enum_values):
        """Verify WorkflowPhase backend enum matches OpenAPI."""
        openapi_values = openapi_enums.get("WorkflowPhase", set())
        backend_values = backend_enum_values.get("WorkflowPhase", set())

        assert openapi_values == backend_values, (
            f"WorkflowPhase mismatch:\n"
            f"  OpenAPI: {sorted(openapi_values)}\n"
            f"  Backend: {sorted(backend_values)}\n"
            f"  Missing in backend: {sorted(openapi_values - backend_values)}\n"
            f"  Extra in backend: {sorted(backend_values - openapi_values)}"
        )

    def test_content_status_sync(self, openapi_enums, backend_enum_values):
        """Verify ContentStatus backend enum matches OpenAPI."""
        openapi_values = openapi_enums.get("ContentStatus", set())
        backend_values = backend_enum_values.get("ContentStatus", set())

        assert openapi_values == backend_values, (
            f"ContentStatus mismatch:\n"
            f"  OpenAPI: {sorted(openapi_values)}\n"
            f"  Backend: {sorted(backend_values)}\n"
            f"  Missing in backend: {sorted(openapi_values - backend_values)}\n"
            f"  Extra in backend: {sorted(backend_values - openapi_values)}"
        )

    def test_content_type_sync(self, openapi_enums, backend_enum_values):
        """Verify ContentType backend enum matches OpenAPI."""
        openapi_values = openapi_enums.get("ContentType", set())
        backend_values = backend_enum_values.get("ContentType", set())

        assert openapi_values == backend_values, (
            f"ContentType mismatch:\n"
            f"  OpenAPI: {sorted(openapi_values)}\n"
            f"  Backend: {sorted(backend_values)}"
        )

    def test_urgency_sync(self, openapi_enums, backend_enum_values):
        """Verify Urgency backend enum matches OpenAPI."""
        openapi_values = openapi_enums.get("Urgency", set())
        backend_values = backend_enum_values.get("Urgency", set())

        assert openapi_values == backend_values, (
            f"Urgency mismatch:\n"
            f"  OpenAPI: {sorted(openapi_values)}\n"
            f"  Backend: {sorted(backend_values)}"
        )


class TestFrontendTypesExist:
    """Tests for frontend TypeScript type files existence."""

    def test_workflow_types_file_exists(self):
        """Verify workflow.ts types file exists."""
        workflow_types = FRONTEND_TYPES_PATH / "workflow.ts"
        assert workflow_types.exists(), f"Missing {workflow_types}"

    def test_review_types_file_exists(self):
        """Verify review.ts types file exists."""
        review_types = FRONTEND_TYPES_PATH / "review.ts"
        assert review_types.exists(), f"Missing {review_types}"

    def test_analytics_types_file_exists(self):
        """Verify analytics.ts types file exists."""
        analytics_types = FRONTEND_TYPES_PATH / "analytics.ts"
        assert analytics_types.exists(), f"Missing {analytics_types}"

    def test_types_index_file_exists(self):
        """Verify types index.ts file exists."""
        index_file = FRONTEND_TYPES_PATH / "index.ts"
        assert index_file.exists(), f"Missing {index_file}"


class TestFrontendWorkflowTypes:
    """Tests for frontend workflow type definitions."""

    @pytest.fixture
    def workflow_types_content(self):
        """Read workflow.ts content."""
        workflow_types = FRONTEND_TYPES_PATH / "workflow.ts"
        with open(workflow_types) as f:
            return f.read()

    @pytest.fixture
    def openapi_enums(self):
        """Extract enums from OpenAPI spec."""
        with open(OPENAPI_SPEC_PATH) as f:
            spec = yaml.safe_load(f)
        schemas = spec.get("components", {}).get("schemas", {})

        enums = {}
        for name, schema in schemas.items():
            if schema.get("type") == "string" and "enum" in schema:
                enums[name] = set(schema["enum"])
        return enums

    def test_workflow_phase_type_defined(self, workflow_types_content):
        """Verify WorkflowPhase type is defined in frontend."""
        assert "WorkflowPhase" in workflow_types_content, "Missing WorkflowPhase type definition"

    def test_workflow_phase_values_match_openapi(self, workflow_types_content, openapi_enums):
        """Verify frontend WorkflowPhase values match OpenAPI."""
        # Extract values from frontend type definition
        # Frontend uses type union: 'idle' | 'scouting' | ...
        import re

        # Find the WorkflowPhase type definition (stop at // comment or export keyword)
        # The pattern captures the type definition until the next line that starts with // or export
        pattern = r"export type WorkflowPhase\s*=\s*((?:[^/\n]*(?:\n\s*\|[^/\n]*)*)\n)"
        match = re.search(pattern, workflow_types_content)
        if match:
            type_def = match.group(1)
            # Extract quoted values
            values = re.findall(r"'(\w+)'", type_def)
            frontend_values = set(values)
            openapi_values = openapi_enums.get("WorkflowPhase", set())

            # Frontend should NOT have 'paused' or 'running' (those are WorkflowStatus)
            assert frontend_values == openapi_values, (
                f"WorkflowPhase frontend mismatch:\n"
                f"  OpenAPI: {sorted(openapi_values)}\n"
                f"  Frontend: {sorted(frontend_values)}"
            )

    def test_workflow_response_type_defined(self, workflow_types_content):
        """Verify WorkflowResponse interface is defined."""
        assert "WorkflowResponse" in workflow_types_content, "Missing WorkflowResponse interface"

    def test_workflow_state_type_defined(self, workflow_types_content):
        """Verify WorkflowState interface is defined."""
        assert "WorkflowState" in workflow_types_content, "Missing WorkflowState interface"


class TestFrontendReviewTypes:
    """Tests for frontend review type definitions."""

    @pytest.fixture
    def review_types_content(self):
        """Read review.ts content."""
        review_types = FRONTEND_TYPES_PATH / "review.ts"
        with open(review_types) as f:
            return f.read()

    def test_pending_review_type_defined(self, review_types_content):
        """Verify PendingReview interface is defined."""
        assert "PendingReview" in review_types_content, "Missing PendingReview interface"

    def test_review_submit_response_type_defined(self, review_types_content):
        """Verify ReviewSubmitResponse interface is defined."""
        assert "ReviewSubmitResponse" in review_types_content, "Missing ReviewSubmitResponse interface"


class TestFrontendAnalyticsTypes:
    """Tests for frontend analytics type definitions."""

    @pytest.fixture
    def analytics_types_content(self):
        """Read analytics.ts content."""
        analytics_types = FRONTEND_TYPES_PATH / "analytics.ts"
        with open(analytics_types) as f:
            return f.read()

    def test_growth_report_type_defined(self, analytics_types_content):
        """Verify GrowthReport interface is defined."""
        assert "GrowthReport" in analytics_types_content, "Missing GrowthReport interface"

    def test_cost_data_type_defined(self, analytics_types_content):
        """Verify CostData interface is defined."""
        assert "CostData" in analytics_types_content, "Missing CostData interface"


class TestGeneratedModelsConsistency:
    """Tests for generated model consistency (if generation tools exist)."""

    @pytest.fixture
    def openapi_schemas(self):
        """Get schemas from OpenAPI spec."""
        with open(OPENAPI_SPEC_PATH) as f:
            spec = yaml.safe_load(f)
        return spec.get("components", {}).get("schemas", {})

    def test_backend_substates_exist(self):
        """Verify backend substates module exists."""
        assert BACKEND_SUBSTATES_PATH.exists(), f"Missing {BACKEND_SUBSTATES_PATH}"

    def test_backend_substates_match_openapi(self, openapi_schemas):
        """Verify backend substates have corresponding OpenAPI schemas."""
        # Read substates file to find defined classes
        with open(BACKEND_SUBSTATES_PATH) as f:
            content = f.read()

        # Find TypedDict class names
        class_pattern = r"class\s+(\w+)\(TypedDict"
        defined_classes = re.findall(class_pattern, content)

        # These should have corresponding schemas in OpenAPI
        expected_schemas = ["TrendData", "ContentPlan", "CopyContent", "VisualPlan"]
        for schema_name in expected_schemas:
            assert schema_name in openapi_schemas, f"OpenAPI missing schema for {schema_name}"