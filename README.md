# XHS Growth Agent

小红书增长引擎 — Multi-agent system for automating content growth on Xiaohongshu (Little Red Book).

[English](#overview) | [中文说明](#中文说明)

---

## Overview

XHS Growth Agent is a LangGraph-based multi-agent workflow that automates the complete content lifecycle on Xiaohongshu:

🌐 **Demo**: [https://xhs.jameryw.dev](https://xhs.jameryw.dev)

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
| `RIPPLE_BASE_URL` | Ripple CAS engine URL | Ripple引擎地址 | No |
| `RIPPLE_API_TOKEN` | Ripple API token | Ripple API令牌 | No |
| `POSTGRES_URI` | PostgreSQL connection | PostgreSQL连接串 | Prod only |
| `REDIS_URI` | Redis connection | Redis连接串 | Prod only |

*At least one LLM provider API key required.

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Ripple CAS Engine

> **重要：本项目依赖 Ripple CAS 引擎的 fork 版本（[JameryW/Ripple](https://github.com/JameryW/Ripple)），不是上游原版。**

Fork 版本相比上游新增了：
- `providers/` 模块：HistoricalProvider、TopologyProvider 等数据源抽象
- `provider_insights` 顶层输出字段（向后兼容）
- Per-phase timeout 机制（`RIPPLE_PHASE_TIMEOUT_*` 环境变量）
- `job.timed_out` 事件类型

Ripple 提供以下 API：
- 健康检查（`GET /healthz`，无需认证）
- 心跳（`GET /v1/ping`）
- 模拟任务提交（`POST /v1/simulations`）
- 模拟状态查询（`GET /v1/simulations/{job_id}`）
- 紧凑日志获取（`GET /v1/simulations/{job_id}/artifacts/compact-log`）
- 模拟结果获取（`GET /v1/simulations/{job_id}/artifacts/output-json`）
- 报告生成（`POST /v1/simulations/{job_id}/report`）
- 事件流（`GET /v1/simulations/{job_id}/events`）
- 取消请求（`POST /v1/simulations/{job_id}/cancel-request`）
- 取消确认（`POST /v1/simulations/{job_id}/cancel-confirm`）

**启动 Ripple 服务（必须本地构建，fork 版本无预构建镜像）：**

```bash
git clone https://github.com/JameryW/Ripple.git
cd Ripple
podman build -t ripple-service:local -f deploy/docker/Dockerfile .
podman run -d --name ripple-service \
  -p 127.0.0.1:8080:8080 \
  -e RIPPLE_API_TOKEN=your_token \
  localhost/ripple-service:local

# 配置环境变量
RIPPLE_BASE_URL=http://127.0.0.1:8080
RIPPLE_API_TOKEN=your_token
RIPPLE_ENABLED=true
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

Vue 3 前端界面，赛博朋克风格，围绕创作、审核、增长和账号管理组织工作区：

### Pages and interaction paths

| 页面 | 路径 | 功能 |
|------|------|------|
| Start Creating | `/start` | 首屏欢迎 Hero、当前账号上下文、三步创作 cue，以及趋势/Brief/自由创作模式入口 |
| Dashboard | `/dashboard/:threadId?` | 状态感知 Hero、进度和唯一下一步行动；支持阶段输出与深链恢复 |
| Review | `/review/:threadId?` | 人机审核、内容预览、通过/修改/拒绝，展开卡片后固定操作栏 |
| Analytics | `/analytics` | 按当前账号和周期查看数据、帖子表现、成本分析 |
| Evaluation | `/evaluation` | 创作者质量与工作流评估，移动端从“更多”进入 |
| History | `/history` | 工作流恢复、查看和回放 |
| Settings | `/settings` | 控制台用户、小红书账号和系统配置；窄屏使用横向标签 |
| Help Center | `/help` | FAQ、快捷键面板和反馈报告 |
| Free Creation TUI | `/tui?mode=free` | 登录后进入终端式自由创作；保留命令行，同时提供建议/草稿/帮助快捷操作 |

前端交互约定、导航层级、连接状态、错误恢复、响应式和无障碍规则见 [docs/frontend-ux-optimization.md](./docs/frontend-ux-optimization.md)。

开始创作页会先展示“配置 → 确认 → 创作”的任务路径和当前账号，再进入模式配置；工作台首屏根据空闲、运行中、等待输入/审核、已完成或错误状态切换主标题、进度摘要和行动入口，减少用户扫描时间。

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

# 类型检查与前端回归测试
npm run type-check
npm run test:run

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

### Latency Instrumentation

HTTP request + LLM call latency is env-gated and off by default (zero overhead when unset). Enable it to discover bottlenecks with prod data:

```bash
# 1. Enable on the backend container (restart required — gate is read once at import)
XHS_LATENCY_LOG=1

# 2. Drive traffic to an instrumented endpoint (/status /list /account-totals /evaluation/result),
#    then aggregate:
python scripts/collect_latency.py                 # live tail of backend-xhs
python scripts/collect_latency.py --since 1h      # last hour
python scripts/collect_latency.py --file logs.txt # a saved log file
```

Each sampled request emits one JSON line to the `xhs_growth.api.latency` logger:

```json
{"event":"http_latency","endpoint":"/status","thread_id":"...","phase":"completed",
 "total_ms":12.3,"aget_state_ms":4.1,"db_ms":1.2,"serialize_ms":3.0}
```

`/status` is sampled 1-in-10 (the 5s poller); other endpoints log every call. The aggregate script reports per-endpoint p50/p95/avg + per-segment p50 (aget_state / db / count / serialize) and a phase breakdown. LLM call timing (`ainvoke_ms` / `parse_ms`) is recorded onto the existing `performance_log` `kind:"llm"` entries.

---

## oh-my-pi (omp) Extension

Terminal-based AI coding agent integration via [oh-my-pi](https://github.com/can1357/oh-my-pi). Enables XHS content creation workflows from the terminal.

### Setup

```bash
cd backend/omp/extensions/xhsagent-ext
npm install

# Configure API endpoint (defaults to http://localhost:8000)
export XHS_AGENT_API_BASE=http://localhost:8000

# Make sure the API server is running
xhs-growth serve --port 8000
```

### Available Tools

| Tool | Description |
|------|-------------|
| `xhs_workflow_start` | Start a workflow with SSE real-time progress |
| `xhs_workflow_status` | Query workflow status with full snapshot |
| `xhs_workflow_pause` | Pause a running workflow |
| `xhs_workflow_resume` | Resume a paused workflow |
| `xhs_workflow_cancel` | Cancel a workflow |
| `xhs_review_approve` | Approve content in review gate |
| `xhs_review_reject` | Reject content with revision feedback |

### Commands

- `/xhs [topic]` — Start a XHS content creation workflow
- `/xhs-review` — Review pending content

---

## Visual Design Tools Enhancement

The visual design tools have been enhanced with a data-driven architecture that analyzes real XHS post patterns to generate intelligent recommendations.

### Architecture Overview

```
XHS Platform Data
       ↓
VisualDataExtractor (AI-powered analysis)
       ↓
SceneDatabase (pattern storage with expiry)
       ↓
VisualAnalysisService (recommendation engine)
       ↓
layout_recommender / style_library (LangChain tools)
```

### Key Components

| Component | Purpose | File |
|-----------|---------|------|
| `VisualDataExtractor` | AI-powered visual pattern extraction from posts | `tools/visual/extractor.py` |
| `SceneDatabase` | Scene-based pattern storage with 7-day expiry | `tools/visual/database.py` |
| `VisualAnalysisService` | Distribution analysis & recommendation generation | `tools/visual/service.py` |
| `VisualTypes` | TypedDict models for all visual data structures | `tools/visual/types.py` |

### Supported Scenes

- `food` — Food photography and recipes
- `travel` — Travel destinations and experiences
- `fashion` — Fashion and outfit inspiration
- `beauty` — Beauty and skincare products
- `lifestyle` — Lifestyle and daily life content
- `fitness` — Fitness and workout content
- `home_decor` — Home decoration and interior design

### Recommendation Features

**Layout Recommendations:**
- Content type filtering (single_image, carousel, video_cover)
- Image count requirements (minimum/maximum)
- Style compatibility matching
- Popularity scoring based on analyzed posts

**Style Recommendations:**
- Color palette extraction (primary, secondary, accent colors)
- Category filtering (minimalist, vibrant, warm, cool, editorial)
- Trending style boosting
- Pro/cons analysis for each style

### Data Structures

```python
# Layout Option
LayoutOption(
    name="三图拼接",
    description="Three images arranged horizontally",
    pros=["视觉冲击力强", "信息量大"],
    cons=["需要三张高质量图片"],
    suitable_content_types=["carousel"],
    min_images=3, max_images=3,
    style_compatibility=["modern", "minimalist"],
    popularity_score=0.85
)

# Style Option
StyleOption(
    name="清新简约",
    description="Clean and minimalist aesthetic",
    color_palette=ColorPalette(
        primary="#F5F5F5",
        secondary="#333333",
        accent="#FF6B6B"
    ),
    pros=["干净利落", "易于模仿"],
    cons=["可能显得单调"],
    suitable_content_types=["single_image", "carousel"],
    trending_score=0.92
)
```

---

## License

MIT License - See [LICENSE](./LICENSE) for details.
