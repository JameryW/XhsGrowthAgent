"""LEGACY 文本→JSON 策略的表征测试（P1d-S4）。

这些断言**钉的是现状**，不全是"正确"：

- ``test_an_array_in_prose_is_truncated_to_its_first_element`` 钉的是一个**已知缺陷** ——
  ``parse_json_payload`` 把夹在散文里的数组按花括号边界截成了首个元素。修它等于改变
  所有 agent 的解析结果，属独立切片；本片只固化现状，不修。
- ``TestTheTwoParsersCannotBeMerged`` 把"两份实现不能合并"钉成断言 —— 将来谁想
  "顺手收敛"，会在这一组红，而不是在某个 agent 的行为回归里才被发现。
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from backend.agents.base import BaseAgent
from backend.models.json_parsing import UNPARSED, parse_json_payload
from backend.services.llm_enrichment import LLMEnrichmentError, LLMEnrichmentService

# (name, content, parse_json_payload 结果, 副本结果)。副本侧 UNPARSED 表示"抛错"。
# 期望值来自 S4 探针（`_s4_probe.py`）的实测输出，不是推断。
CORPUS: list[tuple[str, str, Any, Any]] = [
    (
        "raw_json_object",
        '{"key": "value", "number": 42}',
        {"key": "value", "number": 42},
        {"key": "value", "number": 42},
    ),
    ("fenced_json", '```json\n{"key": "value"}\n```', {"key": "value"}, {"key": "value"}),
    ("fenced_plain", '```\n{"key": "value"}\n```', {"key": "value"}, {"key": "value"}),
    (
        "raw_list_of_objects",
        '[{"id": 1}, {"id": 2}]',
        [{"id": 1}, {"id": 2}],
        [{"id": 1}, {"id": 2}],
    ),
    (
        "embedded_object_in_prose",
        'Some text {"key": "value"} more text',
        {"key": "value"},
        {"key": "value"},
    ),
    ("pure_prose", "Not valid JSON at all", UNPARSED, UNPARSED),
    # ↓ 本模块按花括号边界把数组截成了首个元素（已知缺陷）；副本给出了完整 list。
    (
        "embedded_array_in_prose",
        'Here are the results:\n[{"id": 1}, {"id": 2}]',
        {"id": 1},
        [{"id": 1}, {"id": 2}],
    ),
    ("bare_int_array", "[1, 2, 3]", [1, 2, 3], [1, 2, 3]),
    # ↓ 副本的贪婪 rescue 能捞出来，本模块不能。
    ("int_array_in_prose", "List: [1, 2, 3] done", UNPARSED, [1, 2, 3]),
    # ↓ 本模块的 _repair_json 补上缺失的引号，副本直接抛。
    ("unquoted_hashtags", '{"tags": ["#a", "#b", #c]}', {"tags": ["#a", "#b", "#c"]}, UNPARSED),
    ("bracket_mismatch", '{"a": [1, 2}', UNPARSED, UNPARSED),
    ("single_bare_array_object", '[{"a": 1}]', [{"a": 1}], [{"a": 1}]),
    # ↓ 本模块取首个对象；副本抛。
    ("two_objects", '前缀 {"a": 1} 中间 {"b": 2} 结尾', {"a": 1}, UNPARSED),
    ("fenced_array_of_objects", '```json\n[{"a": 1}]\n```', [{"a": 1}], [{"a": 1}]),
    ("empty_string", "", UNPARSED, UNPARSED),
    ("object_then_object_newline", '{"a": 1}\n{"b": 2}', {"a": 1}, UNPARSED),
    ("prose_with_braces", "Use {braces} to group items", UNPARSED, UNPARSED),
    (
        "markdown_two_blocks",
        '```json\n{"a": 1}\n```\nand\n```json\n{"b": 2}\n```',
        {"a": 1},
        {"a": 1},
    ),
]

CONTENT: dict[str, str] = {name: content for name, content, _b, _e in CORPUS}
BASE_EXPECTED: dict[str, Any] = {name: base for name, _c, base, _e in CORPUS}
ENRICH_EXPECTED: dict[str, Any] = {name: enrich for name, _c, _b, enrich in CORPUS}
NAMES = list(CONTENT)

DIVERGENT = {
    "embedded_array_in_prose",
    "int_array_in_prose",
    "unquoted_hashtags",
    "two_objects",
    "object_then_object_newline",
}


def _enrichment_side(content: str) -> Any:
    """副本的策略 —— 抛 ``LLMEnrichmentError`` 归一成 ``UNPARSED`` 便于比较。"""
    try:
        return LLMEnrichmentService()._parse_json_response(content)
    except LLMEnrichmentError:
        return UNPARSED


def _differs(name: str) -> bool:
    base = parse_json_payload(CONTENT[name])
    enrich = _enrichment_side(CONTENT[name])
    if base is UNPARSED or enrich is UNPARSED:
        return (base is UNPARSED) != (enrich is UNPARSED)
    return base != enrich


class _ProbeAgent(BaseAgent):
    """解析器只用到 ``self.agent_name``，其余抽象成员给最小实现。"""

    def __init__(self) -> None:
        self.agent_name = "probe"

    async def execute(self, state: Any, store: Any) -> dict[str, Any]:  # pragma: no cover
        return {}


class TestParseJsonPayload:
    """base 侧的解析策略，逐条钉住。"""

    @pytest.mark.parametrize("name", NAMES)
    def test_policy_is_characterised(self, name: str) -> None:
        expected = BASE_EXPECTED[name]
        result = parse_json_payload(CONTENT[name])
        if expected is UNPARSED:
            assert result is UNPARSED, f"{name}: expected UNPARSED, got {result!r}"
        else:
            assert result == expected, f"{name}: expected {expected!r}, got {result!r}"

    def test_an_array_in_prose_is_truncated_to_its_first_element(self) -> None:
        """**已知缺陷**，刻意钉住：修它就是在迁移外衣下改所有 agent 的解析结果。"""
        assert parse_json_payload(CONTENT["embedded_array_in_prose"]) == {"id": 1}

    def test_unparsed_is_not_a_valid_json_value(self) -> None:
        """哨兵不能用 ``None``：``null`` 是合法 JSON，会把一次成功说成失败。"""
        assert parse_json_payload("null") is None
        assert parse_json_payload("null") is not UNPARSED

    def test_missing_quotes_around_hashtags_are_repaired(self) -> None:
        assert parse_json_payload(CONTENT["unquoted_hashtags"]) == {"tags": ["#a", "#b", "#c"]}

    def test_a_bare_array_still_parses_although_the_annotation_says_dict(self) -> None:
        """``_parse_json_response`` 注解是 ``dict``，但直连 ``json.loads`` 会给出 list。

        S2b 的 ``accepts_bare_list`` 就是为这个既有事实存在的。
        """
        assert parse_json_payload('[{"a": 1}]') == [{"a": 1}]


class TestTheAgentBoundaryIsUnchanged:
    """抽取成模块级函数后，agent 边界的契约逐字保持。"""

    def test_still_returns_the_raw_content_sentinel(self) -> None:
        assert _ProbeAgent()._parse_json_response("Not valid JSON at all") == {
            "raw_content": "Not valid JSON at all"
        }

    def test_still_returns_the_parsed_payload_when_it_can(self) -> None:
        assert _ProbeAgent()._parse_json_response('{"a": 1}') == {"a": 1}

    def test_still_warns_with_the_agent_name(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="xhs_growth.agents"):
            _ProbeAgent()._parse_json_response("Not valid JSON at all")
        assert "Failed to parse JSON response from probe" in caplog.text


class TestTheTwoParsersCannotBeMerged:
    """S4 的结论：两份**不是副本**，合并会改变行为。"""

    @pytest.mark.parametrize("name", NAMES)
    def test_enrichment_copy_is_characterised(self, name: str) -> None:
        expected = ENRICH_EXPECTED[name]
        if expected is UNPARSED:
            with pytest.raises(LLMEnrichmentError):
                LLMEnrichmentService()._parse_json_response(CONTENT[name])
        else:
            assert _enrichment_side(CONTENT[name]) == expected

    def test_the_divergent_corpus_is_exactly_these_five_entries(self) -> None:
        assert {name for name in NAMES if _differs(name)} == DIVERGENT

    def test_neither_side_accepts_a_superset_of_the_other(self) -> None:
        """两个方向都非空 → 谁也不能替换谁。这条是"不合并"的硬证据。"""
        base_only = {
            name
            for name in NAMES
            if parse_json_payload(CONTENT[name]) is not UNPARSED
            and _enrichment_side(CONTENT[name]) is UNPARSED
        }
        enrich_only = {
            name
            for name in NAMES
            if parse_json_payload(CONTENT[name]) is UNPARSED
            and _enrichment_side(CONTENT[name]) is not UNPARSED
        }
        assert base_only == {"unquoted_hashtags", "two_objects", "object_then_object_newline"}
        assert enrich_only == {"int_array_in_prose"}
