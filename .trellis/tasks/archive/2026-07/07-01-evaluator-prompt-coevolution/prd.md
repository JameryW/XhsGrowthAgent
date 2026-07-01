# Evaluator Prompt Co-evolution

## Goal

实现 grader prompt 级 Red Queen 协同演化：prompt 按 epoch 版本化，epoch 边界根据样本偏倚表现演化 prompt（bias_check 严苛度措辞）+ 把 DB 学到的权重同步进 prompt 文本，消除 prompt/代码权重不一致。

## What I already know

- evaluator.yaml 静态，**prompt 里硬编码了权重**（copywriting 0.25...）和阈值（>=70, <50）
- evaluator.py 从 DB 读权重重算 overall（不信任 LLM 自报）—— 但 prompt 里写的权重若与 DB 不同步，LLM 自报 overall 会偏
- 论文 RQGM：epoch 内评估标准固定（保自改进理论性质），epoch 边界可演化 utility
- bias_check 维度检测面板对 AI 内容过度宽容

## Requirements

- prompt 版本化：evaluator.yaml 支持 {epoch_version} + {weights_block} 占位，运行时从 DB 填充
- 权重同步：evaluator 启动读 DB 权重，把权重块注入 prompt（消除硬编码不一致）
- epoch 机制：evaluator_prompt_epochs 表（epoch_id, bias_severity, weights_snapshot, created_at, active）
- epoch 演化：CLI `scripts/evolve_evaluator_prompt.py` 根据近期样本的 bias_check 表现调整下个 epoch 的 bias 严苛度措辞
- epoch 切换有版本追溯、可回滚（active 标记）
- 默认 epoch = 当前 prompt 行为（零变化）

## Acceptance Criteria

- [ ] prompt 运行时注入 DB 权重（不再硬编码）
- [ ] epoch 表可建、可切、可查
- [ ] evolve 脚本根据样本调 bias 严苛度
- [ ] epoch 切换可回滚
- [ ] 默认行为 = epoch-1（零变化）
- [ ] 单测覆盖 prompt 注入 + epoch 切换
- [ ] lint/mypy 绿

## Definition of Done

- prompt 版本化 + 权重同步 + epoch 演化 CLI
- 单测覆盖
- lint/mypy 绿

## Out of Scope

- LLM 自主重写 prompt（用规则驱动 epoch 演化）
- 多 grader 面板对抗训练

## Technical Notes

- prompt：backend/config/prompts/evaluator.yaml 加占位
- epoch 表：backend/db/evaluator_config.py 加 ensure + CRUD
- 注入：backend/agents/base.py _build_system_prompt 或 evaluator.py
- evolve CLI：scripts/evolve_evaluator_prompt.py
