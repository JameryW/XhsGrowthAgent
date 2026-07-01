# Evaluator Online Weight Training

## Goal

从 evaluator_samples（含 engagement 弱标签）统计拟合各维度权重，把 epoch-1 的"手动 set_weight"升级为"从样本自动学权重"的可执行训练流程。无 GPU，纯统计拟合。

## What I already know

- evaluator_samples 表：dimensions（6 维分数）+ engagement（likes/collects/comments/shares/views 弱标签）
- 当前权重：DB evaluator_config 表，set_weight 手动 upsert
- 无 GPU / 无 torch —— 必须用统计方法
- 6 维：copywriting/visual/compliance/reach/audience + bias_check（bias_check 不参与加权，走 penalty）

## Requirements

- `train_weights(account_id)` 函数：从样本拟合各维度权重 + 阈值，写回 evaluator_config
- 训练信号：engagement_rate = (likes+collects+comments+shares) / views（弱标签）
- 算法：归一化线性回归（各维度分数 → engagement_rate），权重 = |回归系数| 归一化到和为 1
- 阈值学习：用 decision 与真实表现的混淆矩阵调 pass/reject threshold（样本足时）
- CLI `scripts/train_evaluator_weights.py --account-id X --dry-run/--apply`
- 最小样本数守卫（< MIN_SAMPLES 跳过，默认沿用）
- 训练非阻塞、可手动触发
- 默认值 = epoch-1 值（无样本时零行为变化）

## Acceptance Criteria

- [ ] train_weights 能从样本拟合出权重并写回 DB
- [ ] --dry-run 打印学到的权重 + 样本数 + 拟合质量（R²）
- [ ] --apply 写回 evaluator_config
- [ ] 样本不足时 graceful 跳过 + 提示
- [ ] 无 DB 时 graceful 降级
- [ ] 单测覆盖拟合逻辑 + 边界（0 样本/1 样本/全同分）
- [ ] 默认权重不变，现有测试绿

## Definition of Done

- train_weights + CLI 可执行
- 单测覆盖
- lint/mypy 绿

## Out of Scope

- 深度学习权重训练（需 GPU）
- 在线持续训练（本期手动/定时触发）
- 训练算法极致调优（用最简统计拟合）

## Technical Notes

- 数据源：evaluator_samples（dimensions + engagement）
- 落点：backend/db/evaluator_config.py 加 train_weights + scripts/train_evaluator_weights.py
- 算法：归一化线性回归（无第三方依赖，纯 Python 或 numpy 若已装）
- 依赖 epoch-1 的 load_weights/set_weight
