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
    """A short label for an annotation, written the way a model reads it.

    A nested model reads as ``object``: the class name means nothing to a model,
    and the fields behind it are spelled out by :func:`_describe_fields` instead.
    An ``Optional[X]`` is unwrapped rather than labelled from the wrapper —
    ``X | None`` is not a type of its own, and the fall-through used to call it
    ``string``, which is worse than useless here: a nested model is only spelled
    out *once*, so the second field referring to it has nothing but its label.
    """
    if annotation is Any:
        return "any"
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        return f"list[{_type_label(args[0]) if args else 'any'}]"
    if origin is dict:
        return "object"
    if origin is not None:
        # Optional[X] / X | None / a genuine union — none of these is a type.
        labels = list(
            dict.fromkeys(_type_label(arg) for arg in get_args(annotation) if arg is not type(None))
        )
        if not labels:
            return "any"
        return labels[0] if len(labels) == 1 else " | ".join(labels)
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return "object"
        return _SIMPLE_TYPES.get(annotation, annotation.__name__)
    return "string"


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    """Every model reachable from an annotation, without repeating one."""
    found: list[type[BaseModel]] = []
    pending = [annotation]
    while pending:
        current = pending.pop()
        origin = get_origin(current)
        if origin is not None:
            pending.extend(get_args(current))
            continue
        if isinstance(current, type) and issubclass(current, BaseModel) and current not in found:
            found.append(current)
    return found


def _describe_fields(
    lines: list[str], model: type[BaseModel], *, indent: str, expanded: set[type[BaseModel]]
) -> None:
    """One field per line, recursing into nested models exactly once.

    Without the recursion a nested field would be described as ``list[object]``
    and the model would have to guess the keys from the field name alone — which
    is how a payload that was *supposed* to be shaped arrives as a list of
    strings and costs a retry. Expanding once (not per reference) keeps the hint
    from growing with the number of fields that share a nested type.
    """
    for name, field in model.model_fields.items():
        label = _type_label(field.annotation)
        requirement = "必填" if field.is_required() else "可选"
        described = f"，{field.description}" if field.description else ""
        lines.append(f"{indent}- {name}: {label}（{requirement}{described}）")
        for nested in _nested_models(field.annotation):
            if nested in expanded:
                continue
            expanded.add(nested)
            lines.append(f"{indent}  {name} 的元素字段：")
            _describe_fields(lines, nested, indent=indent + "  ", expanded=expanded)


def render_schema_instructions(output_model: type[BaseModel]) -> str:
    """The shape, stated for a model rather than for a parser.

    This belongs in a *runtime* message, never in the compiled system prompt.
    The layered prompt is measured against a committed snapshot (P1b) and is
    meant to be identical across calls; a schema hint that appears on some calls
    and not others would make that measurement describe nothing.
    """
    lines = ["请只输出一个 JSON 对象（不要 markdown 代码围栏、不要任何解释文字），字段如下："]
    _describe_fields(lines, output_model, indent="", expanded=set())
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


_OBJECT_ROOT_CORRECTION = "输出必须是 JSON 对象（顶层形如 {...}），请重新输出。"
_LIST_ROOT_CORRECTION = "输出必须是 JSON 对象或数组（顶层形如 {...} 或 [...]），请重新输出。"


def _takes_a_list_root(output_model: type[BaseModel]) -> bool:
    """Whether ``output_model`` declares that a bare JSON array is a legal root.

    Only the model can answer this. For most models an array is not a shape at
    all but a mistake, while for a few it is the *natural* answer — a question
    list is ``[{"field": …}]`` long before it is ``{"questions": [...]}``, and
    ``_parse_json_response`` really does hand back a list for both spellings
    (measured, not assumed). Pydantic cannot express the difference: the
    object-only gate below runs before ``model_validate`` ever sees the payload,
    so a root shape that is not an object has nowhere else to be declared.
    """
    return bool(getattr(output_model, "accepts_bare_list", False))


def validate_output(
    payload: Any,
    output_model: type[T],
) -> tuple[T | None, str | None]:
    """``(instance, None)`` when well formed, ``(None, correction)`` when not.

    Accepts either a mapping to validate or an instance the provider already
    built from ``output_model`` — a native structured-output call hands back the
    model itself, and re-validating it would be busywork. A bare list is
    accepted only when the model declares ``accepts_bare_list``; anything else
    is refused: broadening this to "any object" would make the gate decorative,
    and broadening it to "any list" would hand eleven object-rooted models a
    Pydantic root error in place of the instruction to emit an object.

    The refusal carries the shapes this *particular* model accepts, not a fixed
    sentence: the correction is the entire mechanism of the retry, and telling a
    model that takes a question list that its answer "must be an object" spends
    a round trip narrowing it to the spelling we did not need.

    Schema only. The semantic check is *deliberately* not folded in here: the
    two failures need different dispositions (a malformed payload is never
    usable, a well-formed one that a validator refuses may still be), and a
    single function that reported both the same way would hide that difference
    from the caller — which is how an advisory check silently becomes a fatal
    one. Callers run their own validator against the returned instance.
    """
    accepts_list_root = _takes_a_list_root(output_model)
    if isinstance(payload, output_model):
        return payload, None
    if not isinstance(payload, dict) and not (isinstance(payload, list) and accepts_list_root):
        return None, _LIST_ROOT_CORRECTION if accepts_list_root else _OBJECT_ROOT_CORRECTION
    try:
        return output_model.model_validate(payload), None
    except ValidationError as exc:
        return None, describe_validation_error(exc)
