"""P3/E4: the quality judge — shape, scoring and the 199-call budget.

The judge runs against real content in an experiment, so the two things that can
go wrong quietly are a verdict that does not parse and a run that spends more
calls than approved.  Both are pinned here with a fake model: no network, no
keys, deterministic.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO / "scripts" / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import judge  # noqa: E402

GOOD = {
    "copywriting": 8,
    "visual": 7,
    "compliance": 9,
    "reach": 6,
    "audience": 8,
    "rationale": "标题具体，正文有信息密度。",
    "bias_warning": "",
}


class FakeModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0
        self.messages: list[object] = []

    async def ainvoke(self, messages):
        self.calls += 1
        self.messages = list(messages)
        return SimpleNamespace(content=self.content)


def test_the_prompt_is_deterministic_and_carries_the_content():
    first = judge.build_judge_prompt(title="标题", body="正文", niche="家居")
    second = judge.build_judge_prompt(title="标题", body="正文", niche="家居")
    assert [message.content for message in first] == [message.content for message in second]
    assert "标题" in first[1].content and "正文" in first[1].content
    assert all(name in first[1].content for name in judge.JUDGE_DIMENSIONS)


def test_plain_json_parses_and_overall_is_the_mean():
    scores = judge.parse_judge_output(json.dumps(GOOD, ensure_ascii=False))
    assert scores.copywriting == 8
    assert scores.overall == 7.6
    assert scores.rationale.startswith("标题")


def test_fenced_json_and_surrounding_prose_are_tolerated():
    fenced = "```json\n" + json.dumps(GOOD) + "\n```"
    assert judge.parse_judge_output(fenced).overall == 7.6
    prose = "评审结果如下：\n" + json.dumps(GOOD) + "\n以上。"
    assert judge.parse_judge_output(prose).overall == 7.6


def test_a_missing_dimension_is_refused():
    payload = dict(GOOD)
    payload.pop("audience")
    with pytest.raises(judge.JudgeOutputError):
        judge.parse_judge_output(json.dumps(payload))


def test_out_of_range_scores_are_refused():
    payload = dict(GOOD, copywriting=11)
    with pytest.raises(judge.JudgeOutputError):
        judge.parse_judge_output(json.dumps(payload))


def test_non_json_output_is_refused_with_a_preview():
    with pytest.raises(judge.JudgeOutputError) as excinfo:
        judge.parse_judge_output("这个内容不错，我给 8 分")
    assert "no JSON object" in str(excinfo.value)


def test_the_budget_defaults_to_199_and_refuses_after_it():
    budget = judge.JudgeBudget()
    assert budget.max_calls == 199
    for _ in range(199):
        budget.consume()
    assert budget.remaining == 0
    with pytest.raises(judge.JudgeBudgetExceededError):
        budget.consume()


def test_the_budget_refuses_a_nonsense_cap():
    with pytest.raises(ValueError):
        judge.JudgeBudget(max_calls=0)


def test_judging_charges_one_call_and_returns_scores():
    model = FakeModel(json.dumps(GOOD))
    budget = judge.JudgeBudget(max_calls=3)

    scores = asyncio.run(judge.judge_content(model, title="标题", body="正文", budget=budget))

    assert scores.overall == 7.6
    assert model.calls == 1
    assert budget.used == 1


def test_an_exhausted_budget_refuses_before_the_model_is_called():
    model = FakeModel(json.dumps(GOOD))
    budget = judge.JudgeBudget(max_calls=1)
    budget.consume()

    with pytest.raises(judge.JudgeBudgetExceededError):
        asyncio.run(judge.judge_content(model, title="t", body="b", budget=budget))
    assert model.calls == 0


def test_a_model_that_breaks_the_shape_still_spends_its_call():
    model = FakeModel("不是 JSON")
    budget = judge.JudgeBudget(max_calls=2)
    with pytest.raises(judge.JudgeOutputError):
        asyncio.run(judge.judge_content(model, title="t", body="b", budget=budget))
    assert model.calls == 1
    assert budget.used == 1


def test_a_budget_cap_above_the_approval_is_refused():
    """No caller may quietly raise the 199-call approval by passing a big number."""
    with pytest.raises(ValueError):
        judge.JudgeBudget(max_calls=200)
    with pytest.raises(ValueError):
        judge.JudgeBudget(max_calls=10**9)
    assert judge.JudgeBudget(max_calls=199).max_calls == 199


def test_the_budget_counter_cannot_start_or_go_negative():
    with pytest.raises(ValueError):
        judge.JudgeBudget(used=-1)
    with pytest.raises(ValueError):
        judge.JudgeBudget(max_calls=5, used=6)
    budget = judge.JudgeBudget()
    with pytest.raises(AttributeError):
        budget.max_calls = 10**6
    assert budget.max_calls == 199
