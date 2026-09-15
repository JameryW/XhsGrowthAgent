"""L1 tool-schema rendering — the producer P1b left the layer without (P1c-S4).

``PromptLayer.L1_TOOL_SCHEMA`` sits in the stable prefix (architecture review
§十八) because a tool schema changes far less often than account profile, task
or recall. It stayed empty through P1b for a simple reason: there was nothing to
put in it. The Registry (S1) is that something — every capability the agents can
reach is declared there, with a summary and a parameter shape, so the layer can
finally be *rendered* rather than reserved.

What this module deliberately does **not** render: the runtime facts
(``side_effect`` / ``auth_scope`` / ``latency`` / ``retry``). Tools are for
calling; the Gateway is for deciding what a call is allowed to do. Putting
"this one changes external state" in the prompt would invite a model to reason
about permissions it does not hold — and the model has no tool-calling channel
until P2c anyway. The one runtime fact that *is* part of the call shape is
``pass_style``: a MAPPING tool cannot be called the way the other nine are, and
:func:`describe_params` reflects its single ``data`` parameter as though it
could, which is exactly the misreading the parameter rendering has to head off.

Output is deterministic — sorted by capability — because a stable prefix that
reshuffles between runs is not a stable prefix.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.tools.runtime.models import PassStyle, ToolSpec

__all__ = ["render_tool_schema"]

_HEADER = (
    "[可用能力] 以下能力由运行时（Tool Gateway）执行。参数：`name: type` 必填，`name?: type` 可选。"
)
_MAPPING_NOTE = "整体即 `{name}: {type}` —— 该工具只接收一个 mapping，不再嵌套"


def _type_name(described: object) -> str:
    """The declared type as text.

    Whatever ``describe_params`` found: a reflected JSON-schema type
    (``"string"``/``"integer"``) for a LangChain tool, an annotation name
    (``"str"``/``"dict"``) for a plain function. Rendered as-is rather than
    normalised — normalising here would invent a schema the tools do not have.
    """
    if isinstance(described, dict):
        value = described.get("type", "any")
        return str(value) if value else "any"
    return "any"


def _is_required(described: object) -> bool:
    if isinstance(described, dict):
        return bool(described.get("required", False))
    return True


def _render_params(spec: ToolSpec) -> str:
    """One capability's parameter line, honouring its ``pass_style``.

    ``MAPPING`` is the reason this branches at all: its reflected signature
    shows one ``data`` parameter, but callers hand the payload over *as* that
    mapping rather than nesting it under ``data``. Rendered as a normal
    parameter it reads exactly like the other nine and would be called wrong.
    """
    described = spec.input_schema
    if not described:
        return "  参数: 无"
    if spec.pass_style is PassStyle.MAPPING:
        name, shape = next(iter(described.items()))
        return "  参数: " + _MAPPING_NOTE.format(name=name, type=_type_name(shape))
    parts = [
        f"{name}: {_type_name(shape)}" if _is_required(shape) else f"{name}?: {_type_name(shape)}"
        for name, shape in described.items()
    ]
    return "  参数: " + ", ".join(parts)


def render_tool_schema(specs: Sequence[ToolSpec]) -> str:
    """L1 text for these capabilities; ``""`` when there are none.

    Empty asks render as the empty string, not as a header with nothing under
    it: the compiler uses emptiness to decide whether the layer exists at all,
    so a stray header would put an empty L1 in every prompt.
    """
    unique = sorted({spec.capability: spec for spec in specs}.values(), key=lambda s: s.capability)
    if not unique:
        return ""
    lines = [_HEADER]
    for spec in unique:
        lines.append(f"- {spec.capability} — {spec.summary}")
        lines.append(_render_params(spec))
    return "\n".join(lines)
