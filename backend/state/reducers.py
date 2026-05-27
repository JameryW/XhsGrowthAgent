"""State reducers for LangGraph state management."""

from typing import Any


def merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge — right overrides left."""
    return {**left, **right}


def append_list(left: list[Any], right: list[Any]) -> list[Any]:
    """Append right to left."""
    return left + right


def replace(left: Any, right: Any) -> Any:
    """Simple replacement — right replaces left."""
    return right


def max_value(left: int | float, right: int | float) -> int | float:
    """Keep the larger value."""
    return max(left, right)
