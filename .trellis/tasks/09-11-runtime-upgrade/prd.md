# Agent Runtime 架构升级（Workflow-centric → Kernel-centric）— 路线图

## Background

2026-09-11 的架构评估（research/architecture-review-2026-09-11.md）判断：XhsGrowthAgent 已越过 "Agent Demo → 产品" 阶段，核心瓶颈不再是 Prompt/模型，而是 LangGraph Workflow 承担了太多 Kernel 职责。P0 断言已逐条对当前代码核实（research/p0-claims-verification.md），全部 VERIFIED。

目标终态：Agent Kernel + Task Graph + Context Compiler + Memory Fabric + Tool Gateway + Durable Scheduler + Decision/Action System。LangGraph 从 "≈ 系统" 降级为 "Task Graph Executor"。

克制原则：不新增 PlannerAgent/MemoryAgent/RetryAgent 之类的 LLM Agent；能用 deterministic mechanism 解决的不放 Agent。

## 子任务分解（依赖顺序）

### P0 `09-11-p0-correctness-fixes` — 正确性修复（无前置依赖）
async 共享可变状态、双 Retry 语义收口、Publisher 幂等、namespace fail-fast、Evaluator compliance fail-closed。本任务独立可合并，不依赖后续任何阶段。

### P1a `09-11-p1-kernel-state-layers` — Kernel 核心对象 + State 三层拆分（依赖 P0）
引入 RunContext / Task / ArtifactRef / ToolResult / ActionIntent / ExecutionReceipt 六个核心对象；XHSGrowthState 收缩为 RuntimeState（phase/task/retry/interrupt/artifact refs）；copy/visual/PDF 等大块内容改存 Artifact Store（checkpoint 只留 artifact_id）；performance_log/messages 等 append 流迁往 Event/Trace Store，消除 checkpoint 放大。含 Memory 检索降级显式信号（RetrievalResult.mode/degraded）。checkpoint 迁移兼容需单独设计。

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
