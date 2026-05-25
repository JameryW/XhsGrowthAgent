#!/bin/bash
set -e

echo "=== Generating types from OpenAPI spec ==="

mkdir -p xhs_growth/api/generated

datamodel-codegen \
  --input api/spec/openapi.yaml \
  --output xhs_growth/api/generated/models.py \
  --output-model-type pydantic_v2.BaseModel \
  --field-constraints \
  --use-annotated \
  --strict-types str bytes int float bool \
  --snake-case-field \
  --capitalize-enum-members \
  --use-double-quotes

cat > xhs_growth/api/generated/__init__.py << 'EOF'
"""Auto-generated Pydantic models from OpenAPI spec."""
from xhs_growth.api.generated.models import *

__all__ = [
    "ApiResponse",
    "ErrorDetail",
    "WorkflowPhase",
    "ContentStatus",
    "WorkflowStartRequest",
    "WorkflowResponse",
    "WorkflowState",
    "PendingReview",
    "ReviewDecisionRequest",
    "ReviewSubmitResponse",
]
EOF

echo "=== Generation complete ==="