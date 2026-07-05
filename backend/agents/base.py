"""Base agent class — shared logic for all XHS Growth sub-agents."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, cast

import yaml
from langchain_core.language_models import BaseChatModel
from langgraph.store.base import BaseStore

from backend.config.models import TaskType
from backend.memory.store import MemoryManager
from backend.models.router import get_model
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents")


class BaseAgent(ABC):
    """所有子 Agent 的基类"""

    task_type: TaskType = TaskType.ROUTING
    agent_name: str = "base"
    prompt_file: str = ""

    def __init__(self) -> None:
        self._model: BaseChatModel | None = None
        self._prompt_template: dict[str, str] | None = None

    @property
    def model(self) -> BaseChatModel:
        if self._model is None:
            self._model = get_model(self.task_type.value)
        return self._model

    @property
    def prompt_template(self) -> dict[str, str]:
        if self._prompt_template is None:
            self._prompt_template = self._load_prompt()
        return self._prompt_template

    def _load_prompt(self) -> dict[str, str]:
        if not self.prompt_file:
            return {"system": "", "user_template": ""}
        path = Path(__file__).parent.parent / "config" / "prompts" / self.prompt_file
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            return {
                "system": data.get("system", ""),
                "user_template": data.get("user_template", ""),
            }
        return {"system": "", "user_template": ""}

    def _build_system_prompt(self, state: XHSGrowthState, extra_context: str = "") -> str:
        template = self.prompt_template.get("system", "")
        niche = state.get("niche", "母婴")
        template = template.replace("{account_niche}", niche)
        template = template.replace("{memory_context}", extra_context)
        return template

    async def _recall_memory(
        self,
        store: BaseStore,
        account_id: str,
        query: str,
        namespace: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if store is None:
            return []
        try:
            mm = MemoryManager(account_id)
            ns_map = {
                "content_history": mm.content_history_ns,
                "audience_preferences": mm.audience_ns,
                "performance_insights": mm.insights_ns,
                "strategy_notes": mm.strategy_ns,
            }
            ns = ns_map.get(namespace, mm.insights_ns)
            items = await store.asearch(ns, query=query, limit=limit)
            return [item.value for item in items]
        except Exception as e:
            logger.warning(f"_recall_memory failed (ns={namespace}): {e}")
            return []

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        """从 LLM 响应中提取 JSON（增强版，处理多种格式和常见语法错误）"""
        import re

        def repair_json(json_str: str) -> str:
            """修复常见的 JSON 语法错误"""
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
            json_str = "".join(result)
            return json_str

        def extract_json_from_markdown(text: str) -> str:
            """从 markdown 代码块中提取 JSON"""
            if "```json" in text:
                return text.split("```json")[1].split("```")[0].strip()
            if "```" in text:
                parts = text.split("```")
                for i, part in enumerate(parts):
                    if i % 2 == 1:  # 奇数索引是代码块内容
                        return part.strip()
            return text

        try:
            # 1. 提取 JSON 内容
            json_content = extract_json_from_markdown(content)

            # 2. 尝试直接解析
            try:
                return cast(dict[str, Any], json.loads(json_content))
            except json.JSONDecodeError:
                pass

            # 3. 尝试修复常见语法错误后解析
            repaired = repair_json(json_content)
            try:
                return cast(dict[str, Any], json.loads(repaired))
            except json.JSONDecodeError:
                pass

            # 4. 尝试从文本中找到 JSON 对象边界
            start = json_content.find("{")
            end = json_content.rfind("}")
            if start != -1 and end != -1 and end > start:
                json_str = json_content[start : end + 1]
                try:
                    return cast(dict[str, Any], json.loads(json_str))
                except json.JSONDecodeError:
                    repaired = repair_json(json_str)
                    try:
                        return cast(dict[str, Any], json.loads(repaired))
                    except json.JSONDecodeError:
                        pass

            # 5. 尝试正则匹配 JSON 对象
            json_pattern = r"\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\}"
            matches = re.findall(json_pattern, content)
            for match in matches:
                try:
                    return cast(dict[str, Any], json.loads(match))
                except json.JSONDecodeError:
                    repaired = repair_json(match)
                    try:
                        return cast(dict[str, Any], json.loads(repaired))
                    except json.JSONDecodeError:
                        continue

            # 所有方法都失败
            logger.warning(f"Failed to parse JSON response from {self.agent_name}: {content[:200]}")
            return {"raw_content": content}
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"JSON decode error in {self.agent_name}: {e}")
            return {"raw_content": content}

    @abstractmethod
    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        """执行 Agent 核心逻辑，返回状态更新字典"""
        ...

    async def __call__(self, state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
        """LangGraph node entry point.

        Wraps execute() with node-level timing → appends one performance_log
        entry per successful call. The entry rides the returned dict under
        `performance_log: [entry]`; LangGraph's `_append_list` reducer merges
        it into state. Recording is best-effort: a timer failure must not
        break the node (see PRD: 节点级指标).

        On failure we re-raise (LangGraph retry needs the exception); a failed
        entry can't be written to state mid-exception, so retries/failed-count
        is captured indirectly: the next successful call's `retries` field
        (sourced from state.retry_count, which the retry router increments)
        records how many attempts preceded this success.
        """
        from backend.agents.nodes._base import node_perf_entry
        from backend.core.error_handling import AgentError

        started = _now_iso()
        retries = int(state.get("retry_count", 0) or 0)
        try:
            result = await self.execute(state, store)
        except Exception as e:
            logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
            # Propagate to LangGraph retry mechanism. State can't be updated
            # on a raised exception — the retry's next successful call records
            # the attempt count via its `retries` field.
            raise AgentError(self.agent_name, e) from e

        result["current_agent"] = self.agent_name
        result["error"] = None  # Clear stale error on success
        try:
            result["performance_log"] = [
                node_perf_entry(
                    self.agent_name,
                    started_at=started,
                    completed_at=_now_iso(),
                    status="success",
                    error=None,
                    retries=retries,
                )
            ]
        except Exception as timer_err:  # best-effort: never break the node
            logger.debug("performance_log node entry failed: %s", timer_err)
        return result


def _now_iso() -> str:
    """UTC ISO8601 timestamp for performance_log entries."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
