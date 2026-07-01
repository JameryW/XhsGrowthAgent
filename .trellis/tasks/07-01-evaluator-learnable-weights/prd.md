# Evaluator Learnable Grader Weights

## Goal

把 evaluator 硬编码的 6 维权重/阈值做成可配置 + 可持久化，并预留训练数据回灌通道，为真正协同演化（grader 权重训练）打地基。本期搭骨架，不实现在线训练。

## What I already know

- 当前权重全在 `backend/agents/evaluator.py` 模块级硬编码：
  - `_DIMENSION_WEIGHTS` (5 维加权，compliance 由 is_blocking 兜底)
  - `DEFAULT_PASS_THRESHOLD=70` / `DEFAULT_REJECT_THRESHOLD=50`
  - `_BIAS_PENALTY_THRESHOLD=60` / `_BIAS_PENALTY=5`
- `system_config` 表是 secret/全局 env 覆盖导向，**不适合**放可学习参数
- analyst 节点处理 publish 后 analytics，但未反喂 evaluator 权重
- evaluation_result 已含 dimensions 原始分 + overall + decision

## Requirements

- 权重/阈值从 DB 读取（缺省回落到当前硬编码值，保证向后兼容）
- 新建轻量存储（不污染 system_config）：`evaluator_config` 表 or 现有 store namespace
- evaluator 启动读权重，缓存（避免每次评估查 DB）
- 标注样本回灌通道：publish 后把 (evaluation_result.dimensions, 真实 engagement) 写入样本表
- 训练接口预留（CLI or admin endpoint），本期只支持手动/离线回灌，不实现自动训练
- 默认值 = 当前硬编码值（零行为变化）

## Decision (ADR-lite)

**Context**: 权重是可学习标量参数，需按账号/赛道差异化（协同演化关键），且训练时要 SQL 聚合。

**Decision**: 新建 `backend/db/evaluator_config.py` 专用表（weight_key / weight_value / account_id nullable），不复用 system_config（secret/env 导向）也不复用 LangGraph store（语义是记忆非配置）。

**Consequences**: 多一张表 + db 模块，但权重语义清晰、训练聚合方便、缓存层独立；account_id nullable 兼容全局默认。

## Acceptance Criteria

- [ ] 权重可从 DB 读取，evaluator 不再依赖模块级常量
- [ ] 缺省值 = 当前硬编码值，现有评估测试全绿
- [ ] publish 后样本（dimensions + engagement）写入样本表
- [ ] 权重变更后 evaluator 缓存失效/重载
- [ ] 健康检查/配置页可查 evaluator 权重状态
- [ ] 单测覆盖权重加载 + 缺省回落 + 样本写入

## Definition of Done

- 权重可配置 + 持久化 + 缓存
- 样本回灌通道打通
- 默认值零变化，现有测试绿
- lint/mypy 绿

## Out of Scope

- 真正在线权重训练（需发布后数据积累 + 训练算法）
- grader prompt 级协同演化（另开 epoch）
- 权重训练算法实现（回归/贝叶斯优化等）

## Technical Notes

- evaluator 源码：`backend/agents/evaluator.py`
- analyst 回灌点：`backend/agents/nodes/analyst.py`
- system_config（参考但不复用）：`backend/db/system_config.py`
- EvaluationResult 状态：`backend/state/substates.py`
