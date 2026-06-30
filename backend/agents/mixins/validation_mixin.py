"""Validation mixin for state updates."""

from typing import Any


class ValidationMixin:
    """状态验证能力"""

    def validate_state_update(self, updates: dict[str, Any], schema: type[Any]) -> None:
        """验证状态更新字段是否合法"""
        # TypedDict.__annotations__ contains valid field names
        valid_fields = getattr(schema, "__annotations__", {})
        for key in updates:
            if key not in valid_fields:
                raise ValueError(f"Invalid field: {key}")
