# P1c 实施 prd — Tool Runtime

> 状态：**草案（2026-09-15）**。用户以"继续"驱动，Q1–Q6 按推荐执行并冻结为本任务
> info.md 的 D1'–D6'；开工前如需推翻某项，改对应条目即可。
> 前置：P1a（Kernel 骨架 + State 三层）与 P1b（Context Compiler）均已合入 main；
> 本任务分支自 main 开（独立 PR）。L1 tool schema 层（P1b 留的空层）由本任务补生产者。

设计权威来源：父任务 prd `09-11-runtime-upgrade/prd.md` P1c 段 +
`research/architecture-review-2026-09-11.md`（Tool 未组件化）+ P1b info.md
（L1_TOOL_SCHEMA 保持空直到 P1c 给生产者）。

## 目标（父 prd 已定）

Agent 不再 `from backend.tools.xhs.xxx` 直调；建立 **ToolSpec**（capability / input-output
schema / latency-cost class / side_effect / retry_policy / auth_scope）+ **Registry** +
**Gateway**；**timeout / retry / permission / rate limit / error / tracing 收口到 Gateway**；
Agent 只声明 capability 需求。

## 现状盘点（2026-09-15 实测）

工具面本身不大——4 个子包、15 个模块；**9 处 agent 直调**，按风险梯度天然分四类：

| # | 调用点 | 工具 | 类别 | 副作用 |
|---|---|---|---|---|
| 1 | `content_strategist.py:593` | `analysis.topic_scorer.topic_scorer` | 纯计算 | 无 |
| 2 | `copywriter.py:504` | `content.de_ai_taste.algorithmic_de_ai` | 纯计算 | 无 |
| 3 | `copywriter.py:456` | `content.de_ai_taste.polish_copy` | 内部 LLM | 无（但计费/慢） |
| 4 | `analyst.py:308` | `ripple.integration.get_report` | 外部服务 | 只读 |
| 5 | `content_strategist.py:635` | `ripple.integration.predict_spread` | 外部服务（重） | 只读，长耗时 |
| 6 | `content_strategist.py:686` | `ripple.integration.validate_pmf` | 外部服务 | 只读 |
| 7 | `trend_scout.py:77` | `xhs.trending.xhs_trending` | 外部平台 | 只读但有封禁风险 |
| 8 | `trend_scout.py:91` | `xhs.trending.competitor_analyzer` | 外部平台 | 只读但有封禁风险 |
| 9 | `trend_scout.py:118` | `xhs.trending.keyword_monitor` | 外部平台 | 只读但有封禁风险 |

模块分布：`xhs/`（analytics / engagement / publisher / trending）、`content/`
（de_ai_taste / layout / style）、`ripple/`（client / integration）、`analysis/`（topic_scorer）。
其中 `xhs/publisher.py` 是**真正的高副作用**面（发帖），目前不在 agent 直调清单里
（走 API 层），P2a 会把它纳入 Action Executor + Gateway——本任务只保证它的工具能被注册，
不改变其调用路径。

## 决策点（按推荐冻结 → info.md D1'–D6'）

### Q1 ToolSpec 的 schema 表达形态
- **A（推荐）**：Pydantic 模型。`ToolSpec` 为 frozen Pydantic，input/output 直接引用
  已有 Pydantic 模型（缺失的补最小模型），必要时导出 JSON schema 供 L1 渲染。
  与项目既有风格一致，可测性好，零新依赖。
- B：dataclass + 手写 JSON schema dict——更轻，但与项目 Pydantic 主流不一致，
  L1 渲染需自己维护 schema 正确性。

### Q2 Gateway 的调用形态
- **A（推荐）**：单一收敛入口 `await Gateway.invoke(capability, payload, *, ctx) -> ToolResult`；
  Registry 负责 capability → 实现绑定。timeout / retry / tracing / error 归一化都在这一条路径上。
- B：给每个工具加 `@tool(...)` 装饰器——改动面看起来小，但 rate limit / permission /
  tracing 会散落各处，违背"收口"目标。

### Q3 迁移激进程度
- **A（推荐）**：按**风险梯度分批**（纯计算 → 内部 LLM → 外部只读服务 → 外部平台），
  每批独立可合；迁移期新旧路径并存，但立刻加 **AST 门禁冻结新增直调**（只许减不许增）。
- B：一次性全迁——9 处虽不多，但外部平台类工具带封禁风险，回滚面大。

### Q4 权限 / auth_scope 的落地深度
- **A（推荐）**：本任务只做**声明 + 校验元数据**（capability 是否被该 agent 声明、
  auth_scope 是否齐备），真正的账号级鉴权执行留给 P2a（Action Executor + Policy Engine）——
  否则要依赖尚不存在的身份上下文。
- B：本轮接账号级鉴权——依赖超前，且与 P2a 的 Policy Engine 职责重叠。

### Q5 L1 tool schema 的生产方式
- **A（推荐）**：从 Registry **按需生成**——只把该 agent 声明的 capability schema 渲染进 L1。
  稳定前缀第二位，内容随 agent 固定，可安全上 prompt cache；新增 schema 需刷新
  P1b 快照（同 PR 内 `--write-snapshot`，diff 可见）。
- B：全量 schema 进 L1——prompt 立刻膨胀，且与"只给该 agent 需要的"意图相悖。

### Q6 retry policy 的归属
- **A（推荐）**：Gateway 层声明式 `retry_policy`，按 `side_effect` 分级——`pure` 可安全重试，
  `side_effecting` 必须带幂等键；**不与 graph 级 retry 叠加**（P0 已收口双 retry 语义）。
- B：复用 graph 的 retry——自动重试会把"工具级瞬时失败"和"节点级失败"混在一起，
  正是 P0 修掉的坑。

## 切片计划（每片独立 PR）

| 切片 | 内容 | 风险 |
|---|---|---|
| **S1** | `ToolSpec` 模型 + `Registry`（声明式注册、capability 查表、去重/冲突 fail-fast）+ 为现有工具登记元数据。**纯新增，零行为变更** | 低 |
| **S2** | `Gateway` 骨架：`invoke` 单一路径，timeout / retry（按 side_effect 分级）/ error 归一化 / tracing 事件；先接 1 个纯计算工具试点（topic_scorer） | 低-中 |
| **S3** | 分批迁移 9 个直调点：S3a 纯计算(2) → S3b 内部 LLM(1) → S3c ripple 只读(3) → S3d xhs 平台(3) | 中（S3d 最高） |
| **S4** | L1 tool schema 生产者：Registry → L1 层渲染，接入 Context Compiler（P1b 遗留空层）；刷新基线快照 | 中 |
| **S5** | 门禁 + 文档：AST 门禁（`backend/agents/**` 禁止直调 `backend.tools`，白名单=Registry/Gateway）、Registry 覆盖度（每个已注册工具都有 spec）、`docs/tool-runtime.md` | 低 |

执行记录（2026-09-15）：**S3c 实际拆为两片**。

- **S3c-1 ✅**：`ripple.get_report`（analyst）。等待预算从调用点的 120s `asyncio.wait_for` 搬到能力声明（`timeout_s=120.0`），直调 **6 → 5**。
- **S3c-2 待办（有阻塞）**：`ripple.predict_spread` / `ripple.validate_pmf` **不能机械迁移** —— 这两个工具用 `RippleTimeoutError`（携带 `job_id`，调用方据此取消任务并留作续存）表达"等超时"这一**领域结果**，而 Gateway 把一切失败归一化成字符串 `error`，`job_id` 会丢；同时它们把软失败当数据返回（`{"error": ...}`），经 Gateway 会被记为 `ok=True`（trace 失真）。动这两处之前需要先给 `ToolResult` 增加领域结果通道。

## 验收

- `backend/agents/**` 对 `backend.tools` 的直调**清零**（AST 门禁强制，白名单仅 Registry/Gateway 自身）
- 每次工具调用经 Gateway，产生 tracing 事件；timeout / retry 行为有测试覆盖
- `pure` 工具重试安全、`side_effecting` 工具强制幂等键（无键即拒）
- L1 层被真实填充且不破坏 P1b 稳定性四不变量；快照在同 PR 刷新
- 全量 `tests/unit` + `tests/integration` 通过；ruff / mypy 干净

## 红线（不做的事）

- 不引入 LLM Tool-calling 自主规划（那是 P2c 的事）
- 不改变 `xhs/publisher.py` 的实际发布路径（P2a 负责）
- 不做账号级鉴权执行（P2a Policy Engine）
- 不为"以后可能用到"提前抽象未注册工具
