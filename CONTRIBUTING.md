# Contributing to XHS Growth Agent

感谢你对 XHS Growth Agent 的贡献兴趣！本文档说明如何参与项目开发。

## 开发环境设置

### 1. 克隆仓库

```bash
git clone https://github.com/JameryW/XhsGrowthAgent.git
cd XhsGrowthAgent
```

### 2. 安装依赖

```bash
# Python 后端
pip install -e ".[dev,browser]"

# 前端
cd frontend
npm install
```

### 3. 配置环境变量

复制 `.env.example` 并填写必要的 API keys:

```bash
cp .env.example .env
```

必填项:
- `ANTHROPIC_API_KEY` - Claude 模型
- `OPENAI_API_KEY` - GPT 模型
- `DEEPSEEK_API_KEY` - DeepSeek 模型

## 代码风格

### Python

- 使用 **Ruff** 进行格式化和 linting
- 使用 **mypy** 进行类型检查
- 遵循 snake_case 命名约定

```bash
# 格式化
ruff format .

# Lint
ruff check .

# 类型检查
mypy xhs_growth
```

### TypeScript/Vue

- 使用 ESLint + Prettier
- Vue 组件使用 PascalCase
- TypeScript 文件使用 camelCase

```bash
cd frontend
npm run lint
npm run format
```

## 测试要求

### 运行测试

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

### 测试要求

- **新增 Agent**: 必须有单元测试 (`tests/unit/agents/`)
- **新增 Tool**: 必须有单元测试 (`tests/unit/tools/`)
- **API 变更**: 必须有集成测试 (`tests/integration/`)
- **类型变更**: 必须有合同测试 (`tests/contract/`)

## Pull Request 流程

### 1. 创建分支

```bash
git checkout main
git pull
git checkout -b feature/your-feature-name
```

### 2. 提交变更

遵循 Conventional Commits 格式:

- `feat:` 新功能
- `fix:` Bug 修复
- `refactor:` 重构
- `test:` 测试
- `docs:` 文档
- `chore:` 其他

```bash
git add .
git commit -m "feat: add new agent for XYZ"
```

### 3. 推送并创建 PR

```bash
git push -u origin feature/your-feature-name
gh pr create --title "feat: add new agent for XYZ" --body "..."
```

### 4. PR 检查清单

- [ ] 所有测试通过
- [ ] 类型检查通过 (`mypy xhs_growth`)
- [ ] Lint 通过 (`ruff check .`)
- [ ] 新功能有对应测试
- [ ] 文档已更新

## 添加新 Agent

参考现有 Agent 实现模式:

1. 创建 `xhs_growth/agents/<name>.py`，继承 `BaseAgent`
2. 添加 prompt YAML 到 `xhs_growth/config/prompts/<name>.yaml`
3. 在 `execute()` 内通过直接 submodule import 引入所需 tools（如 `from backend.tools.analysis.topic_scorer import topic_scorer`）；无中心注册表
4. 添加 node + edges 到 `xhs_growth/graph/builder.py`
5. 更新 `TaskType` enum (如需要)
6. 导出 Agent 类到 `xhs_growth/agents/__init__.py`
7. 创建单元测试 `tests/unit/agents/test_<name>.py`

## 添加新 Tool

参考现有 Tool 实现模式:

1. 创建 tool 文件在 `xhs_growth/tools/<category>/<name>.py`
2. 使用 `@tool` decorator 从 `langchain_core.tools`
3. 导出 tool 到 `xhs_growth/tools/<category>/__init__.py`
4. 由消费该 tool 的 agent 在 `execute()` 内直接 submodule import 引入（无中心注册表）；manual-only 操作员工具只需保持可 import、不被任何 workflow agent 引用
5. 创建单元测试 `tests/unit/tools/<category>/test_<name>.py`

## 问题反馈

使用 GitHub Issues 报告问题:
- Bug 报告: 包含复现步骤、预期行为、实际行为
- 功能请求: 说明需求和预期用途

## 代码审查

所有 PR 需要至少一位 maintainer 审查批准后才能合并。
