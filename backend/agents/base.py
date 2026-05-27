"""Base agent class — shared logic for all XHS Growth sub-agents."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.config.models import TaskType
from backend.models.router import get_model
from backend.memory.store import MemoryManager
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents")


class BaseAgent(ABC):
    """所有子 Agent 的基类"""

    task_type: TaskType = TaskType.ROUTING
    agent_name: str = "base"
    prompt_file: str = ""

    def __init__(self):
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
            return {"system": data.get("system", ""), "user_template": data.get("user_template", "")}
        return {"system": "", "user_template": ""}

    def _build_system_prompt(self, state: XHSGrowthState, extra_context: str = "") -> str:
        template = self.prompt_template.get("system", "")
        if extra_context:
            template = template.replace("{memory_context}", extra_context)
        return template

    async def _recall_memory(self, store: BaseStore, account_id: str, query: str, namespace: str, limit: int = 5) -> list[dict]:
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

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        """从 LLM 响应中提取 JSON（增强版，处理多种格式）"""
        try:
            # 1. 尝试直接解析纯 JSON
            stripped = content.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                return json.loads(stripped)

            # 2. 尝试从 markdown code block 中提取
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            if "```" in content:
                parts = content.split("```")
                for i, part in enumerate(parts):
                    if i % 2 == 1:  # 奇数索引是代码块内容
                        try:
                            return json.loads(part.strip())
                        except json.JSONDecodeError:
                            continue

            # 3. 尝试从文本中提取 JSON 对象
            import re
            json_pattern = r'\{[^{}]*\}'
            matches = re.findall(json_pattern, content)
            for match in matches:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    continue

            # 4. 尝试找到第一个 { 和最后一个 }
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                json_str = content[start:end+1]
                return json.loads(json_str)

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
        """LangGraph node 入口点"""
        try:
            result = await self.execute(state, store)
            result["current_agent"] = self.agent_name
            return result
        except Exception as e:
            logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
            return {
                "error": f"{self.agent_name}: {type(e).__name__}: {e}",
                "retry_count": state.get("retry_count", 0) + 1,
                "current_agent": self.agent_name,
            }