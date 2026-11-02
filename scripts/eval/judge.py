"""E4 quality judge (LLM-as-judge) with a hard call budget.

Decisions this implements (2026-11-02): the user allowed an LLM judge, capped the
run at **fewer than 200 model calls**, and designated the **test account** as the
L3 subject.  ``JudgeBudget`` is therefore not optional bookkeeping: it is the
enforcement point for the budget decision, and it charges a call *before* the
model is invoked so a crash cannot make the accounting optimistic.

The judge is deliberately a separate module from the evaluator panel
(``backend/agents/evaluator.py``): that panel is a production gate with its own
fail-closed semantics, while this one scores an evaluation fixture for an
offline/experimental A/B run.  Sharing the dimension vocabulary (copywriting,
visual, compliance, reach, audience) keeps the numbers comparable, but nothing
here can influence a publish decision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

JUDGE_PROMPT_VERSION = "1"
JUDGE_DIMENSIONS: tuple[str, ...] = (
    "copywriting",
    "visual",
    "compliance",
    "reach",
    "audience",
)
DEFAULT_MAX_CALLS = 199  # "<200" from the 2026-11-02 decision, expressed literally
# No budget may exceed what the user approved.  A caller that wants a different
# cap must change this constant through review, not pass a bigger number.
APPROVED_MAX_CALLS = DEFAULT_MAX_CALLS

_SYSTEM = (
    "你是小红书内容质量的独立评审。只输出 JSON，不要 Markdown，不要解释。"
    "字段：copywriting、visual、compliance、reach、audience 各 0-10 的整数，"
    "rationale 为不超过 120 字的中文理由，bias_warning 为字符串（无则空串）。"
    "评分必须独立于作者/账号身份；不要复述原文。"
)


class JudgeOutputError(ValueError):
    """The model did not answer in the required JSON shape."""


class JudgeBudgetExceededError(RuntimeError):
    """The run would exceed the user-approved model-call budget."""


class JudgeScores(BaseModel):
    """One judge verdict; scores are 0-10 integers, never floats from the model."""

    copywriting: int = Field(ge=0, le=10)
    visual: int = Field(ge=0, le=10)
    compliance: int = Field(ge=0, le=10)
    reach: int = Field(ge=0, le=10)
    audience: int = Field(ge=0, le=10)
    rationale: str = ""
    bias_warning: str = ""

    @property
    def overall(self) -> float:
        values = [getattr(self, name) for name in JUDGE_DIMENSIONS]
        return round(sum(values) / len(values), 2)


@dataclass
class JudgeBudget:
    """The approved call cap; ``max_calls`` may never exceed the 199 decision.

    There is deliberately no opt-out: the guard the plan calls the enforcement
    point would otherwise be optional, and a caller passing ``max_calls=10**9``
    would silently spend past the approval.  One ``judge_content`` call consumes
    one unit; provider-level retries/fallbacks inside a single ``ainvoke`` are not
    observable here and are documented as outside this count.
    """

    max_calls: int = DEFAULT_MAX_CALLS
    used: int = 0

    def __post_init__(self) -> None:
        if self.max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        if self.max_calls > APPROVED_MAX_CALLS:
            raise ValueError(
                f"max_calls {self.max_calls} exceeds the approved cap of {APPROVED_MAX_CALLS} "
                "(the user approved fewer than 200 model calls)"
            )
        if not 0 <= self.used <= self.max_calls:
            raise ValueError(
                f"used {self.used} must be between 0 and max_calls {self.max_calls}; "
                "a negative counter would allow more calls than approved"
            )

    def __setattr__(self, name: str, value: object) -> None:
        # ``max_calls`` is a dataclass field, so the class object already carries
        # the default; checking the *instance* dict distinguishes "init" from a
        # later mutation (a plain getattr would see the class default and refuse
        # every construction).
        if name == "max_calls" and "max_calls" in self.__dict__:
            raise AttributeError(
                "max_calls is fixed at construction; create a new budget instead of mutating it"
            )
        super().__setattr__(name, value)

    @property
    def remaining(self) -> int:
        return self.max_calls - self.used

    def consume(self) -> None:
        """Charge one call, or refuse before the model is touched."""
        if self.used < 0:
            raise ValueError(f"budget counter is corrupt: used={self.used}")
        if self.used >= self.max_calls:
            raise JudgeBudgetExceededError(
                f"judge budget exhausted: {self.used}/{self.max_calls} calls used"
            )
        self.used += 1


def build_judge_prompt(
    *,
    title: str,
    body: str,
    niche: str = "",
    visual_summary: str = "",
) -> list[Any]:
    """Deterministic messages for one judging call (same input -> same prompt)."""
    payload = {
        "niche": niche,
        "title": title,
        "body": body,
        "visual_summary": visual_summary,
        "dimensions": list(JUDGE_DIMENSIONS),
    }
    return [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, sort_keys=True)),
    ]


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise JudgeOutputError(f"judge output has no JSON object: {text[:120]!r}")
    return stripped[start : end + 1]


def parse_judge_output(text: str) -> JudgeScores:
    """Parse one verdict, refusing anything that is not the agreed shape."""
    raw = _extract_json_object(text)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JudgeOutputError(f"judge output is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise JudgeOutputError(f"judge output must be an object, got {type(payload).__name__}")
    missing = [name for name in JUDGE_DIMENSIONS if name not in payload]
    if missing:
        raise JudgeOutputError(f"judge output missing dimensions: {', '.join(missing)}")
    try:
        return JudgeScores.model_validate(payload)
    except ValidationError as exc:
        raise JudgeOutputError(f"judge scores are out of range: {exc}") from exc


async def judge_content(
    model: Any,
    *,
    title: str,
    body: str,
    budget: JudgeBudget,
    niche: str = "",
    visual_summary: str = "",
) -> JudgeScores:
    """Ask *model* to score one piece of content; one call, charged up front.

    ``budget`` is required on purpose: an implicit per-call budget would make a
    loop over N fixtures spend N calls while every individual call "stayed under
    the cap".  Provider-level retries/fallbacks inside one ``ainvoke`` are not
    counted; this guard counts verdicts, not HTTP requests.
    """
    budget.consume()
    response = await model.ainvoke(
        build_judge_prompt(title=title, body=body, niche=niche, visual_summary=visual_summary)
    )
    content = getattr(response, "content", response)
    if not isinstance(content, str):
        raise JudgeOutputError(f"model returned {type(content).__name__}, expected text")
    return parse_judge_output(content)
