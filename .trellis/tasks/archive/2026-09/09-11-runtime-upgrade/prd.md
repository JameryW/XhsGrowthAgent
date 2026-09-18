# Agent Runtime 架构升级（Workflow-centric → Kernel-centric）— 路线图

## Background

2026-09-11 的架构评估（research/architecture-review-2026-09-11.md）判断：XhsGrowthAgent 已越过 "Agent Demo → 产品" 阶段，核心瓶颈不再是 Prompt/模型，而是 LangGraph Workflow 承担了太多 Kernel 职责。P0 断言已逐条对当前代码核实（research/p0-claims-verification.md），全部 VERIFIED。

目标终态：Agent Kernel + Task Graph + Context Compiler + Memory Fabric + Tool Gateway + Durable Scheduler + Decision/Action System。LangGraph 从 "≈ 系统" 降级为 "Task Graph Executor"。

克制原则：不新增 PlannerAgent/MemoryAgent/RetryAgent 之类的 LLM Agent；能用 deterministic mechanism 解决的不放 Agent。

## 子任务分解（依赖顺序）

### P0 `09-11-p0-correctness-fixes` — 正确性修复（无前置依赖）
async 共享可变状态、双 Retry 语义收口、Publisher 幂等、namespace fail-fast、Evaluator compliance fail-closed。本任务独立可合并，不依赖后续任何阶段。

### P1a `09-11-p1-kernel-state-layers` — Kernel 最小骨架 + State 三层拆分（依赖 P0）
**范围已按 2026-09-13 用户拍板收敛**（详案与代价记录见该任务 info.md + research/）：本任务落 **3+2 件**——ArtifactRef + ArtifactStore（LangGraph BaseStore + façade）+ EventStore（workflow_events 表 + 内存回退）+ RuntimeState 字段矩阵 + hydration 层。XHSGrowthState 收缩为 RuntimeState（路由谓词只消费本层字段；versions_meta/trend_summary 类摘要留驻、正文外置）；performance_log 与死字段（messages、state content_history）出 checkpoint；/status 保全文响应（6 个读面收口 hydration，前端零改动）。迁移=一刀切：新 run 新 schema、存量 checkpoint 不重写、旧线程透传；RunContext→P1b、Task/ToolResult→P1c、ActionIntent/Receipt 通用化→P2a（避免无消费方的提前抽象）。Memory 检索降级信号（RetrievalResult.mode/degraded）随 P1b recall 管线落。

### P1b `09-11-p1-context-compiler` — Context Compiler（依赖 P1a 的 RunContext）
统一 recall → rerank → dedup → freshness → confidence → token budget → compile；prompt 分层 L0-L5 稳定前缀（L0 system/policy、L1 tool schema、L2 account profile ｜ L3 task、L4 memory、L5 observations）；消除 `"母婴"` 隐式默认上下文污染；context item 带 source/timestamp/confidence/scope/priority/token_cost。

### P1c `09-11-p1-tool-runtime` — Tool Runtime（依赖 P1a）
Agent 不再 `from backend.tools.xhs.xxx` 直调；建立 ToolSpec（capability/input/output schema、latency/cost class、side_effect、retry_policy、auth_scope）+ Registry + Gateway；timeout/retry/permission/rate limit/error/tracing 收口到 Gateway；Agent 只声明 capability 需求。

### P1d `09-11-p1-structured-output` — 结构化输出 schema 化（依赖 P1a）
主要链路改 provider-native structured output + Pydantic schema + semantic validator + validation-error retry；`_parse_json_response_impl` 降级为 legacy fallback；ContentPlan 等 dict[str, Any] 全面类型化。

### P2a `09-11-p2-action-model-mainline` — Creator Action 模型融入主链（依赖 P1a ArtifactRef + P0/P1c）
Publisher 改造为 Generate → PublishIntent(artifact_id + content_hash + account) → Policy Engine → Human Confirm → Action Executor → Tool Gateway → ExecutionReceipt；复用 creator_agent 的 ActionIntent/Receipt 实现为全局执行协议；重要 Decision 一律产 immutable DecisionRecord。

### P2b `09-11-p2-execution-plane` — Execution Plane 独立 + durable scheduler（依赖 P0 的 retry 收口）
_background_tasks process-local → lease-based durable task scheduler（acquire/heartbeat/commit/lease-expiry）；XHS Browser/CDP、Ripple、重型图片任务移到 worker；API 进程不持有真实执行生命周期。

### P2c `09-11-p2-dynamic-planning` — 动态 Planning（依赖 P1a/P1c/P2a）
Planner 按 Goal 编译 Task Graph（保留常用模板为 deterministic path），停止新增 workflow_mode+router+edge；workflow.py（2519 行）按 api/application/runtime/artifacts/actions 分层拆分。

### P3 `09-11-p3-outcome-learning` — Outcome Learning 闭环（依赖 P2a/P2c）
区分 offline quality（LLM Judge）与 online reward（impression/click/save/comment/follow/conversion）；串起 Context+Decision+Content+Execution+Outcome → LearningSignal → CreatorModel Revision → 下一轮决策；统一 Memory 与 Creator Model 两套 personalization stack 为 Memory Fabric。

## 验收

父任务在全部子任务归档后关闭。每个子任务独立 PR、独立通过 tests/unit + tests/integration。

## 交付结清（2026-09-18）

**验收判定：9/9 子票交付，51 个 PR（#577–627）连续无缺口。**

判定方式不是读票面自述，而是**实测**：把窗口内每个已合并 PR 的标题按子票前缀归属，得到 **51/51 全部归属成功**（无一条落在票外），且九个票段**严丝合缝拼满** #577–627（无跳号、无重叠）。票面自述在本仓**不可信** —— 多片票的 `task.json.commit` 只记最后一片（P0/P1b/P1c/P1d 甚至是空），`status` 在交付后仍写着 `in_progress`。判交付只看 `git log origin/main`。

| 子票 | PR | n | 交付面 |
|---|---|---|---|
| P0 `09-11-p0-correctness-fixes` | #577 | 1 | 并发状态隔离、retry 收口、发布幂等、质量门 fail-closed |
| P1a `09-11-p1-kernel-state-layers` | #578 | 1 | ArtifactStore / EventStore / hydration + State 三层拆分 |
| P1b `09-11-p1-context-compiler` | #579–590 | 12 | recall → … → compile、prompt L0–L5 分层、逐 agent 迁移、基准门禁 |
| P1c `09-11-p1-tool-runtime` | #591–599 | 9 | ToolSpec + Registry + Gateway，调用点全部改道 |
| P1d `09-11-p1-structured-output` | #600–605 | 6 | provider-native structured output + schema 化 |
| P2a `09-11-p2-action-model-mainline` | #606–613 | 8 | PublishIntent + 确定性策略引擎 + 人工确认 + Action Executor |
| P2b `09-11-p2-execution-plane` | #614–617 | 4 | 租约数据面 + 接管/自栅栏 + 执行平面契约文档 |
| P2c `09-11-p2-dynamic-planning` | #618–623 | 6 | Plan 只读导出 + 穷举模板注册表 + 模式/Goal 收敛 + `workflow.py` 分层 |
| P3 `09-11-p3-outcome-learning` | #624–627 | 4 | 弱标签契约 + 接通生产者 + 结果学习契约文档 |

### 目标终态对照（见上文第 7 行）

| 目标终态 | 今天的落地物 | 由谁交付 |
|---|---|---|
| Agent Kernel | `backend/state/`（artifacts / events / hydration / schema / substates / machine，约 2485 行） | P1a |
| Task Graph | `backend/state/machine.py` + `modes.py` + `docs/planning.md`（Plan 契约 + 穷举模板注册表） | P2c |
| Context Compiler | `backend/context/`（compiler / retrieval / estimator / segments / baseline）+ `docs/context-compiler-baseline.md` | P1b |
| Memory Fabric | `backend/memory/` —— **读侧已统一；写侧明确不统一**（见遗留 7） | P3 裁定 |
| Tool Gateway | `backend/tools/runtime/`（gateway / registry / catalog / audit / schema）+ `docs/tool-runtime.md` | P1c |
| Durable Scheduler | `backend/db/execution_leases.py` + `api/routes/_takeover.py` + `graph/takeover_safety.py` + `docs/execution-plane.md` | P2b |
| Decision/Action System | `creator_agent/policy.py`（确定性策略）+ `agents/nodes/publish_gate.py`（人工闸门）+ `docs/publish-action-protocol.md` | P2a |

「LangGraph 从『≈ 系统』降级为 Task Graph Executor」按票面的克制原则部分达成：**判定与执行**已经搬到 Kernel 侧（state 三层 + 策略引擎 + 网关 + 租约），但**图仍然是主链的编排者** —— 这是 P2a 遗留 2 的直接后果。

### ★ 遗留登记（关闭 ≠ 无已知缺口）

八条**被明确登记、而不是顺手修掉**的事项。它们不是遗漏：每一条都带着「为什么不修」与「什么证据才开闸」。**关闭父任务不改变它们的效力**，也不表示它们被接受为终态。

| # | 遗留 | 出处 | 为什么不修 / 开闸条件 |
|---|---|---|---|
| 1 | 两条 publish-retry 路径（`_runner._background_tasks[thread_id]` 与 publish-retry）**既未迁移也未接管** —— 重启后不可见，而它们恰恰是「上一次没跑完」时最可能被走的路径 | P2b（第 7 节末有排序后的修复清单） | 两个修法都改变行为（走单一入口会改相位推进与事件时序；自有租约要加拒绝分支与新失败模式），闸门未开 |
| 2 | 主干仍直调 `run_publish`：**不发 PublishIntent、不过策略引擎** —— 计划行里「PublisherAgent emits a PublishIntent and stops there」这半句**未建** | P2a | 走控制面（intent → Policy → Executor）是与「永不无授权发布」**正交**的架构迁移（S4a 已定不发 intent）；S5c 已把契约写下来 |
| 3 | `orchestrator_router` 在 brief 模式 + `phase=creating` 时答 `copywriter`，而 `builder.py` 的 orchestrator 路径映射**没有这个键** ⇒ 即 P1d 的 KeyError 失败形态；`CREATING` 非终态、分支**可达** | P2c | 需要一次定夺（补映射键 or 改 router 答案），且该分支今天无测试覆盖 |
| 4 | `should_brief_or_optimize` **完全没有调用者**（图用普通 edge 到 `blogger_scout`，早于本表存在）—— 已登记进 `ROUTERS_WITHOUT_AN_EDGE` | P2c | 要么接线、要么删；已带反向断言，有人接线时会红 |
| 5 | 两个 text→JSON 解析器**不可合并**（`_parse_json_response` 与 `llm_enrichment` 那份）：后者的 `raise` 是触发 `fallback_fn` 的唯一条件，而 `de_ai_taste` 依赖 `method == "algorithmic"` | P1d | 融合会动到 topic 红线；分歧已钉成可执行断言（`TestTheTwoParsersCannotBeMerged`），已知缺陷标为「本片不修」 |
| 6 | ripple-retry 路由（`api/routes/workflow.py` 约 :2184）**仍直调 `RippleService`**：工具门禁范围**故意**只覆盖 `backend/agents/**`；`xhs.publish` 在目录里是唯一孤儿 | P1c | 边界已写进 `_ALLOWED_PREFIX` 的说明；P2a 落地后孤儿消失 |
| 7 | **Memory Fabric 只统一了读侧**：写侧（`LearningSignal` 与 engagement 弱标签）**明确不合并** | P3 | 人工 `UserFeedback`（`pending_creator_review`，**要人审**）与自动弱标签合并会改变人工闸门的语义 ⇒ 需要先有「两条路径对同一 run 给出冲突结论」的实例 |
| 8 | `count_labeled_since` 的窗口是**样本创建时间**，而写入条件是「每次 sync 回填一次」⇒ 一条老样本被标签会正常落库、**却不推高计数**；`free` 路径的无门回填同理 | P3（S4 已裁定「登记不改」） | 现行方向**偏保守**（只让演进更晚）。**要开闸，先证明「同一行被重复回填是可识别的」**（回填次数 / 标签版本）—— 否则把窗口换成「标签到达时间」会让 upsert 的重复回填算成新标签、计数虚高，可能用未成熟样本池重拟合。**晚只是延迟，错会污染权重。** |

### 本次结清做了什么 / 没做什么

- **做了**：把「9 子票已交付」从票面自述升级为**可复算的映射**（51/51 归属、九个票段拼满窗口）；把八条遗留集中到一处；按本仓归档惯例（`task.py archive`）把 9 个子票与父任务移入 `archive/2026-09/`。
- **没做**：没有改动一行生产代码；没有把上述八条遗留顺手修掉；各子票的 `prd.md` / `notes` 保持原样（**归档只翻 `status` 与 `completedAt`，是移动而非改写**）。
- **口径**：`completedAt` 由归档工具写作**归档日**（2026-09-18）。各子票的**真实交付日**见其 `notes` 里的 `DELIVERED` 段与上表的 PR 号；P0 更早（#577，归档于 2026-09-13，其 `completedAt` 保留当时的值）。
- **一处历史偏差已就地修正**：P0 曾同时存在于 `tasks/` 与 `archive/2026-09/`（上一轮手工复制、未删原件），现按工具语义（移动）删除 `tasks/` 下的残留。

