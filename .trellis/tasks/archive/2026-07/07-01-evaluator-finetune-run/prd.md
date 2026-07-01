# Evaluator Finetune Run

## Goal

把 `scripts/finetune_evaluator.py --train` 从占位 return 填成真实 SFTTrainer 调用代码。无 GPU 时 graceful 降级 + CPU fallback。

## What I already know

- epoch-1 的 run_train：import torch/peft/transformers/trl 后直接 `return 3`（占位）
- 无 GPU，torch/peft/trl 未安装
- 样本 → jsonl 已实现（sample_to_jsonl）
- LORA_CONFIG + TRAIN_HYPERPARAMS 已定义

## Requirements

- run_train 填实：load tokenizer + base model + LoRA config → SFTTrainer → train() → save adapter
- 无 torch 时清晰报错引导安装（exit 2，已有）
- `--cpu` 开关：强制 CPU 模式（fp32, 小 batch, 适合小规模试跑/调试）
- 训练后保存 adapter 到 out_dir + 写 metrics.json（loss/steps）
- 数据集从 jsonl 加载（datasets 库或手动 Dataset）
- 保留 --dry-run（不变）

## Acceptance Criteria

- [ ] --train 在装了 torch 的机器上能真跑 SFT（代码完整，非占位）
- [ ] --cpu 开关切换 fp32 + 小 batch
- [ ] 训练产物：adapter 权重 + metrics.json
- [ ] 无 torch 时 graceful 报错（exit 2）
- [ ] --dry-run 不变
- [ ] mypy/ruff 干净（torch/peft 等 optional import 有 type:ignore）

## Definition of Done

- run_train 填实可执行
- 代码完整（即使本机无 GPU 无法验证训练结果，代码路径要正确）
- lint/mypy 绿

## Out of Scope

- 实际跑出生产模型（需 GPU + 足够语料）
- 模型评测基准
- 分布式训练

## Technical Notes

- 文件：scripts/finetune_evaluator.py run_train
- 依赖：torch/transformers/peft/trl（optional，type:ignore）
- SFT 流程：trl.SFTTrainer 标准用法
