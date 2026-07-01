# 评估器演化决策 realtime 可观测

## Goal

让 RQGM 评估器的协同演化决策可被前端/omp 实时观测。当前 maybe_evolve 演化发生时（权重 refit / prompt epoch 推进）只 logger.info，无 realtime 事件——评估器"自我改进"了但无人可见，违反 RQGM 的可审计性（verifiable metric + judge signal 必须可查）。

## What I already know

* EventType 是 StrEnum（backend/realtime/events.py），前后端同步（frontend/src/realtime/events.ts）。
* 现有类型：WORKFLOW_*/REVIEW_*/RIPPLE_PROGRESS/ANALYTICS_*。无评估器演化专属事件。
* evaluator_node 已 emit WORKFLOW_DATA_UPDATED（data_type=evaluation_result）。
* maybe_evolve（evaluator_config.py）演化时只 logger.info，不 emit。它在 analyst_node 的 fire-and-forget task 里跑（thread_id 可得）。
* EventBusService.emit(event_type, thread_id, payload)，thread_id=None 表全局事件。
* 前端有 realtime websocket + missed-events 补传。

## Assumptions (temporary)

* 演化是低频事件（攒够样本才触发），值得专门事件让前端提示。
* 演化可能跨 thread（account 级），但触发源于某次发布的 thread。

## Open Questions

*（已全部收敛 — 默认采用推荐方案 A 推进）*

## Requirements

* 新增 `EventType.EVALUATOR_EPOCH_EVOLVED = "evaluator.epoch_evolved"`（backend StrEnum + frontend events.ts 同步）。
* `maybe_evolve` 演化发生时（action=="evolved"）emit 该事件；skip/error 不 emit（避免噪声）。
* payload：account_id、epoch {from, to, created}、weight_training {applied, n_samples, r_squared}、bias_avg、thread_id（触发发布的 thread，None 表全局）。
* 复用 maybe_evolve 已有 report dict 构造 payload。

## Decision (ADR-lite)

**Context**: maybe_evolve 演化只 log，前端/omp 看不到；RQGM 要求演化决策可审计。
**Decision**: Approach A — 新增专属 EVALUATOR_EPOCH_EVOLVED 事件类型。与 REVIEW_*/ANALYTICS_*/RIPPLE_* 各有专属类型一致；演化是低频高信号事件，值得独立通道。skip/error 不 emit。
**Consequences**: 前后端 EventType 各加一行；消费方需识别新类型。复用 WORKFLOW_DATA_UPDATED 会混淆语义（fire-and-forget account 级演化不是 workflow 状态更新）。

## Acceptance Criteria

* [ ] backend EventType + frontend events.ts 同步新增 EVALUATOR_EPOCH_EVOLVED。
* [ ] maybe_evolve evolved 路径 emit 事件，payload 含 epoch/权重/bias/account 信息。
* [ ] skip 路径（below threshold / already-evolving）不 emit。
* [ ] error 路径不 emit（失败降级只 log）。
* [ ] 测试：evolved emit / skip no-emit / error no-emit。
* [ ] ruff/mypy/CI 绿（check + format --check 都跑）。

## Definition of Done

* Tests added/updated
* Lint/typecheck/CI green
* 前后端类型同步

## Out of Scope (explicit)

* 前端 UI 展示演化提示（toast/通知）——后续可加，本任务只保证事件可送达。
* 演化历史持久化查询端点（已有 evaluator_prompt_epochs 表 + list_epochs）。

## Technical Notes

* 涉及：backend/realtime/events.py（EventType）、backend/db/evaluator_config.py（maybe_evolve emit）、frontend/src/realtime/events.ts（EventType 同步）。
* maybe_evolve 已有 report dict，payload 直接用。
