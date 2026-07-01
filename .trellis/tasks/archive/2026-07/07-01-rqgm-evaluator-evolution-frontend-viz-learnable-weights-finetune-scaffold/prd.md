# RQGM Evaluator Evolution — Out-of-Scope Epoch Items

## Goal

完成 RQGM 评估器 (arxiv 2606.26294) 的三类后续 epoch 演进，使其从"固定规则 judge 面板"走向"真正协同演化"：
1. 前端可视化页 — 把已落地的 EvaluationResult 6 维评分展示成可交互图表
2. grader 权重可学习化 — 硬编码权重做成可配置/可持久化，预留训练数据回灌通道
3. 模型微调脚手架 — LoRA/PEFT 微调骨架 + 标注语料采集管道

## What I already know

- evaluator 已集成工作流 (`evaluator_gate`) 和 omp 工具 (`xhs_evaluation_result`)
- 6 维 judge 面板：copywriting/visual/compliance/reach/audience + bias_check
- `_DIMENSION_WEIGHTS`、`DEFAULT_PASS_THRESHOLD` 等全是模块级硬编码常量 (`backend/agents/evaluator.py`)
- decision/overall 由确定规则重算（不信任 LLM 自报），保证一致性
- 前端已装 `echarts` + `vue-echarts`，有 `components/charts/` 目录和懒加载路由
- `GET /evaluation/result/{thread_id}` API 已就绪
- `system_config` 表是 secret 导向全局配置（API key 类），不适合放可学习权重参数
- analyst 节点处理 publish 后 analytics，但**未把真实 engagement 反喂回 evaluator 权重**
- 前端无 `/evaluation` 路由和视图

## Decision (ADR-lite)

**Context**: 三类工作量和前置条件差异巨大 — 前端页纯前端单 PR 可落地；权重训练需发布后真实数据闭环（数据问题）；微调需 GPU + 标注语料（基础设施级）。

**Decision**: 拆三个独立子任务，各自 PR（符合 `separate-pr-per-feature` 记忆），按 前端页 → 可学习化 → 微调 顺序推进。本轮按"三者都做"执行。

**Consequences**:
- 每个子任务可独立验收、独立合并
- 权重可学习化本期只搭骨架（可配置+持久化+回灌通道），真正训练依赖发布后数据
- 微调脚手架本期只搭骨架 + 语料采集，真正训练需 GPU

## Subtasks

1. `07-01-evaluator-frontend-viz` — 前端可视化页
2. `07-01-evaluator-learnable-weights` — grader 权重可学习化
3. `07-01-evaluator-finetune-scaffold` — 模型微调脚手架

## Requirements (总)

- 三类演进各自有可演示产物
- 不破坏现有 evaluator_gate 工作流和 omp 工具
- 权重/微调改动向后兼容：默认值 = 当前硬编码值

## Out of Scope (总)

- 真正的 grader 权重在线训练（需发布后真实 engagement 数据积累）
- 实际模型微调训练运行（需 GPU + 足够标注语料）
- grader 自身 prompt 的协同演化（论文 Red Queen 机制的 prompt 级实现，另开 epoch）

## Technical Notes

- evaluator 源码：`backend/agents/evaluator.py`
- 评估 API：`backend/api/routes/evaluation.py`
- 评估状态：`backend/state/substates.py` `EvaluationResult` / `DimensionScore`
- analyst 回灌点：`backend/agents/nodes/analyst.py`
- 前端图表组件：`frontend/src/components/charts/`
- 前端路由：`frontend/src/router/index.ts`
