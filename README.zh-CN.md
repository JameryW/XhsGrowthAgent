# 小红书增长引擎

面向小红书（Xiaohongshu / RedNote）的 AI 内容运营工作台，基于 LangGraph 多智能体工作流构建，并在发布前保留人工审核边界。

[English](./README.md) | [简体中文](./README.zh-CN.md)

[![在线展示](https://img.shields.io/badge/在线展示-ff4f7b)](https://xhs.jameryw.dev/)
[![License](https://img.shields.io/badge/license-MIT-22c55e)](./LICENSE)

> 从趋势发现到可审核、可发布的笔记产出，让证据、决策和中间结果都保持可见。

## 项目定位

小红书增长引擎把增长目标或创作 Brief 转化为可重复执行的内容工作流，将调研、定位、文案、视觉、质量检查、发布、数据分析和互动连接在一次可恢复的运行中，而不是分散在多个提示词和工具里。

适合需要以下能力的创作者、运营人员和团队：

- 将热点或 Brief 转化为清晰的选题角度；
- 产出完整笔记包：标题、正文、标签和视觉方向；
- 在任何内容发布前保留人工确认；
- 按账号查看历史工作流和表现；
- 通过 Web UI、CLI、API 或终端扩展使用同一套工作流。

## 在线产品展示

线上部署提供两个无需登录即可查看的只读页面：

- [打开公开案例展示](https://xhs.jameryw.dev/)：浏览已授权的案例和最终产出。
- [打开示例工作流回放](https://xhs.jameryw.dev/replay/case_c35a6559d23fd17cd832?from=%2F)：按步骤查看从趋势发现到内容审核的证据链。

“开始创作”会进入需要登录的工作区。公开页面用于了解产品和示例结果；创建、运行、审核或发布自己的工作流需要登录并配置凭据。

### 产品导览总览

<p align="center">
  <img src="docs/assets/readme/product-tour-overview.png" alt="四宫格小红书增长引擎产品导览，覆盖公开案例、工作流回放、开始创作和数据分析" width="100%">
</p>

| 区域 | 线上入口 | 访问要求 | 展示内容 |
| --- | --- | --- | --- |
| 公开案例展示 | [`/`](https://xhs.jameryw.dev/) | 无需登录 | 浏览已授权案例并查看最终产出。 |
| 工作流回放 | [`/replay/:caseId`](https://xhs.jameryw.dev/replay/case_c35a6559d23fd17cd832?from=%2F) | 无需登录 | 按步骤查看从趋势发现到内容审核的证据链。 |
| 开始创作 | `/start` | 需要登录 | 选择创作路径、账号和目标，再进入对应工作区。 |
| 数据分析 | `/analytics` | 需要登录 | 切换账号范围、筛选时间窗口并查看增长洞察。 |

先看总览图，再通过下面的功能区块了解各个页面。每张图片都保留完整界面区域并标出清晰边界，打开 README 时可以直接读懂。

### 案例展示首页

<p align="center">
  <img src="docs/assets/readme/live-home.png" alt="带完整边界的小红书增长引擎公开案例展示主视觉区块" width="100%">
</p>

*截图于 2026-08-12 的线上公开部署。图片保留完整的 Showcase 主视觉区块，并移除了半截卡片和页面滚动延续内容。*

### 工作流回放

<p align="center">
  <img src="docs/assets/readme/live-replay.png" alt="带完整边界的小红书增长引擎工作流回放介绍区块" width="100%">
</p>

*回放保留关键决策和生成结果；图片停在完整的阶段导航区块。*

线上公开案例当前展示了：

1. 趋势发现与受众洞察；
2. 策略规划与选题定位；
3. 内容创作，包括标题、长正文和视觉方向；
4. 内容审核，包括关键要点、标签、图片数量和配色方案。

### 登录后工作区功能区块截图

登录后的工作区在公开案例查看器之上增加了按账号隔离的创作与增长运营能力。以下功能区块截图来自 2026-08-12 的线上部署；账号名称、指标数值以及帖子/话题文本均已主动遮盖。每张图片都由完整界面区块构成，不再使用容易产生残缺的长页面滚动截图。

<p align="center">
  <img src="docs/assets/readme/authenticated-create.png" alt="带完整边界的已脱敏登录后开始创作区块，展示三种创作模式和快速入口" width="100%">
</p>

*开始创作：选择趋势发现、商单 Brief 或自由创作。选择自由创作后，会先出现目标填写区，再进入 Agent 工作区。*

<p align="center">
  <img src="docs/assets/readme/authenticated-analytics.png" alt="带完整边界的已脱敏登录后数据分析区块，展示账号范围、时间筛选、指标卡和增长洞察" width="100%">
</p>

*数据分析：切换账号范围、选择时间窗口、查看指标卡和增长洞察，并继续查看话题、图表、帖子明细和 CSV 导出。*

### 自由创作路径

自由创作现在会先完成一次清晰的引导，再进入对话工作区：

1. 在“开始创作”中选择目标小红书账号；
2. 输入创作目标、粗略想法或已有草稿，也可以直接套用示例提示；
3. 进入自由创作工作区后，目标会预填到可编辑输入框中，用户确认发送前不会触发智能体；
4. 继续通过对话、`/drafts`、`/evaluate`、`/analytics`、修改和发布完成按账号隔离的创作闭环。

目标和账号会一起带入工作区，因此自由模式生成的草稿和后续洞察会归属于用户刚刚选择的创作者账号。

发布后，`/analytics <id>` 会把互动快照保存到草稿上，最新浏览/点赞/收藏在 `/draft <id>` 和历史页的“自由草稿”标签页中随时可见，无需重新从小红书拉取。多次采集会形成最近 10 次的趋势序列；草稿详情与历史徽标都会显示浏览量较上次的变化。

### 登录后工作区导览

登录后，工作区按账号隔离，覆盖创作、审核、数据分析和账号运营：

| 页面 | 可以做什么 |
| --- | --- |
| 开始创作 | 选择趋势发现、商单 Brief 或自由创作；选择账号；自由创作还会把可编辑目标带入 Agent 工作区。 |
| 工作流仪表盘 | 跟踪实时工作流、查看阶段输出、恢复下一步行动，并继续中断运行。 |
| 内容审核 | 对比生成的笔记包，提交通过/拒绝/修改意见，并明确保留发布边界。 |
| 数据分析 | 切换账号，选择近 24 小时/7 天/30 天，查看指标卡、增长洞察、热门话题、图表、帖子明细和 CSV 导出。 |
| 质量评估 | 查看发布后表现、RQGM 内容评审趋势、样本可信度、质量维度和已评估工作流。 |
| 工作流历史 | 按账号浏览历史工作流，在账号间切换而不改变当前工作区，并恢复或回放历史运行。 |
| 设置 | 管理管控台用户、小红书账号、扫码/浏览器登录态、创作者中心数据绑定、模型/Ripple/向量配置和公开页体验监控。 |
| 帮助中心 | 查看 FAQ、打开键盘快捷键并提交产品反馈。 |

以上能力清单来自 2026-08-12 对登录后工作区的实际查看。账号名称、真实指标、帖子文本和工作流记录会随部署变化，因此不会提交到仓库；仓库保留公开 Showcase/Replay 截图和已脱敏的工作区功能区块作为可分享证据。

### 从输入到产出

启用相应集成后，一次运行会沿着以下路径，从输入经过工作区步骤，留下可检查的产出：

| 输入或信号 | 工作区步骤 | 可以检查的产出 |
| --- | --- | --- |
| 自由创作目标 | 开始创作 → Agent 工作区 | 可编辑输入框、选中账号和明确的发送决策 |
| 热点或增长 Brief | 开始创作 | 账号、主题、垂类和启动就绪状态 |
| 调研信号 | 趋势侦察 + 内容策略 | 证据、受众洞察、定位和发布时间判断 |
| 创作方向 | 文案创作 + 视觉设计 | 标题、正文、标签、CTA 和视觉方案 |
| 人工决策 | 内容审核 | 发布前的通过、拒绝或修改意见 |
| 已通过的笔记包 | 质量评估 + 内容发布 | 质量结果、发布请求，以及可选的实验/定时发布扩展点 |
| 发布后反馈 | 数据分析 + 用户互动 | 指标、话题模式、帖子明细和下一轮创作信号 |

## 产品能力

| 能力 | 作用 | 主要入口 |
| --- | --- | --- |
| 趋势侦察 | 发现热点、关键词、受众信号和竞品内容模式。 | Trend Scout、公开回放 |
| 内容策略 | 将热点或 Brief 转化为选题角度、受众、时机和增长假设。 | Content Strategist、Dashboard |
| 文案创作 | 生成标题、正文、标签、CTA 和修订版本。 | Copywriter、Review |
| 视觉设计 | 根据小红书内容模式推荐封面概念、布局、配色、风格和图片提示词。 | Visual Designer、Review |
| 人工审核 | 在审核门暂停，由人工通过、拒绝或提出修改意见。 | Review 工作台 |
| 质量评估 | 人工通过后增加 AI 质量检查，将不合格草稿路由回修订流程。 | Evaluation、工作流图 |
| 内容发布 | 对接小红书发布器，并提供 A/B 版本和定时发布扩展点。 | Publisher 工具、API |
| 数据分析 | 读取表现、成本、互动和内容模式，为下一轮创作提供依据。 | Analytics、Analyst |
| 用户互动 | 通过选定账号会话支持评论回复和私信流程。 | Engagement 工具 |
| 账号运营 | 将账号上下文、浏览器会话和历史记录隔离到对应创作者账号。 | Settings、账号控制 |

### 端到端流程

```text
热点 / Brief
    ↓
趋势侦察 → 内容策略 → 文案创作 + 视觉设计
                         ↓
                    人工审核门
                         ↓
                    AI 质量评估
                    ↙          ↘
                 修订          发布
                               ↓
                       数据分析 + 用户互动
```

工作流支持恢复，并会暴露状态、中间结果、审核决策和性能日志。审核门是明确的产品边界：智能体可以准备和评估内容，但发布动作仍然可见、可控。

## Web 工作区

Vue 3 前端围绕创作、审核、增长和账号运营组织：

| 页面 | 路径 | 作用 |
| --- | --- | --- |
| 公开案例展示 | `/` | 无需登录查看公开案例和最终产出。 |
| 公开工作流回放 | `/replay/:caseId` | 回放公开案例的关键决策和证据。 |
| 开始创作 | `/start` | 选择趋势发现、商单 Brief 或自由创作，配置账号/主题/垂类，或把自由创作目标带入 Agent 工作区。需要登录。 |
| 工作台 | `/dashboard/:threadId?` | 查看实时状态、进度、阶段输出、恢复信息和下一步行动。 |
| 内容审核 | `/review/:threadId?` | 发布前预览、通过、拒绝或修改内容。 |
| 数据分析 | `/analytics` | 查看账号指标、时间范围、增长洞察、热门话题、图表、帖子明细和 CSV 导出。 |
| 质量评估 | `/evaluation` | 查看发布后表现、RQGM 评审趋势、样本可信度和工作流质量结果。 |
| 历史记录 | `/history` | 切换账号范围，恢复、查看和回放历史工作流。 |
| 设置 | `/settings` | 管理管控台用户、小红书账号/登录态、创作者中心数据、系统配置和公开页监控。 |
| 帮助中心 | `/help` | 查看 FAQ、键盘快捷键、引导和反馈入口。 |
| 自由创作 TUI | `/tui?mode=free` | 使用带草稿和帮助快捷操作的终端式创作工作区。 |

公开案例展示和回放是安全的浏览入口；私有工作区、账号会话、模型密钥和发布操作仍由登录与本地配置保护。

## 技术架构

### 运行时

- **后端：** Python 3.11+、FastAPI、LangGraph、Pydantic、Typer、Uvicorn
- **前端：** Vue 3、Vite、Pinia、Vue Router、Tailwind CSS、ECharts、xterm.js
- **持久化：** 开发环境使用 SQLite/内存检查点，生产环境使用 PostgreSQL 和 Redis
- **浏览器自动化：** Playwright，支持按账号隔离浏览器/CDP 会话
- **可选预测引擎：** Ripple CAS，通过 HTTP 集成

### Agent 与工具层

| Agent | 代表性工具 | 产出 |
| --- | --- | --- |
| `trend_scout` | `xhs_trending`、`keyword_monitor`、`competitor_analyzer` | 趋势和受众信号 |
| `content_strategist` | `topic_scorer`、`timing_optimizer`、`ripple_predict` | 角度、时机和定位 |
| `copywriter` | `hashtag_researcher`、`title_generator` | 笔记文案和版本 |
| `visual_designer` | `image_prompt_generator`、`layout_recommender` | 封面和视觉方案 |
| `review_gate` | Human-in-the-loop interrupt | 审核或修改意见 |
| `publisher` | `xhs_publisher`、`ab_test_manager`、`post_scheduler` | 发布请求和实验设置 |
| `analyst` | `analytics_reader`、`pattern_detector`、`report_generator` | 表现洞察 |
| `engagement` | `comment_replier`、`dm_handler` | 账号互动动作 |

### 模型路由

系统按任务类型选择更适合的模型，具体提供商由环境变量配置，无需修改工作流即可调整：

| 任务 | 项目默认路由 |
| --- | --- |
| 路由与趋势侦察 | DeepSeek |
| 策略与文案 | Claude Sonnet 4 |
| 视觉规划与分析 | GPT-4o |
| 发布 | Qwen Plus |
| 用户互动 | DeepSeek |

## 安装

```bash
git clone https://github.com/JameryW/XhsGrowthAgent.git
cd XhsGrowthAgent

pip install -e ".[dev,browser]"
playwright install
```

复制环境变量示例，并至少配置一个 LLM 提供商密钥：

```bash
cp .env.example .env
```

### 主要配置

| 变量 | 用途 | 要求 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic 模型 | 至少配置一个模型提供商 |
| `OPENAI_API_KEY` | OpenAI 模型 | 至少配置一个模型提供商 |
| `DEEPSEEK_API_KEY` | DeepSeek 路由和趋势侦察 | 可选，若改用其他路由 |
| `DASHSCOPE_API_KEY` | Alibaba/Qwen 发布路由 | 可选，若改用其他路由 |
| `RIPPLE_BASE_URL` | Ripple CAS 服务地址 | 可选 |
| `RIPPLE_API_TOKEN` | Ripple CAS 令牌 | 可选 |
| `POSTGRES_URI` | 生产检查点/数据库连接 | 生产环境 |
| `REDIS_URI` | 生产缓存和协同 | 生产环境 |

完整环境变量见 [docs/configuration.md](./docs/configuration.md)，密钥和账号会话安全见 [docs/security.md](./docs/security.md)。

## 快速开始

### 使用 CLI 运行工作流

```bash
# 不调用外部 API，验证工作流
xhs-growth run --dry-run

# 指定账号和起始阶段
xhs-growth run --account-id my_account --phase scouting

# 查看工作流并恢复中断运行
xhs-growth status <thread_id>
xhs-growth resume <thread_id>
```

### 启动 Web/API 服务

```bash
xhs-growth serve --port 8000
```

前端开发：

```bash
cd frontend
npm install
npm run dev

# 生产构建和检查
npm run build
npm run type-check
npm run test:run
npm run i18n:check
```

### Python API

```python
from backend.graph.builder import compile_graph_dev

graph = await compile_graph_dev()
config = {"configurable": {"thread_id": "demo-thread"}}

result = await graph.ainvoke(
    {"phase": "scouting", "account_id": "my_account"},
    config,
)
```

HTTP 接口、请求/响应示例、审核提交、数据分析和健康检查见 [docs/api-reference.md](./docs/api-reference.md)。

## Ripple CAS 集成

项目通过 fork 版本 [JameryW/Ripple](https://github.com/JameryW/Ripple) 获取内容预测信号。该 fork 增加了 provider 抽象、顶层 `provider_insights`、分阶段超时和项目使用的 `job.timed_out` 事件。

支持健康检查与 ping、模拟任务提交/查询、紧凑日志、JSON 输出、报告、事件流和取消操作：

```bash
git clone https://github.com/JameryW/Ripple.git
cd Ripple
podman build -t ripple-service:local -f deploy/docker/Dockerfile .
podman run -d --name ripple-service \
  -p 127.0.0.1:8080:8080 \
  -e RIPPLE_API_TOKEN=your_token \
  localhost/ripple-service:local

RIPPLE_BASE_URL=http://127.0.0.1:8080
RIPPLE_API_TOKEN=your_token
RIPPLE_ENABLED=true
```

## oh-my-pi 扩展

可选的 [oh-my-pi](https://github.com/can1357/oh-my-pi) 扩展可以在终端 Agent 中使用同一套工作流：

```bash
cd backend/omp/extensions/xhsagent-ext
npm install
export XHS_AGENT_API_BASE=http://localhost:8000
```

使用 `/xhs [topic]` 开始创作，使用 `/xhs-review` 审核待处理内容；扩展还提供开始、查询、暂停、恢复、取消、通过和拒绝工具。

## 视觉推荐引擎

视觉层使用数据驱动的推荐引擎：从小红书帖子中提取模式，按场景保存并过期，再依据内容类型、兼容性、热度、配色和趋势分数推荐布局与风格。

支持美食、旅行、穿搭、美妆、生活方式、健身和家居等场景，相关模型位于 `backend/tools/visual/`，由视觉设计工作流调用。

## 测试与开发

```bash
# 后端
pytest
ruff check .
ruff format --check .
mypy backend

# 前端
cd frontend
npm run test:run
npm run type-check
npm run i18n:check
npm run build
```

更多文档：

- [前端 UX 与交互规范](./docs/frontend-ux-optimization.md)
- [部署指南](./docs/deployment.md)
- [配置参考](./docs/configuration.md)
- [API 参考](./docs/api-reference.md)
- [安全注意事项](./docs/security.md)
- [贡献指南](./CONTRIBUTING.md)

## 许可证

MIT License，详见 [LICENSE](./LICENSE)。
