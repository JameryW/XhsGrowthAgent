# Testing Guide

本文档说明 XHS Growth Agent 的测试策略和编写指南。

## 测试结构

```
tests/
  conftest.py           # 共享 fixtures
  contract/             # 合同测试（类型同步、OpenAPI验证）
  integration/          # 集成测试（API路由、完整工作流）
  unit/                 # 单元测试
    agents/             # Agent 测试
    api/                # API 测试
    config/             # 配置测试
    graph/              # Graph 测试
    memory/             # Memory 测试
    services/           # Service 测试
    state/              # State 测试
    tools/              # Tool 测试
```

---

## 运行测试

### 基本命令

```bash
# 所有测试
pytest tests/ -v

# 单元测试
pytest tests/unit/ -v

# 合同测试
pytest tests/contract/ -v

# 集成测试
pytest tests/integration/ -v

# 带覆盖率
pytest tests/ -v --cov=xhs_growth --cov-report=term-missing
```

### 单模块测试

```bash
# Agent 测试
pytest tests/unit/agents/ -v

# Services 测试
pytest tests/unit/services/ -v

# 特定文件
pytest tests/unit/agents/test_base_agent.py -v
```

---

## Test Fixtures

### conftest.py 共享 Fixtures

```python
@pytest.fixture
def mock_state():
    """标准 mock state"""
    return {
        "phase": WorkflowPhase.IDLE,
        "account_id": "test_account",
        "error": None,
        "retry_count": 0,
    }

@pytest.fixture
def mock_store():
    """Mock LangGraph BaseStore"""
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    return store

@pytest.fixture
def mock_llm():
    """Mock LLM response"""
    response = MagicMock()
    response.content = '{"result": "success"}'
    return response
```

---

## Mock Patterns

### Mock LLM 响应

```python
from unittest.mock import MagicMock, patch

def test_with_llm_mock():
    mock_response = MagicMock()
    mock_response.content = """```json
{"key": "value"}
```"""
    
    with patch("module.get_model") as mock_get_model:
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_model.return_value = mock_model
        
        # Execute test
        result = await agent.execute(state, store)
```

### Mock Memory Store

```python
def test_with_memory_mock():
    mock_store = AsyncMock()
    mock_item = MagicMock()
    mock_item.value = {"insight": "Test insight"}
    mock_store.asearch = AsyncMock(return_value=[mock_item])
    
    result = await agent._recall_memory(mock_store, "test", "query", "insights")
```

### Mock XHS Client

```python
def test_with_xhs_mock():
    mock_client = MagicMock()
    mock_client.get_trending = AsyncMock(return_value={"topics": []})
    
    with patch("module.XHSClient", return_value=mock_client):
        result = await tool.invoke({"keyword": "test"})
```

---

## 异步测试

使用 `pytest.mark.asyncio`:

```python
@pytest.mark.asyncio
async def test_async_execution():
    result = await agent.execute(state, store)
    assert result["phase"] == WorkflowPhase.SCOUTING
```

配置在 `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 测试模式

### Agent 测试模式

```python
class TestMyAgent:
    @pytest.fixture
    def agent(self):
        return MyAgent()
    
    @pytest.mark.asyncio
    async def test_execute_success(self, agent, mock_state, mock_store):
        """测试成功执行"""
        result = await agent.execute(mock_state, store=mock_store)
        assert "expected_key" in result
    
    @pytest.mark.asyncio
    async def test_execute_handles_error(self, agent, mock_state, mock_store):
        """测试错误处理"""
        with patch("module.get_model") as mock_model:
            mock_model.side_effect = Exception("LLM error")
            result = await agent(mock_state, store=mock_store)
            assert "error" in result
```

### Tool 测试模式

```python
@pytest.mark.asyncio
async def test_tool_llm_success():
    """LLM 成功返回"""
    with patch("tool.get_llm_service") as mock_service:
        mock_service.return_value.enrich_with_llm = AsyncMock(
            return_value={"items": [{"id": 1}]}
        )
        result = await my_tool.invoke({"param": "value"})
        assert len(result) == 1

@pytest.mark.asyncio
async def test_tool_fallback():
    """LLM 失败时降级"""
    with patch("tool.get_llm_service") as mock_service:
        mock_service.return_value.enrich_with_llm = AsyncMock(
            side_effect=Exception("Error")
        )
        result = await my_tool.invoke({"param": "value"})
        # Should return fallback data
        assert result is not None
```

---

## 覆盖率要求

| 模块 | 最低覆盖率 | 当前覆盖率 |
|------|------------|------------|
| `agents/` | 80% | ~55% |
| `services/` | 70% | ~43% |
| `graph/` | 70% | ~75% |
| `tools/` | 60% | ~29% |
| `state/` | 80% | ~50% |

---

## 边缘情况测试

### 必须测试的边缘情况

1. **空输入**: 空字符串、空列表、None 值
2. **无效 JSON**: LLM 返回无法解析的内容
3. **LLM 失败**: 超时、连接错误、rate limit
4. **Memory 失败**: 空搜索结果、存储失败
5. **并发**: 多个工作流实例同时运行

### 示例

```python
@pytest.mark.asyncio
async def test_empty_input(agent, mock_store):
    """空输入处理"""
    result = await agent.execute({"account_id": ""}, store=mock_store)
    assert result is not None  # 不应崩溃

@pytest.mark.asyncio
async def test_invalid_json(agent, mock_store):
    """无效 JSON 处理"""
    mock_response = MagicMock()
    mock_response.content = "Not valid JSON"
    
    with patch.object(agent, "model") as mock_model:
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        result = await agent.execute({}, store=mock_store)
        # 应返回 raw_content 或 fallback
        assert "raw_content" in result or result.get("error")
```

---

## 合同测试

### OpenAPI Spec 验证

```python
def test_openapi_spec_valid():
    """OpenAPI 规范有效"""
    spec = load_openapi_spec()
    assert spec["openapi"] == "3.1.0"
    assert "/api/workflow/start" in spec["paths"]
```

### 类型同步验证

```python
def test_types_sync():
    """前端类型与后端同步"""
    from xhs_growth.state.enums import WorkflowPhase
    from frontend.src.types.workflow import WorkflowPhaseType
    
    # 确保 enum 值一致
    for phase in WorkflowPhase:
        assert phase.value in frontend_phases
```