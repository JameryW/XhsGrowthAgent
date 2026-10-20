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

Parameter types are rendered in the shared vocabulary below (票 5o). The two
reflection conventions — JSON-schema names from a LangChain tool, annotation
names from a plain function — describe the same underlying types, so translating
them into one vocabulary is not inventing structure; leaving them raw would put
``dict[str, Any]`` next to ``object`` in the same prompt. The raw reflection
stays on ``ToolSpec.input_schema`` for anything that needs it exactly; only the
prompt-facing text is canonicalised, and an unrecognised name becomes ``any``
rather than leaking an annotation into the stable prefix.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.tools.runtime.models import PassStyle, ToolSpec

__all__ = ["render_tool_schema"]

_HEADER = (
    "[可用能力] 以下能力由运行时（Tool Gateway）执行。参数：`name: type` 必填，`name?: type` 可选。"
)
_MAPPING_NOTE = "整体即 `{name}: {type}` —— 该工具只接收一个 mapping，不再嵌套"

_TYPE_VOCABULARY: dict[str, str] = {
    "str": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "float": "number",
    "number": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "dict": "object",
    "mapping": "object",
    "object": "object",
    "list": "array",
    "tuple": "array",
    "sequence": "array",
    "set": "array",
    "frozenset": "array",
    "array": "array",
    "none": "null",
    "nonetype": "null",
    "any": "any",
}
"""The one vocabulary L1 renders in.

Both reflection conventions land here: a LangChain tool reports JSON-schema
names already (``string`` / ``integer``), a plain function reports annotation
names (``str`` / ``dict[str, Any]``). A name outside this table renders as
``any`` — the vocabulary is closed on purpose, so a new annotation cannot leak
its text into the stable prefix unnoticed.
"""


def _canonical_type(raw: str) -> str:
    """Map one reflected type spelling onto the shared vocabulary.

    Purely textual: strips ``typing.`` / ``collections.abc.`` prefixes and
    forward-ref quotes, reduces generics to their container
    (``dict[str, Any]`` → ``object``, ``list[str]`` → ``array``), and unwraps
    ``Optional[...]`` / ``X | None`` to the wrapped type. Nullability is not
    rendered: L1 describes the *call shape* (and required-ness already says
    whether a parameter may be omitted), not every value the tool accepts.
    Unknown names → ``any``.
    """
    text = raw.strip().strip("'\"")
    if not text:
        return "any"
    text = text.replace("typing.", "").replace("collections.abc.", "").replace("types.", "")
    for prefix in ("Optional[", "Union["):
        if text.startswith(prefix) and text.endswith("]"):
            parts = [
                part.strip()
                for part in text[len(prefix) : -1].split(",")
                if part.strip().lower() not in {"none", "nonetype"}
            ]
            text = parts[0] if parts else "any"
            break
    if "|" in text:
        parts = [
            part.strip()
            for part in text.split("|")
            if part.strip().lower() not in {"none", "nonetype"}
        ]
        text = parts[0] if parts else "any"
    if "[" in text:
        text = text.split("[", 1)[0].strip()
    base = text.rsplit(".", 1)[-1].lower()
    return _TYPE_VOCABULARY.get(base, "any")


def _type_name(described: object) -> str:
    """The declared type, rendered in the L1 vocabulary.

    ``describe_params`` reflects two conventions for the same idea; both go
    through :func:`_canonical_type` so the rendered text never mixes
    ``dict[str, Any]`` with ``object``. Anything unreadable renders as ``any``
    rather than echoing a name whose meaning L1 cannot promise.
    """
    if isinstance(described, dict):
        value = described.get("type", "any")
        return _canonical_type(str(value)) if value else "any"
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
