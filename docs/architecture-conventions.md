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
