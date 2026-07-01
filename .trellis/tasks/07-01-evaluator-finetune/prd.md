# evaluator finetune 训练样本补原文输入

## Goal

修复评估器 finetune 链路的根本断点：SFT 训练样本缺"被评估的内容"，模型学不到"内容→评分"映射。当前 `finetune_evaluator.py` 的 `sample_to_jsonl` 把 instruction 设为泛泛的"评估以下内容"但 `input=""`，且 output 只含分数，丢了 rationale/issues/bias_severity 等推理信号。上游 `_collect_sample` 也未存原文。

## What I already know

* finetune 脚本完整可执行（dry-run/export/train 三模式），LoRA SFT 流程对，但训练数据贫乏。
* `sample_to_jsonl`（finetune_evaluator.py:76-105）：
  - `dim_summary` 只取 `dimension=score`，忽略 `bias_severity`（PR#159 新字段）、`rationale`、`issues`、`is_blocking`。
  - `output` 只写 综合分/决策/维度score，丢了推理内容。
  - `input=""`（空），instruction 不带被评估内容。
* `_collect_sample`（agents/nodes/evaluator.py:69-93）只存 dimensions/overall_score/decision/label_source，未存 copy_content/visual_plan 原文。
* `EvaluatorSample` dataclass + evaluator_samples 表无原文列。

## Assumptions (temporary)

* finetune 目标是让 judge 模型学会"内容→6维评分+决策+推理"，不是只复述分数。
* 原文内容（标题/正文/标签/CTA/视觉prompt）是必要训练输入。

## Open Questions

*（已全部收敛 — 默认采用推荐方案 A 推进）*

## Requirements

* `evaluator_samples` 表新增 `content_snapshot` JSONB 列（nullable，向后兼容旧样本）。
* `_collect_sample` 采集时存内容快照：标题 + 正文截断（前 ~2000 字）+ hashtags + CTA + tone + 视觉 prompt 列表（封面+图片 prompts，cap 数量）。不含完整原文，控制体积。
* `sample_to_jsonl`（finetune_evaluator.py）：
  - `input` = content_snapshot 渲染成"被评估内容"文本块。
  - `output` = 完整 judge 产出：6维 score+bias_severity+rationale+issues（首几条）+决策+bias_warning，不只分数。
  - `bias_severity` 进入训练数据（PR#159 新字段）。
* 旧样本无 content_snapshot 时：jsonl 记录标记 input 为空 + metadata `incomplete=true`，不崩。
* 不破坏 export_samples / insert_sample 现有调用方。

## Decision (ADR-lite)

**Context**: finetune SFT 样本缺"被评估内容"，input="" 让模型学不到内容→评分映射；output 只含分数丢了推理信号。原文需从某处取。
**Decision**: Approach A — 采集时把内容快照存进 evaluator_samples.content_snapshot（JSONB，nullable）。finetune 数据自包含，离线可跑，不依赖 checkpointer 存活。不做 backfill（评估器刚上线，无历史样本量，YAGNI）。
**Consequences**: sample 行体积涨 ~1-3KB/条（可接受，截断控制）；一次性 ADD COLUMN 迁移（nullable 兼容）；旧样本不可训练但新样本即生效。

## Acceptance Criteria

* [ ] evaluator_samples 表有 content_snapshot 列（migration + ensure_tables）。
* [ ] _collect_sample 存内容快照；insert_sample 持久化它。
* [ ] sample_to_jsonl 的 input 含内容、output 含完整 judge 产出含 bias_severity。
* [ ] 旧样本（无 snapshot）jsonl 不崩，标记 incomplete。
* [ ] dry-run 输出验证数据格式；新增 finetune 数据格式单测。
* [ ] 现有 evaluator/evaluator_config 测试不破。
* [ ] ruff/mypy/CI 绿（check + format --check 都跑）。

## Definition of Done

* Tests added/updated
* Lint/typecheck/CI green
* Docs/notes updated if behavior changes

## Out of Scope (explicit)

* 实际跑 --train LoRA（需 GPU + 依赖，本任务只保证数据格式正确 + dry-run 验证）。
* DPO/reward 阶段（engagement 弱标签后续用）。

## Technical Notes

* 涉及：scripts/finetune_evaluator.py、backend/agents/nodes/evaluator.py（_collect_sample）、backend/db/evaluator_config.py（EvaluatorSample/insert_sample/export_samples schema）、state schema 若存原文。
* checkpointer：compile_graph_prod/dev 用 AsyncPostgresSaver/Memory，thread_id 已存于 sample。
