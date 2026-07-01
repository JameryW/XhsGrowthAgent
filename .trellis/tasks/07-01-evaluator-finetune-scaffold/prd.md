# Evaluator Model Finetune Scaffold

## Goal

为 evaluator judge 模型搭 LoRA/PEFT 微调脚手架 + 标注语料采集管道。本期只搭骨架和语料采集，不跑实际训练（需 GPU + 足够语料）。

## What I already know

- evaluator 当前用 `astron-code-latest`（EVALUATION TaskType 路由），judge 输出 6 维 JSON
- 无现有微调脚手架 / 语料采集
- 标注来源候选：①人工标注（review_gate 人工反馈）②发布后真实 engagement 回灌 ③RQGM 论文的 grader 互评

## Requirements

- 语料采集管道：把 (输入内容, 6 维评分, decision) 持久化为训练样本
- 微调脚手架：LoRA/PEFT 配置 + 训练入口脚本（`scripts/finetune_evaluator.py` 或 backend/finetune/）
- 数据导出：样本表 → 训练格式（jsonl）导出命令
- 训练入口可 dry-run（无 GPU 时校验配置 + 数据）
- 不阻塞现有工作流（采集异步/非关键路径）

## Decision (ADR-lite)

**Context**: 语料质量决定微调上限，三种来源价值/成本各异。

**Decision**: 三种都采 — ①evaluator 每次评估产出（基础样本）②发布后真实 engagement（弱标签）③review_gate 人工反馈（强标签）。样本表用 label_source 字段区分强弱标签。

**Consequences**: 采集管道最复杂（三处采集点），但语料价值最高；engagement 依赖发布闭环，标注可能稀疏，训练时按 label_source 加权。

## Acceptance Criteria

- [ ] 工作流每次评估产出训练样本并持久化
- [ ] 样本可导出为训练 jsonl
- [ ] 微调脚本可 dry-run（校验配置 + 数据，不实际训练）
- [ ] 采集非阻塞，失败不中断工作流
- [ ] 文档说明训练前置条件（GPU/语料量）

## Definition of Done

- 语料采集 + 导出 + 微调脚手架 dry-run
- 文档 + 默认不启用（env 开关）
- lint/mypy 绿

## Out of Scope

- 实际微调训练运行（需 GPU + 足够语料）
- 模型评测/基准对比
- 在线持续训练

## Technical Notes

- evaluator 源码：`backend/agents/evaluator.py`
- TaskType.EVALUATION 路由：`backend/models/router.py`
- 样本采集点：evaluator_node 评估完成后
- 依赖 learnable-weights 子任务的样本表（或独立 finetune_samples 表）
