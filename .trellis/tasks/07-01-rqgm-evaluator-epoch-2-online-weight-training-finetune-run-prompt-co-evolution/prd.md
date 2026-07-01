# RQGM Evaluator Epoch-2 — Online Weight Training + Finetune Run + Prompt Co-evolution + Trend Chart

## Goal

把 epoch-1 落地的"训练管道骨架/占位"升级为"可执行流程"：
1. 在线权重训练 — 从样本（含 engagement 弱标签）统计拟合各维度权重，不再手动 set_weight
2. 微调训练运行 — 把 finetune_evaluator.py --train 从占位 return 填成真实 SFTTrainer 调用（无 GPU 时 graceful 降级）
3. grader prompt 级 Red Queen 协同演化 — prompt 按 epoch 版本化，epoch 边界根据样本表现演化 prompt + 同步 DB 权重到 prompt 文本
4. 评估历史趋势图 — 前端多 thread 聚合趋势

## What I already know (epoch-1 现状)

- `backend/db/evaluator_config.py`：evaluator_config 权重表 + evaluator_samples 样本表（含 engagement 弱标签）
- 权重只有手动 `set_weight`，无训练算法
- `scripts/finetune_evaluator.py --train` 是占位（import 后 return 3，没调 SFTTrainer）
- `backend/config/prompts/evaluator.yaml` 静态，**prompt 里硬编码了权重和阈值**（与 DB 权重不同步风险）
- evaluator.py 已从 DB 读权重（per-account 覆盖默认），DB 不可用回落模块常量
- 前端已有 `TrendChart.vue` + `EvaluationRadar.vue`，无趋势图
- 无 GPU：torch/peft/trl 未安装（微调 --train 需 graceful 降级）

## Decision (ADR-lite)

**Context**: 无 GPU 环境，但要把占位升级为可执行。

**Decision**:
- 权重训练用**轻量统计拟合**（纯 Python/numpy 级，不依赖 torch）：基于样本的 dimensions 分数 → engagement 回归，学各维度权重。无需 GPU。
- 微调 --train 填真实 SFTTrainer 代码（可执行），但无 torch 时 graceful 报错引导安装；加 `--cpu` 开关允许 CPU 小规模试跑（fallback）。
- prompt 协同演化：实现 **epoch 版本化**（evaluator_prompt_epochs 表/prompt 文件版本）+ epoch 切换时根据样本偏倚表现调整 prompt 的 bias_check 严苛度措辞 + 把 DB 权重同步进 prompt 文本（消除 prompt/代码权重不一致）。
- 趋势图：复用 TrendChart 模式，多 thread overall_score 时序。

**Consequences**:
- 权重训练是统计启发式（非深度学习），但有真实数据闭环、可执行、可复现
- 微调 --train 在无 GPU 机器上仍不能跑出生产模型，但代码完整可执行、有 CPU fallback
- prompt 协同演化是规则驱动的 epoch 演化（非 LLM 自演化），符合论文 epoch 边界语义

## Subtasks

1. `07-01-evaluator-online-weight-training` — 在线权重训练（统计拟合）
2. `07-01-evaluator-finetune-run` — 微调训练运行填实
3. `07-01-evaluator-prompt-coevolution` — grader prompt 协同演化
4. `07-01-evaluator-trend-chart` — 评估历史趋势图

## Requirements (总)

- 四项各自可演示、可执行（非占位）
- 不破坏现有 evaluator_gate 工作流（默认权重=epoch-1 值，零行为变化）
- 权重训练非阻塞、可手动触发 + 定时
- prompt 演化有版本追溯、可回滚

## Out of Scope (总)

- 深度学习权重训练（需 GPU + 大数据，用统计拟合替代）
- 生产级微调模型评测/基准
- LLM 自主重写 prompt（用规则驱动 epoch 演化替代）
- 手动触发评估 UI（omp 已有）

## Technical Notes

- 权重训练数据源：evaluator_samples（dimensions + engagement 弱标签）
- 权重训练落点：backend/db/evaluator_config.py 加 train_weights 函数 + scripts/train_evaluator_weights.py CLI
- 微调填实：scripts/finetune_evaluator.py run_train
- prompt 演化：backend/config/prompts/evaluator.yaml 版本化 + backend/agents/evaluator.py 加 epoch 解析
- 趋势图：frontend 新增组件 + /evaluation 页扩展 + 后端聚合端点
