# 评估器 epoch 历史 omp 可见

## Goal

让评估器的 prompt epoch 演化历史对 omp 操作者可见。当前 list_epochs 后端函数存在但无 HTTP 端点、无 omp 工具——评估器自我演化（refit 权重、推进 epoch）后，用 omp 的人看不到当前 epoch 状态/历史，演化黑箱。

## What I already know

* `list_epochs()`（evaluator_config.py:663）返回 `list[PromptEpoch]`（epoch_id/bias_severity/note/active/created_at），`get_active_epoch()` 返回当前 active。
* HTTP evaluation 端点有 /result /run /weights /samples /trend，**无 /epochs**。
* omp 有 evaluation_result/evaluation_run 工具，**无 epoch/weights 查看工具**。
* omp 工具模式：TS 文件 register(pi) + pi.zod schema + HTTP get/post + textResult（见 evaluation_result.ts）。
* #162 加了 EVALUATOR_EPOCH_EVOLVED realtime 事件，但 omp 走 HTTP 不订阅 ws，看不到。

## Assumptions (temporary)

* omp 操作者需要：看当前 active epoch + 演化历史（哪个 epoch、bias_severity、note、何时创建）。
* 暴露已有 list_epochs 即可，无需新逻辑。

## Open Questions

*（已全部收敛 — 用户选方案 3：epoch+weights+samples+trend 全暴露给 omp）*

## Requirements

* 新增 HTTP `GET /evaluation/epochs` 端点（包 list_epochs，含 active 标记）。其余 /weights /samples /trend 端点已存在。
* 新增 4 个 omp 工具（均走 HTTP 拉取，复用现有端点）：
  - `xhs_evaluation_epochs`：当前 active epoch + 演化历史（epoch_id/bias_severity/note/active/created_at）。
  - `xhs_evaluation_weights`：当前有效权重（包 /weights，含 is_default 标记）。
  - `xhs_evaluation_samples`：最近训练样本（包 /samples，可选 account_id/limit）。
  - `xhs_evaluation_trend`：评估趋势时序 + 维度均值（包 /trend，可选 account_id/limit）。
* 每个工具 textResult 渲染 + 空数据空状态。
* omp 工具注册到 tools index。

## Decision (ADR-lite)

**Context**: 评估器演化（epoch/权重/样本/趋势）对 omp 全黑箱——后端函数/HTTP 端点大多有，但 omp 无工具。#162 realtime 事件 omp 也不订阅（走 HTTP）。
**Decision**: 方案 3 — 全暴露。补 /epochs 端点 + 4 个 omp 工具（epochs/weights/samples/trend），让 omp 操作者一次看清评估器演化全状态。weights/samples/trend 端点已存在，只需包 omp 工具；epochs 需补端点。
**Consequences**: 4 个 omp 工具（同模板，低边际成本）；omp 仍走 HTTP 拉取（不订阅 ws，架构不变）；样本/趋势是调试数据也暴露，但用户明确要全可见。

## Acceptance Criteria

* [ ] GET /evaluation/epochs 端点 + 后端单测。
* [ ] 4 个 omp 工具（epochs/weights/samples/trend）+ TS 类型。
* [ ] omp 注册到 tools index。
* [ ] 每个工具有空数据空状态。
* [ ] ruff/mypy/CI 绿 + omp tsc 绿。

## Definition of Done

* Tests + lint/typecheck/CI green
* 4 omp 工具注册

## Out of Scope (explicit)

* omp 订阅 realtime ws（omp 走 HTTP 拉取，架构不变）。
* 前端 epoch/weights 展示 UI（前端是另一条线）。
* 写端点（epoch/权重/samples 全只读）。
* 修改 epoch 的 omp 工具（只读可见）。

## Technical Notes

* 涉及：backend/api/routes/evaluation.py（新 /epochs 端点）、backend/omp/extensions/xhsagent-ext/src/tools/evaluation_{epochs,weights,samples,trend}.ts（4 新工具）、omp tools index 注册、tests/unit/api/test_evaluation_epochs.py。
* list_epochs/get_active_epoch/list_weights/export_samples/fetch_trend 已封装。
* omp 工具模板见 evaluation_result.ts：register(pi) + pi.zod schema + HTTP get + textResult。
