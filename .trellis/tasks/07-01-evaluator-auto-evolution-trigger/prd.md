# 评估器在线协同演化自动触发

## Goal

让 RQGM 评估器的"自我改进"从纯手动 CLI（evolve_evaluator_prompt.py / train_evaluator_weights.py 需人手动 --apply）变成事件驱动的在线触发，使评估器能根据真实反馈持续调整 prompt epoch 权重，闭合协同演化回路。

## What I already know

* 两个演化脚本完整：evolve_evaluator_prompt.py（bias_severity epoch 演化）、train_evaluator_weights.py（OLS 权重拟合）。都支持 --dry-run / --apply，逻辑闭环。
* 项目无现成调度器（无 APScheduler/cron 库）。lifespan 仅初始化，无周期任务。
* `backfill_engagement`（analyst.py:146）是现有事件触发点：发布后回灌 engagement 弱标签到 evaluator_samples。这是评估器拿到"真实反馈"的时刻。
* train_weights 需 MIN_TRAIN_SAMPLES=10 个带 engagement 标签样本才拟合；evolve 需有样本算 avg_bias_score。
* next_severity/avg_bias_score/create_epoch 已封装，脚本只是 CLI 包装。

## Assumptions (temporary)

* "在线"= 事件驱动（有新反馈时触发评估），不一定是高频周期轮询。
* 演化应幂等、非阻塞、失败降级（不阻断发布/分析主链路）。

## Open Questions

*（已全部收敛 — 默认采用推荐方案 A 推进）*

## Requirements

* 新增 `maybe_evolve(account_id)` 函数（evaluator_config.py）：检查自上次演化后是否攒够新带标签样本（阈值，可配），达阈值则触发 train_weights + next_severity/create_epoch；未达或失败则 no-op。幂等、非阻塞。
* 在 `backfill_engagement`（analyst node，发布后回灌 engagement）成功后，fire-and-forget `asyncio.create_task(maybe_evolve(account_id))` 触发，不阻塞 analyst→publish 主链路。
* 演化决策可观测：logger 记录触发/决策/结果。
* 触发逻辑直接调 evaluator_config 已封装函数（train_weights/next_severity/create_epoch/avg_bias_score），不 shell out 调 CLI 脚本。

## Decision (ADR-lite)

**Context**: 评估器 evolve/train 两脚本纯手动 --apply，不在线；RQGM 要根据真实反馈持续自我调整。项目无调度器。
**Decision**: Approach A — 事件驱动。在 backfill_engagement（拿到真实反馈的时刻）后 fire-and-forget 触发 maybe_evolve，达阈值才演化。零新基础设施，事件信号驱动（非时钟），最 RQGM-faithful。
**Consequences**: 仅在有发布反馈时演化（无新数据时不演化，可接受）；演化在请求路径但 fire-and-forget 不阻塞；需防重入/并发演化（同一 account 同时多次触发）。

## Acceptance Criteria

* [ ] maybe_evolve 函数：达阈值触发 train+evolve，未达 no-op，失败降级。
* [ ] backfill_engagement 后 fire-and-forget 触发，不阻塞主链路。
* [ ] 并发/重入保护：同 account 演化进行中不重复触发。
* [ ] 演化决策有日志。
* [ ] 测试：达阈值触发 / 未达不触发 / 失败降级 / 不阻塞。
* [ ] 不破坏现有 analyst backfill 链路。
* [ ] ruff/mypy/CI 绿（check + format --check 都跑）。

## Definition of Done

* Tests added/updated
* Lint/typecheck/CI green
* 演化决策可观测

## Out of Scope (explicit)

* 真正跑 LoRA finetune（finetune_evaluator.py --train，需 GPU）。
* DPO/reward 阶段。
* 跨进程分布式调度（单进程内触发即可）。

## Technical Notes

* 触发点候选：backend/agents/analyst.py backfill_engagement 后；backend/api/app.py lifespan。
* 演化核心函数已封装在 backend/db/evaluator_config.py（train_weights/next_severity/create_epoch/avg_bias_score），CLI 脚本只是包装——触发逻辑应直接调这些函数，不 shell out 调脚本。
