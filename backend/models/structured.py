"""Provider-native structured output, with a way out when the provider says no.

P1d. Every runtime here is an OpenAI-compatible endpoint (``ChatOpenAI`` with a
custom ``base_url``), which makes "does this provider enforce a real JSON
schema?" unanswerable offline — and the production route sends 13 of 15 task
types to one such endpoint. So capability is *declared* per provider, the
declaration is overridable, and an attempt that cannot be made falls back a
level rather than failing the node::

    NATIVE_SCHEMA -> JSON_OBJECT -> PROMPTED

Whatever the level, the payload passes the same Pydantic model and the same
semantic validator. The level decides how the text is *obtained*; it never
decides whether the text is *checked*.

The table below is a claim, not a measurement: it follows each provider's
public documentation and has not been verified against the real endpoints (that
needs credentials and a live call). Promoting an entry to ``NATIVE_SCHEMA``
should be backed by a real request, not by a reading of the docs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, TypeVar, get_args, get_origin

from pydantic import BaseModel, ValidationError

from backend.config.models import ModelProvider

__all__ = [
    "StructuredMode",
    "StructuredOutputError",
    "degradation_path",
    "describe_validation_error",
    "render_schema_instructions",
    "resolve_structured_mode",
    "validate_output",
]

T = TypeVar("T", bound=BaseModel)

_ENV_PREFIX = "XHS_STRUCTURED_MODE_"


class StructuredMode(StrEnum):
    """How a model is asked to produce a schema-shaped payload."""

    NATIVE_SCHEMA = "native_schema"
    """The provider enforces the schema itself (tool calling / json_schema)."""

    JSON_OBJECT = "json_object"
    """The provider enforces *syntax* only — valid JSON, no shape guarantee."""

    PROMPTED = "prompted"
    """Nothing but instructions: the text is parsed and checked after the fact."""


_PROVIDER_MODES: Mapping[ModelProvider, StructuredMode] = {
    ModelProvider.ANTHROPIC: StructuredMode.NATIVE_SCHEMA,
    ModelProvider.OPENAI: StructuredMode.NATIVE_SCHEMA,
    ModelProvider.DEEPSEEK: StructuredMode.JSON_OBJECT,
    ModelProvider.DASHSCOPE: StructuredMode.JSON_OBJECT,
    # No verified structured-output contract behind either of these two; assume
    # the least and let the degradation chain carry the call.
    ModelProvider.XIAOMIMIMO: StructuredMode.PROMPTED,
    ModelProvider.XUNFEI: StructuredMode.PROMPTED,
}
"""Documented capability per provider — a claim, not a probe result.

The production default route sends 13 of 15 task types to the XUNFEI entry,
which is exactly why the chain exists instead of a hard dependency on native.
"""

_ORDER: tuple[StructuredMode, ...] = (
    StructuredMode.NATIVE_SCHEMA,
    StructuredMode.JSON_OBJECT,
    StructuredMode.PROMPTED,
)


def degradation_path(mode: StructuredMode) -> tuple[StructuredMode, ...]:
    """``mode`` followed by every weaker level, strongest first."""
    return _ORDER[_ORDER.index(mode) :]


def _coerce_mode(value: object) -> StructuredMode | None:
    """A mode from loose input, or ``None`` when it is not one of the three."""
    try:
        return StructuredMode(str(value).strip().lower())
    except ValueError:
        return None


def resolve_structured_mode(
    provider: ModelProvider, *, override: StructuredMode | str | None = None
) -> StructuredMode:
    """The mode for ``provider``; ``override`` then env then the table.

    An explicit argument wins over everything; ``XHS_STRUCTURED_MODE_<PROVIDER>``
    wins over the table. Endpoint capability is an external fact that changes
    without a release of this code, so correcting it must not require a patch.
    A malformed override is ignored rather than fatal — a typo in an env var
    must not take the call down.
    """
    if override is not None:
        resolved = _coerce_mode(override)
        if resolved is not None:
            return resolved
    from_env = _coerce_mode(os.environ.get(f"{_ENV_PREFIX}{provider.name}", ""))
    if from_env is not None:
        return from_env
    return _PROVIDER_MODES[provider]


class StructuredOutputError(RuntimeError):
    """Every level of the chain was tried and none produced a valid payload.

    Carries what a caller needs to decide what to do next — and deliberately no
    partial result. A payload that "mostly" validated is how bad data reaches
    state, so the failure stays a failure until someone chooses a fallback.
    """

    def __init__(
        self,
        output_model: type[BaseModel],
        attempts: Sequence[tuple[StructuredMode, str]],
    ) -> None:
        self.output_model = output_model
        self.attempts: tuple[tuple[StructuredMode, str], ...] = tuple(attempts)
        detail = "; ".join(f"{mode.value}: {reason}" for mode, reason in self.attempts)
        super().__init__(
            f"no valid {output_model.__name__} after {len(self.attempts)} attempt(s) — {detail}"
        )


_SIMPLE_TYPES: Mapping[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _type_label(annotation: Any) -> str:
    """A short label for an annotation, written the way a model reads it."""
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        inner = _type_label(args[0]) if args else "any"
        return f"list[{inner}]"
    if origin is dict:
        return "object"
    if isinstance(annotation, type):
        return _SIMPLE_TYPES.get(annotation, annotation.__name__)
    return "string"


def render_schema_instructions(output_model: type[BaseModel]) -> str:
    """The shape, stated for a model rather than for a parser.

    This belongs in a *runtime* message, never in the compiled system prompt.
    The layered prompt is measured against a committed snapshot (P1b) and is
    meant to be identical across calls; a schema hint that appears on some calls
    and not others would make that measurement describe nothing.
    """
    lines = ["请只输出一个 JSON 对象（不要 markdown 代码围栏、不要任何解释文字），字段如下："]
    for name, field in output_model.model_fields.items():
        label = _type_label(field.annotation)
        requirement = "必填" if field.is_required() else "可选"
        described = f"，{field.description}" if field.description else ""
        lines.append(f"- {name}: {label}（{requirement}{described}）")
    return "\n".join(lines)


def describe_validation_error(error: ValidationError) -> str:
    """A field-level correction notice, addressed to the model that wrote it.

    Pydantic's own message is written for a developer reading a traceback. The
    same information does the work here — the retry succeeds by telling the
    model precisely which field to change, so it has to be stated that way.
    """
    lines = ["上一次输出未通过校验，请修正以下问题后重新输出完整 JSON："]
    for item in error.errors():
        location = ".".join(str(part) for part in item.get("loc", ())) or "(根对象)"
        lines.append(f"- {location}: {item.get('msg', 'invalid')}")
    return "\n".join(lines)


def validate_output(
    payload: Any,
    output_model: type[T],
) -> tuple[T | None, str | None]:
    """``(instance, None)`` when well formed, ``(None, correction)`` when not.

    Accepts either a mapping to validate or an instance the provider already
    built from ``output_model`` — a native structured-output call hands back the
    model itself, and re-validating it would be busywork. Anything else is
    refused: broadening this to "any object" would make the gate decorative.

    Schema only. The semantic check is *deliberately* not folded in here: the
    two failures need different dispositions (a malformed payload is never
    usable, a well-formed one that a validator refuses may still be), and a
    single function that reported both the same way would hide that difference
    from the caller — which is how an advisory check silently becomes a fatal
    one. Callers run their own validator against the returned instance.
    """
    if isinstance(payload, output_model):
        return payload, None
    if not isinstance(payload, dict):
        return None, "输出必须是 JSON 对象（顶层形如 {...}），请重新输出。"
    try:
        return output_model.model_validate(payload), None
    except ValidationError as exc:
        return None, describe_validation_error(exc)
