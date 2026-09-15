"""Legacy free-text → JSON extraction (P1d-S4).

**这份实现不是"迁完就能删的旧代码"，它是新链路第三档的解析器。**
``BaseAgent._structured_call`` 在 ``PROMPTED`` / ``JSON_OBJECT`` 两档走的就是它 ——
见 ``backend/agents/base.py`` 里 ``return parse_json_payload(...)`` 那一行。
云端 provider 的表把 13/15 个 TaskType 判成 ``PROMPTED``，所以它在**生产主路径**上
（探针实测，非推断）。删除前提只有一个：三档只剩 ``NATIVE_SCHEMA``。

本模块只放**策略**，不放契约。两个调用点的失败契约刻意不同，且两边都承重：

=============================  ===========================  ==========================
调用点                          失败时                       独有策略
=============================  ===========================  ==========================
``BaseAgent``                  ``{"raw_content": content}``   ``_repair_json``
（**哨兵**，不抛）              —— 一个**合法 dict**          （补 ``#`` 引号 + 括号修复）
``LLMEnrichmentService``       ``raise LLMEnrichmentError``   贪婪 ``\\{…\\}|\\[…\\]``
（**抛**，不哨兵）              —— 触发 ``fallback_fn``        数组抢救
=============================  ===========================  ==========================

**两份不是副本，不能合并。** 探针测了 18 条语料，5 条接受集不同，且**双向都不包含**：

- ``'Here are the results:\n[{"id": 1}, {"id": 2}]'``
  → 本模块 ``{'id': 1}``（按花括号边界把数组截成了首个元素，**答错了**）；
    副本 ``[{'id': 1}, {'id': 2}]``（对）。
- ``'List: [1, 2, 3] done'`` → 本模块不解析；副本 ``[1, 2, 3]``。
- ``'{"tags": ["#a", "#b", #c]}'`` → 本模块修复缺引号后解析；副本抛错。
- ``'{"a": 1}\n{"b": 2}'`` → 本模块取**首个**对象；副本抛错。

合并成任一份都会改变另一份的行为，而 S1 的红线写着「不动 ``_parse_json_response``
的现有行为」。所以 S4 的结论是**不合并**，并把这张表钉成可执行断言：
``tests/unit/models/test_json_parsing.py`` 里谁单方面"顺手收敛"，谁就红。

（第二条是**既有缺陷**，本片刻意不修：修它就是在迁移外衣下改变所有 agent 的解析
结果。它被显式钉在表征测试里，将来要修单独开片。）
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

__all__ = ["UNPARSED", "parse_json_payload"]


class _Unparsed:
    """Singleton marker: no strategy produced a payload.

    故意不用 ``None`` —— ``None`` 是一个**合法的 JSON 值**（``json.loads("null")``），
    拿它当"没解析出来"会把一次成功的解析说成失败。
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "UNPARSED"


UNPARSED: Final = _Unparsed()


def _repair_json(json_str: str) -> str:
    """修复常见的 JSON 语法错误。"""
    # 修复缺少引号的值（如 #hashtag -> "#hashtag"）
    # 匹配数组中缺少引号的元素: [, #value, -> , "#value",
    json_str = re.sub(r',\s*#([^\s,\[\]"]+)', r', "#\1"', json_str)
    # 修复缺少引号的值开头: [#value, -> ["#value",
    json_str = re.sub(r'\[\s*#([^\s,\[\]"]+)', r'["#\1"', json_str)
    # 修复缺少引号的值结尾: , #value] -> , "#value"]
    json_str = re.sub(r',\s*#([^\s,\[\]"]+)\s*\]', r', "#\1"]', json_str)

    # 修复括号不匹配：] 闭合 { 或 } 闭合 [
    result = []
    stack = []
    for ch in json_str:
        if ch in ("{", "["):
            stack.append(ch)
            result.append(ch)
        elif ch == "}" and stack and stack[-1] == "[":
            stack.pop()
            result.append("]")
        elif ch == "]" and stack and stack[-1] == "{":
            stack.pop()
            result.append("}")
        elif ch in ("}", "]"):
            if stack:
                stack.pop()
            result.append(ch)
        else:
            result.append(ch)
    return "".join(result)


def _extract_json_from_markdown(text: str) -> str:
    """从 markdown 代码块中提取 JSON。"""
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        parts = text.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 1:  # 奇数索引是代码块内容
                return part.strip()
    return text


def parse_json_payload(content: str) -> Any:
    """``BaseAgent`` 侧的解析策略，逐行照搬自 ``_parse_json_response_impl``。

    返回解析到的值（dict / list / 标量），**一份策略都没成功时返回 ``UNPARSED``**。
    本函数**不记日志、不抛业务异常**：日志文案与哨兵转换留在调用点，因为两处调用点
    的文案与契约都不同（见模块 docstring）。
    """
    # 1. 提取 JSON 内容
    json_content = _extract_json_from_markdown(content)

    # 2. 尝试直接解析
    try:
        return json.loads(json_content)
    except json.JSONDecodeError:
        pass

    # 3. 尝试修复常见语法错误后解析
    repaired = _repair_json(json_content)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # 4. 尝试从文本中找到 JSON 对象边界
    start = json_content.find("{")
    end = json_content.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = json_content[start : end + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            repaired = _repair_json(json_str)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    # 5. 尝试正则匹配 JSON 对象
    json_pattern = r"\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\}"
    matches = re.findall(json_pattern, content)
    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            repaired = _repair_json(match)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                continue

    # 所有方法都失败 —— 由调用点决定是哨兵还是抛错
    return UNPARSED
