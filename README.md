# XHS Growth Agent

小红书增长引擎 — Multi-agent system for automating content growth on Xiaohongshu (Little Red Book).

[English](#overview) | [中文说明](#中文说明)

---

## Overview

XHS Growth Agent is a LangGraph-based multi-agent workflow that automates the complete content lifecycle on Xiaohongshu:

```
Trend Scouting → Content Strategy → Copywriting → Visual Design → Human Review → Publishing → Analytics → Engagement
```

**Key Features:**
- 🔍 **Trend Scout**: Monitors hot topics, keywords, and competitor posts
- 📋 **Content Strategist**: Plans content angles, timing, and target audience (with Ripple CAS prediction)
- ✍️ **Copywriter**: Generates titles, body text, hashtags, and CTAs
- 🎨 **Visual Designer**: Creates cover image prompts and layout recommendations
- ✅ **Human Review Gate**: Interrupts for manual approval before publishing
- 📤 **Publisher**: Posts content with A/B testing and scheduling
- 📊 **Analyst**: Analyzes performance metrics and generates insights
- 💬 **Engagement**: Handles comments and DMs automatically

---

## Installation

```bash
# Clone the repository
git clone https://github.com/your-org/xhs-growth-agent.git
cd xhs-growth-agent

# Install dependencies
pip install -e ".[dev,browser]"

# For browser automation (optional)
playwright install
```

---

## Quick Start

### CLI Usage

```bash
# Run the workflow (dry-run mode)
xhs-growth run --dry-run

# Run with specific account
xhs-growth run --account-id my_account --phase scouting

# Start API server
xhs-growth serve --port 8000

# Check workflow status
xhs-growth status <thread_id>
```

### API Usage

```python
from xhs_growth import compile_graph_dev, XHSGrowthState

# Compile the graph
graph = compile_graph_dev()

# Initialize state
initial_state = {
    "phase": "scouting",
    "account_id": "my_account",
    ...
}

# Run the workflow
result = await graph.ainvoke(initial_state, {"configurable": {"thread_id": "xxx"}})
```

---

## Configuration

### Environment Variables

| Variable | Description | 中文说明 | Required |
|----------|-------------|---------|----------|
| `ANTHROPIC_API_KEY` | Anthropic API key | Anthropic API密钥 | Yes* |
| `OPENAI_API_KEY` | OpenAI API key | OpenAI API密钥 | Yes* |
| `DEEPSEEK_API_KEY` | DeepSeek API key | DeepSeek API密钥 | Yes* |
| `DASHSCOPE_API_KEY` | Alibaba Qwen API key | 通义千问API密钥 | Yes* |
| `XHS_COOKIE` | XHS session cookie | 小红书登录Cookie | Yes |
| `XHS_USER_ID` | XHS user ID | 小红书用户ID | Yes |
| `RIPPLE_BASE_URL` | Ripple CAS engine URL | Ripple引擎地址 | No |
| `RIPPLE_API_TOKEN` | Ripple API token | Ripple API令牌 | No |
| `POSTGRES_URI` | PostgreSQL connection | PostgreSQL连接串 | Prod only |
| `REDIS_URI` | Redis connection | Redis连接串 | Prod only |

*At least one LLM provider API key required.

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

---

## Architecture

### Workflow Graph

The system is built as a LangGraph `StateGraph` with conditional routing:

```
START → orchestrator → [trend_scout | content_strategist | analyst | engagement | END]
              ↓
        trend_scout → [content_strategist | END]
              ↓
        content_strategist → copywriter → visual_designer → review_gate
              ↓                                           ↓
        review_gate → [publisher | revise_content → copywriter]
              ↓
        publisher → analyst → [orchestrator | END]
              ↓
        engagement → orchestrator
```

关键节点 (Key Nodes):
- `orchestrator`: 编排器，决定下一步阶段
- `review_gate`: 人工审核门，支持 human-in-the-loop

### Model Routing

不同任务类型路由到不同 LLM:

| TaskType | Model | 中文说明 |
|----------|-------|---------|
| `routing` | DeepSeek | 编排路由 |
| `scouting` | DeepSeek | 趋势侦察 |
| `strategy` | Claude Sonnet 4 | 内容策略 |
| `writing` | Claude Sonnet 4 | 文案创作 |
| `visual` | GPT-4o | 视觉设计 |
| `analysis` | GPT-4o | 数据分析 |
| `publishing` | Qwen Plus | 发布执行 |
| `engagement` | DeepSeek | 用户互动 |

### Tool Registry

每个 Agent 有专属工具集:

| Agent | Tools | 中文说明 |
|-------|-------|---------|
| `trend_scout` | xhs_trending, keyword_monitor, competitor_analyzer | 趋势工具 |
| `content_strategist` | topic_scorer, timing_optimizer, ripple_predict | 策略工具 |
| `copywriter` | hashtag_researcher, title_generator | 文案工具 |
| `visual_designer` | image_prompt_generator, layout_recommender | 设计工具 |
| `analyst` | analytics_reader, pattern_detector, report_generator | 分析工具 |
| `publisher` | xhs_publisher, ab_test_manager, post_scheduler | 发布工具 |
| `engagement` | comment_replier, dm_handler | 互动工具 |

---

## Frontend Web UI

Vue 3 前端界面，赛博朋克风格，包含三大模块：

### Pages

| 页面 | 路径 | 功能 |
|------|------|------|
| Dashboard | `/dashboard` | 工作流进度追踪、阶段输出展示 |
| Review | `/review` | 人机审核、内容预览、通过/修改/拒绝 |
| Analytics | `/analytics` | 数据统计、帖子表现、成本分析 |

### Tech Stack

- Vue 3.4 + Vite 5.0
- Tailwind CSS 3.4 (赛博朋克主题)
- Element Plus 2.5
- Pinia 2.1 状态管理
- axios 1.6 API 客户端

### Development

```bash
# 前端开发
cd frontend
npm install
npm run dev  # http://localhost:3000

# 构建
npm run build  # 生成 dist/

# 后端托管
xhs-growth serve --port 8000  # http://localhost:8000 同时托管前端
```

### Cyberpunk Design

- 暗色渐变背景 (`#0a0a0a → #1a0a2e`)
- 霓虹配色 (pink/cyan/purple)
- 六边形流程节点
- 毛玻璃卡片 (Glass-morphism)
- 发光按钮和图标
- Monospace 终端字体

---

## 中文说明

### 项目简介

小红书增长引擎是一个基于 LangGraph 的多智能体系统，自动化小红书内容的全流程：

- **趋势侦察**: 监控热门话题、关键词和竞品动态
- **内容策划**: 制定内容角度、发布时间和目标受众
- **文案创作**: 生成标题、正文、标签和行动号召
- **视觉设计**: 设计封面图和排版方案
- **人工审核**: 支持发布前人工确认
- **自动发布**: 发布内容并支持A/B测试
- **数据分析**: 分析内容表现并生成优化建议
- **用户互动**: 自动回复评论和私信

### 开发命令

```bash
# 运行测试
pytest

# 运行单个测试
pytest tests/test_graph.py -v

# 代码格式化
ruff format .

# 代码检查
ruff check .

# 类型检查
mypy xhs_growth
```

---

## Development

See [CLAUDE.md](./CLAUDE.md) for detailed development guidelines.

### Adding a New Agent

1. Create `agents/<name>.py` extending `BaseAgent`
2. Add prompt YAML to `config/prompts/<name>.yaml`
3. Register tools in `tools/registry.py`
4. Add node + edges in `graph/builder.py`

### Adding a New Tool

1. Create tool file in `tools/<category>/<name>.py`
2. Use `@tool` decorator from `langchain_core.tools`
3. Register in `ToolRegistry.register()`
4. Add to agent's tool list in `_agent_tools`

---

## License

MIT License - See [LICENSE](./LICENSE) for details.