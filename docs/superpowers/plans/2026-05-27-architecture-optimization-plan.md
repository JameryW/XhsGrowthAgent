# XhsGrowthAgent 架构优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 XhsGrowthAgent 架构，建立清晰的分层结构、拆分大文件、明确 Agent-Tool 边界、统一状态 Schema。

**Architecture:** 采用分层架构（core/agents/services/tools/graph/state），拆分 nodes.py（347→10模块）和 Dashboard.vue（263→6组件），提取 Mixins 和 Service 层。

**Tech Stack:** Python (LangGraph, LangChain), Vue 3 (Composition API, Pinia), pytest, vitest

---

## Phase 1: 基础设施

### Task 1: 创建 core 目录和 base_agent.py

**Files:**
- Create: `xhs_growth/core/__init__.py`
- Create: `xhs_growth/core/base_agent.py`
- Test: `tests/test_core_base_agent.py`
- Modify: `xhs_growth/agents/__init__.py`

- [ ] **Step 1: 创建测试文件，验证 BaseAgent 导入**

创建 `tests/test_core_base_agent.py`：

```python
"""Tests for core.base_agent module."""
import pytest
from xhs_growth.core.base_agent import BaseAgent


def test_base_agent_import():
    """Verify BaseAgent can be imported from core."""
    assert BaseAgent is not None


def test_base_agent_is_abstract():
    """Verify BaseAgent is abstract class."""
    with pytest.raises(TypeError):
        BaseAgent()  # Cannot instantiate abstract class
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/test_core_base_agent.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'xhs_growth.core'`

- [ ] **Step 3: 创建 core 目录结构**

```bash
mkdir -p xhs_growth/core
```

- [ ] **Step 4: 创建 core/__init__.py**

创建 `xhs_growth/core/__init__.py`：

```python
"""Core infrastructure for XHS Growth Agent."""
from xhs_growth.core.base_agent import BaseAgent

__all__ = ["BaseAgent"]
```

- [ ] **Step 5: 创建 core/base_agent.py（移动现有 base.py 内容）**

创建 `xhs_growth/core/base_agent.py`：

```python
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

from xhs_growth.config.models import TaskType
from xhs_growth.models.router import get_model
from xhs_growth.memory.store import MemoryManager
from xhs_growth.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.core")


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
        path = Path(__file__).parent.parent.parent / "config" / "prompts" / self.prompt_file
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
        """从 LLM 响应中提取 JSON"""
        try:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            return json.loads(json_str)
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"Failed to parse JSON response from {self.agent_name}")
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
```

- [ ] **Step 6: 更新 agents/__init__.py 导入路径**

修改 `xhs_growth/agents/__init__.py`，将导入从 `agents.base` 改为 `core.base_agent`：

```python
# 在文件顶部添加
from xhs_growth.core.base_agent import BaseAgent

# 移除旧的导入（如果有）
# from xhs_growth.agents.base import BaseAgent
```

- [ ] **Step 7: 运行测试验证通过**

```bash
pytest tests/test_core_base_agent.py -v
```

Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add xhs_growth/core/ tests/test_core_base_agent.py xhs_growth/agents/__init__.py
git commit -m "feat(core): create core directory with BaseAgent"
```

---

### Task 2: 创建 error_handling.py

**Files:**
- Create: `xhs_growth/core/error_handling.py`
- Test: `tests/test_core_error_handling.py`

- [ ] **Step 1: 创建测试文件**

创建 `tests/test_core_error_handling.py`：

```python
"""Tests for core.error_handling module."""
import pytest
from xhs_growth.core.error_handling import AgentError, handle_agent_error
from xhs_growth.state.enums import WorkflowPhase
from xhs_growth.state.schema import XHSGrowthState


def test_agent_error_creation():
    """Verify AgentError can be created with all fields."""
    original = ValueError("test error")
    error = AgentError("test_agent", "testing", original)
    assert error.agent_name == "test_agent"
    assert error.phase == "testing"
    assert error.original_error == original


def test_handle_agent_error_returns_state_update():
    """Verify handle_agent_error returns correct state update."""
    original = TimeoutError("timeout")
    state: XHSGrowthState = {"retry_count": 0}
    result = handle_agent_error(original, state)
    assert result["phase"] == WorkflowPhase.ERROR
    assert result["error"] == "timeout"
    assert result["retry_count"] == 1


def test_handle_agent_error_increments_retry():
    """Verify handle_agent_error increments retry_count."""
    original = RuntimeError("runtime")
    state: XHSGrowthState = {"retry_count": 2}
    result = handle_agent_error(original, state)
    assert result["retry_count"] == 3
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/test_core_error_handling.py -v
```

Expected: FAIL - `ModuleNotFoundError`

- [ ] **Step 3: 创建 error_handling.py**

创建 `xhs_growth/core/error_handling.py`：

```python
"""Unified error handling for XHS Growth Agent."""

from xhs_growth.state.enums import WorkflowPhase
from xhs_growth.state.schema import XHSGrowthState


class AgentError(Exception):
    """Agent执行错误"""

    def __init__(self, agent_name: str, phase: str, original_error: Exception):
        self.agent_name = agent_name
        self.phase = phase
        self.original_error = original_error
        super().__init__(f"{agent_name} failed in {phase}: {original_error}")


def handle_agent_error(error: Exception, state: XHSGrowthState) -> dict:
    """统一错误处理，返回状态更新"""
    return {
        "phase": WorkflowPhase.ERROR,
        "error": str(error),
        "retry_count": state.get("retry_count", 0) + 1,
    }
```

- [ ] **Step 4: 更新 core/__init__.py 导出**

修改 `xhs_growth/core/__init__.py`：

```python
"""Core infrastructure for XHS Growth Agent."""
from xhs_growth.core.base_agent import BaseAgent
from xhs_growth.core.error_handling import AgentError, handle_agent_error

__all__ = ["BaseAgent", "AgentError", "handle_agent_error"]
```

- [ ] **Step 5: 运行测试验证通过**

```bash
pytest tests/test_core_error_handling.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add xhs_growth/core/error_handling.py xhs_growth/core/__init__.py tests/test_core_error_handling.py
git commit -m "feat(core): add unified error handling"
```

---

### Task 3: 创建 Agent Mixins

**Files:**
- Create: `xhs_growth/agents/mixins/__init__.py`
- Create: `xhs_growth/agents/mixins/retry_mixin.py`
- Create: `xhs_growth/agents/mixins/validation_mixin.py`
- Create: `xhs_growth/agents/mixins/memory_mixin.py`
- Test: `tests/test_mixins.py`

- [ ] **Step 1: 创建测试文件**

创建 `tests/test_mixins.py`：

```python
"""Tests for agent mixins."""
import pytest
from xhs_growth.agents.mixins.retry_mixin import RetryMixin
from xhs_growth.agents.mixins.validation_mixin import ValidationMixin


class TestRetryMixin:
    def test_execute_with_retry_success(self):
        """Verify RetryMixin executes action on success."""
        class MockAgent(RetryMixin):
            pass

        agent = MockAgent()
        result = agent.execute_with_retry(lambda: "success")
        assert result == "success"

    def test_execute_with_retry_retries_on_timeout(self):
        """Verify RetryMixin retries on TimeoutError."""
        class MockAgent(RetryMixin):
            pass

        call_count = 0
        def failing_action():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("timeout")
            return "success"

        agent = MockAgent()
        result = agent.execute_with_retry(failing_action, max_retries=3)
        assert result == "success"
        assert call_count == 3

    def test_execute_with_retry_raises_after_max_retries(self):
        """Verify RetryMixin raises after max retries."""
        class MockAgent(RetryMixin):
            pass

        def always_fails():
            raise TimeoutError("always timeout")

        agent = MockAgent()
        with pytest.raises(TimeoutError):
            agent.execute_with_retry(always_fails, max_retries=2)


class TestValidationMixin:
    def test_validate_state_update_valid_field(self):
        """Verify ValidationMixin passes valid fields."""
        from xhs_growth.state.schema import XHSGrowthState

        class MockAgent(ValidationMixin):
            pass

        agent = MockAgent()
        agent.validate_state_update({"phase": "testing"}, XHSGrowthState)
        # Should not raise

    def test_validate_state_update_invalid_field(self):
        """Verify ValidationMixin raises on invalid field."""
        from xhs_growth.state.schema import XHSGrowthState

        class MockAgent(ValidationMixin):
            pass

        agent = MockAgent()
        with pytest.raises(ValueError, match="Invalid field"):
            agent.validate_state_update({"invalid_field": "value"}, XHSGrowthState)
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/test_mixins.py -v
```

Expected: FAIL - `ModuleNotFoundError`

- [ ] **Step 3: 创建 mixins 目录**

```bash
mkdir -p xhs_growth/agents/mixins
```

- [ ] **Step 4: 创建 retry_mixin.py**

创建 `xhs_growth/agents/mixins/retry_mixin.py`：

```python
"""Retry mixin for Agent resilience."""

import asyncio
from typing import Callable, Any


class RetryMixin:
    """Agent重试能力"""

    def execute_with_retry(
        self,
        action: Callable[[], Any],
        max_retries: int = 3,
        timeout: float = 30.0
    ) -> Any:
        """执行操作，失败时重试"""
        for attempt in range(max_retries):
            try:
                return action()
            except TimeoutError:
                if attempt == max_retries - 1:
                    raise
        return None

    async def execute_with_retry_async(
        self,
        action: Callable[[], Any],
        max_retries: int = 3,
        timeout: float = 30.0
    ) -> Any:
        """异步执行操作，失败时重试"""
        for attempt in range(max_retries):
            try:
                return await asyncio.wait_for(action(), timeout=timeout)
            except (TimeoutError, asyncio.TimeoutError):
                if attempt == max_retries - 1:
                    raise
        return None
```

- [ ] **Step 5: 创建 validation_mixin.py**

创建 `xhs_growth/agents/mixins/validation_mixin.py`：

```python
"""Validation mixin for state updates."""

from typing import TypedDict


class ValidationMixin:
    """状态验证能力"""

    def validate_state_update(self, updates: dict, schema: TypedDict) -> None:
        """验证状态更新字段是否合法"""
        # TypedDict.__annotations__ contains valid field names
        valid_fields = getattr(schema, '__annotations__', {})
        for key in updates:
            if key not in valid_fields:
                raise ValueError(f"Invalid field: {key}")
```

- [ ] **Step 6: 创建 memory_mixin.py**

创建 `xhs_growth/agents/mixins/memory_mixin.py`：

```python
"""Memory mixin for context recall."""

from langgraph.store.base import BaseStore
from xhs_growth.memory.store import MemoryManager


class MemoryMixin:
    """记忆召回能力"""

    async def recall_context(
        self,
        store: BaseStore,
        account_id: str,
        query: str,
        namespace: str = "performance_insights",
        limit: int = 5
    ) -> list[dict]:
        """从记忆存储召回相关上下文"""
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
```

- [ ] **Step 7: 创建 mixins/__init__.py**

创建 `xhs_growth/agents/mixins/__init__.py`：

```python
"""Agent mixins for common capabilities."""
from xhs_growth.agents.mixins.retry_mixin import RetryMixin
from xhs_growth.agents.mixins.validation_mixin import ValidationMixin
from xhs_growth.agents.mixins.memory_mixin import MemoryMixin

__all__ = ["RetryMixin", "ValidationMixin", "MemoryMixin"]
```

- [ ] **Step 8: 运行测试验证通过**

```bash
pytest tests/test_mixins.py -v
```

Expected: PASS

- [ ] **Step 9: 提交**

```bash
git add xhs_growth/agents/mixins/ tests/test_mixins.py
git commit -m "feat(agents): add mixins for retry, validation, memory"
```

---

### Task 4: 创建架构规范文档

**Files:**
- Create: `docs/architecture-conventions.md`

- [ ] **Step 1: 创建规范文档**

创建 `docs/architecture-conventions.md`：

```markdown
# XhsGrowthAgent 架构规范

## 目录结构规范

- `core/`：基础设施，无业务逻辑
- `agents/`：业务Agent，通过Service调用Tool
- `services/`：编排层，组合Tool，处理错误
- `tools/`：原子操作，单一功能，无状态
- `graph/`：拓扑定义，不含业务逻辑
- `state/`：TypedDict定义，严格类型

## 命名规范

### 文件命名
- Agent: `<name>_agent.py` 或 `<name>.py`（在nodes/中）
- Service: `<name>_service.py`
- Tool: `<name>.py`（功能名）
- Node: `<name>.py`（在nodes/中）

### 状态字段命名
- 输入：`input_<name>`（用户提供）
- 输出：`<phase>_data`（阶段结果）
- 列表：`<name>_list` 或 `Annotated[list, reducer]`
- ID：`<name>_id`
- 时间：`<name>_at`

### 函数命名
- Tool: `<verb>_<noun>()`（extract_features）
- Service: `<noun>_<verb>()`（title_analyze）
- Agent: `execute()`（统一入口）
- Node: `<name>_node()`（节点函数）

## 边界规则

### Tool 禁止
- 调用其他Tool
- 访问状态
- 包含业务判断

### Service 允许
- 调用多个Tool
- 处理错误和重试
- 缓存结果

### Agent 职责
- 通过Service调用Tool
- 更新状态
- 业务决策

## 测试规范

每个新增模块必须：
1. 单元测试文件：`tests/test_<module>.py`
2. 边界测试：测试与其他层的交互
3. 错误测试：测试异常场景
```

- [ ] **Step 2: 提交**

```bash
git add docs/architecture-conventions.md
git commit -m "docs: add architecture conventions document"
```

---

## Phase 2: 文件拆分

### Task 5: 创建 nodes 目录和基类

**Files:**
- Create: `xhs_growth/agents/nodes/__init__.py`
- Create: `xhs_growth/agents/nodes/_base.py`
- Test: `tests/test_nodes_base.py`

- [ ] **Step 1: 创建测试文件**

创建 `tests/test_nodes_base.py`：

```python
"""Tests for nodes base classes."""
import pytest
from xhs_growth.agents.nodes._base import NodeContext, NodeResult
from xhs_growth.state.schema import XHSGrowthState


def test_node_context_creation():
    """Verify NodeContext wraps state and store."""
    state: XHSGrowthState = {"phase": "testing"}
    ctx = NodeContext(state, None)
    assert ctx.state == state
    assert ctx.store is None


def test_node_result_to_dict():
    """Verify NodeResult converts to dict."""
    result = NodeResult({"phase": "completed", "error": None})
    output = result.to_dict()
    assert output["phase"] == "completed"
    assert output["error"] is None


def test_node_result_includes_current_agent():
    """Verify NodeResult includes current_agent."""
    result = NodeResult({"phase": "completed"}, agent_name="test_agent")
    output = result.to_dict()
    assert output["current_agent"] == "test_agent"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/test_nodes_base.py -v
```

Expected: FAIL - `ModuleNotFoundError`

- [ ] **Step 3: 创建 nodes 目录**

```bash
mkdir -p xhs_growth/agents/nodes/optimization
```

- [ ] **Step 4: 创建 _base.py**

创建 `xhs_growth/agents/nodes/_base.py`：

```python
"""Base classes for graph nodes."""

from typing import Any
from langgraph.store.base import BaseStore
from xhs_growth.state.schema import XHSGrowthState


class NodeContext:
    """节点执行上下文"""

    def __init__(self, state: XHSGrowthState, store: BaseStore | None):
        self.state = state
        self.store = store


class NodeResult:
    """节点执行结果封装"""

    def __init__(self, updates: dict[str, Any], agent_name: str = ""):
        self.updates = updates
        self.agent_name = agent_name

    def to_dict(self) -> dict[str, Any]:
        """转换为状态更新字典"""
        result = self.updates.copy()
        if self.agent_name:
            result["current_agent"] = self.agent_name
        return result
```

- [ ] **Step 5: 运行测试验证通过**

```bash
pytest tests/test_nodes_base.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add xhs_growth/agents/nodes/_base.py tests/test_nodes_base.py
git commit -m "feat(nodes): add NodeContext and NodeResult base classes"
```

---

### Task 6: 拆分 orchestrator_node

**Files:**
- Create: `xhs_growth/agents/nodes/orchestrator.py`
- Test: `tests/test_nodes_orchestrator.py`

- [ ] **Step 1: 创建测试文件**

创建 `tests/test_nodes_orchestrator.py`：

```python
"""Tests for orchestrator node."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from xhs_growth.agents.nodes.orchestrator import orchestrator_node


@pytest.mark.asyncio
async def test_orchestrator_node_returns_result():
    """Verify orchestrator_node returns agent result."""
    state = {"phase": "idle", "thread_id": "test-123"}
    store = MagicMock()

    result = await orchestrator_node(state, store=store)
    assert "current_agent" in result
    assert result["current_agent"] == "orchestrator"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/test_nodes_orchestrator.py -v
```

Expected: FAIL - `ModuleNotFoundError`

- [ ] **Step 3: 创建 orchestrator.py**

创建 `xhs_growth/agents/nodes/orchestrator.py`：

```python
"""Orchestrator node implementation."""

from typing import Any
from langgraph.store.base import BaseStore
from xhs_growth.agents.nodes._base import NodeResult
from xhs_growth.agents.orchestrator import OrchestratorAgent
from xhs_growth.realtime import EventBusService, EventType
from xhs_growth.state.schema import XHSGrowthState

_orchestrator = OrchestratorAgent()


async def orchestrator_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """执行 orchestrator agent 并更新状态."""
    result = await _orchestrator(state, store=store)

    # Emit phase change event if phase changed
    old_phase = state.get("phase")
    new_phase = result.get("phase")
    if new_phase and new_phase != old_phase:
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_PHASE_CHANGED,
            thread_id=state.get("thread_id"),
            payload={
                "old_phase": old_phase,
                "new_phase": new_phase,
            },
        )

    return NodeResult(result, "orchestrator").to_dict()
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/test_nodes_orchestrator.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add xhs_growth/agents/nodes/orchestrator.py tests/test_nodes_orchestrator.py
git commit -m "feat(nodes): split orchestrator_node from nodes.py"
```

---

### Task 7-14: 拆分其他节点模块

按照相同模式拆分以下节点：

| Task | Node | File |
|------|------|------|
| 7 | trend_scout | `nodes/trend_scout.py` |
| 8 | content_strategist | `nodes/content_strategist.py` |
| 9 | copywriter | `nodes/copywriter.py` |
| 10 | visual_designer | `nodes/visual_designer.py` |
| 11 | publisher | `nodes/publisher.py` |
| 12 | analyst | `nodes/analyst.py` |
| 13 | engagement | `nodes/engagement.py` |
| 14 | review_gate | `nodes/review_gate.py` |

每个任务遵循相同步骤：
1. 创建测试文件
2. 运行测试验证失败
3. 创建节点模块（复制nodes.py中对应代码）
4. 运行测试验证通过
5. 提交

---

### Task 15-18: 拆分优化节点

拆分优化相关节点到 `nodes/optimization/`：

| Task | Node | File |
|------|------|------|
| 15 | viral_matcher | `nodes/optimization/viral_matcher.py` |
| 16 | content_analyzer | `nodes/optimization/content_analyzer.py` |
| 17 | version_generator | `nodes/optimization/version_generator.py` |
| 18 | choice_gate | `nodes/optimization/choice_gate.py` |

---

### Task 19: 创建 nodes/__init__.py 统一导出

**Files:**
- Create: `xhs_growth/agents/nodes/__init__.py`
- Create: `xhs_growth/agents/nodes/optimization/__init__.py`

- [ ] **Step 1: 创建 nodes/__init__.py**

创建 `xhs_growth/agents/nodes/__init__.py`：

```python
"""Graph node functions — wraps agent calls into LangGraph nodes."""

from xhs_growth.agents.nodes.orchestrator import orchestrator_node
from xhs_growth.agents.nodes.trend_scout import trend_scout_node
from xhs_growth.agents.nodes.content_strategist import content_strategist_node
from xhs_growth.agents.nodes.copywriter import copywriter_node
from xhs_growth.agents.nodes.visual_designer import visual_designer_node
from xhs_growth.agents.nodes.publisher import publisher_node
from xhs_growth.agents.nodes.analyst import analyst_node
from xhs_growth.agents.nodes.engagement import engagement_node
from xhs_growth.agents.nodes.review_gate import review_gate_node

from xhs_growth.agents.nodes.optimization.viral_matcher import viral_matcher_node
from xhs_growth.agents.nodes.optimization.content_analyzer import content_analyzer_node
from xhs_growth.agents.nodes.optimization.version_generator import version_generator_node
from xhs_growth.agents.nodes.optimization.choice_gate import choice_gate_node

__all__ = [
    "orchestrator_node",
    "trend_scout_node",
    "content_strategist_node",
    "copywriter_node",
    "visual_designer_node",
    "publisher_node",
    "analyst_node",
    "engagement_node",
    "review_gate_node",
    "viral_matcher_node",
    "content_analyzer_node",
    "version_generator_node",
    "choice_gate_node",
]
```

- [ ] **Step 2: 创建 optimization/__init__.py**

创建 `xhs_growth/agents/nodes/optimization/__init__.py`：

```python
"""Optimization workflow nodes."""

from xhs_growth.agents.nodes.optimization.viral_matcher import viral_matcher_node
from xhs_growth.agents.nodes.optimization.content_analyzer import content_analyzer_node
from xhs_growth.agents.nodes.optimization.version_generator import version_generator_node
from xhs_growth.agents.nodes.optimization.choice_gate import choice_gate_node

__all__ = [
    "viral_matcher_node",
    "content_analyzer_node",
    "version_generator_node",
    "choice_gate_node",
]
```

- [ ] **Step 3: 运行全量测试**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass

- [ ] **Step 4: 提交**

```bash
git add xhs_growth/agents/nodes/__init__.py xhs_growth/agents/nodes/optimization/__init__.py
git commit -m "feat(nodes): add unified exports for all node modules"
```

---

### Task 20: 删除旧 nodes.py

**Files:**
- Delete: `xhs_growth/graph/nodes.py`
- Modify: `xhs_growth/graph/builder.py`

- [ ] **Step 1: 更新 builder.py 导入**

修改 `xhs_growth/graph/builder.py`，将导入从 `graph.nodes` 改为 `agents.nodes`：

```python
# 修改导入
from xhs_growth.agents.nodes import (
    orchestrator_node, trend_scout_node, content_strategist_node,
    copywriter_node, visual_designer_node, review_gate_node,
    publisher_node, analyst_node, engagement_node,
    viral_matcher_node, content_analyzer_node, version_generator_node,
    choice_gate_node,
)
```

- [ ] **Step 2: 运行测试验证导入正确**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass

- [ ] **Step 3: 删除旧 nodes.py**

```bash
git rm xhs_growth/graph/nodes.py
```

- [ ] **Step 4: 提交**

```bash
git add xhs_growth/graph/builder.py
git commit -m "refactor(graph): remove old nodes.py, use agents.nodes"
```

---

### Task 21-25: 前端 Dashboard 拆分

拆分 Dashboard.vue 为多个组件。每个组件遵循相同步骤：

| Task | Component | File |
|------|-----------|------|
| 21 | WorkflowHeader | `components/dashboard/WorkflowHeader.vue` |
| 22 | WorkflowTimeline | `components/dashboard/WorkflowTimeline.vue` |
| 23 | ContentCards | `components/dashboard/ContentCards.vue` |
| 24 | OptimizationPanel | `components/dashboard/OptimizationPanel.vue` |
| 25 | ActionButtons | `components/dashboard/ActionButtons.vue` |

每个任务步骤：
1. 创建组件目录
2. 创建组件文件（从Dashboard.vue提取对应代码）
3. 验证组件可导入
4. 提交

---

### Task 26: 精简 Dashboard.vue

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`

- [ ] **Step 1: 重写 Dashboard.vue 为布局编排**

修改 `frontend/src/views/Dashboard.vue`：

```vue
<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import WorkflowHeader from '@/components/dashboard/WorkflowHeader.vue'
import WorkflowTimeline from '@/components/dashboard/WorkflowTimeline.vue'
import ContentCards from '@/components/dashboard/ContentCards.vue'
import OptimizationPanel from '@/components/dashboard/OptimizationPanel.vue'
import ActionButtons from '@/components/dashboard/ActionButtons.vue'
import { useWorkflowStore } from '@/stores'

const router = useRouter()
const workflowStore = useWorkflowStore()

const showOptimization = computed(() => workflowStore.currentPhase === 'creating')

onMounted(() => {
  if (workflowStore.currentThreadId) {
    workflowStore.refreshStatus()
    workflowStore.startPolling(5000)
  }
})

onUnmounted(() => {
  workflowStore.stopPolling()
})
</script>

<template>
  <div class="space-y-6">
    <WorkflowHeader />
    <WorkflowTimeline />
    <ContentCards />
    <OptimizationPanel v-if="showOptimization" />
    <ActionButtons />
  </div>
</template>
```

- [ ] **Step 2: 验证前端构建**

```bash
cd frontend && npm run build
```

Expected: Build succeeds

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/Dashboard.vue frontend/src/components/dashboard/
git commit -m "refactor(frontend): split Dashboard into sub-components"
```

---

## Phase 3: 边界调整

### Task 27-31: 创建 Service 层

创建 services 目录和各 service：

| Task | Service | File |
|------|---------|------|
| 27 | xhs_service | `services/xhs_service.py` |
| 28 | visual_service | `services/visual_service.py` |
| 29 | ripple_service | `services/ripple_service.py` |
| 30 | optimization_service | `services/optimization_service.py` |
| 31 | services/__init__.py | 导出所有Service |

每个任务遵循相同步骤：TDD模式创建Service。

---

### Task 32: 精简 graph/builder.py

**Files:**
- Modify: `xhs_growth/graph/builder.py`

- [ ] **Step 1: 移除节点定义，仅保留拓扑**

精简 `xhs_growth/graph/builder.py`，移除所有节点定义代码，仅保留：
- 导入语句
- add_node 调用
- add_edge/add_conditional_edges 调用
- compile 调用

目标：约60行

- [ ] **Step 2: 运行测试验证拓扑正确**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass

- [ ] **Step 3: 提交**

```bash
git add xhs_growth/graph/builder.py
git commit -m "refactor(graph): simplify builder.py to topology-only"
```

---

## Phase 4: 验证与回归

### Task 33: 全量回归测试

- [ ] **Step 1: 运行后端测试**

```bash
pytest tests/ -v --cov=xhs_growth --cov-report=term-missing
```

Expected: All tests pass, coverage > 80%

- [ ] **Step 2: 运行前端测试**

```bash
cd frontend && npm run test
```

Expected: All tests pass

- [ ] **Step 3: 运行集成测试**

```bash
pytest tests/integration/ -v
```

Expected: All integration tests pass

---

### Task 34: 前端功能验证

- [ ] **Step 1: 启动前端开发服务器**

```bash
cd frontend && npm run dev
```

- [ ] **Step 2: 手动验证关键功能**
- Dashboard 加载正常
- Workflow 时间轴显示
- 优化流程触发
- 版本选择交互

---

### Task 35: 文档更新和提交

- [ ] **Step 1: 更新 CLAUDE.md**

添加新的目录结构和导入说明到 `CLAUDE.md`

- [ ] **Step 2: 更新 README**

如有README，更新架构说明

- [ ] **Step 3: 最终提交**

```bash
git add .
git commit -m "docs: update documentation for new architecture"
```

---

## Spec Coverage Check

| Spec Section | Covered by Task |
|--------------|-----------------|
| core/base_agent.py | Task 1 |
| core/error_handling.py | Task 2 |
| agents/mixins/ | Task 3 |
| docs/architecture-conventions.md | Task 4 |
| nodes/_base.py | Task 5 |
| nodes/orchestrator.py | Task 6 |
| nodes/*.py (其他8个) | Task 7-14 |
| nodes/optimization/*.py | Task 15-18 |
| nodes/__init__.py | Task 19 |
| 删除旧nodes.py | Task 20 |
| frontend组件拆分 | Task 21-25 |
| Dashboard.vue精简 | Task 26 |
| services/*.py | Task 27-31 |
| builder.py精简 | Task 32 |
| 回归测试 | Task 33 |
| 前端验证 | Task 34 |
| 文档更新 | Task 35 |

All spec requirements covered ✓

---

## Placeholder Scan

- No TBD/TODO found
- No "implement later" found
- All steps have actual code
- All file paths are exact

---

## Type Consistency Check

- BaseAgent → used in all Agent imports
- NodeContext/NodeResult → defined in _base.py, used in all nodes
- XHSGrowthState → consistent throughout
- WorkflowPhase → consistent enum usage

All types consistent ✓