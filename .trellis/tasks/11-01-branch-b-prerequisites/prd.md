# P4 分支 B slice1：outcome 审计字段 + force seam（票 5bn）

> 分支 B 已获拍板实施（目标「完成所有剩余任务」），按 `docs/publish-action-protocol.md`
> 的 5 步方案分轮落地。本票是 **B1**：把"receipt 能否映射回 publish_result"与
> "force 语义能否对齐"这两块前置打通，**不切换 mainline 执行路径**。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 分支 B 需要把 executor 的 receipt 映射回 workflow 的 `publish_result` | 方案第 2/4 步 |
| `publish_result` 使用 `published_at`/`error_type`/`recovery`/`result_known`，而 `PublishOutcome` 只带 status/note/error/retry | `agents/publisher.py` vs `execution.PublishOutcome` |
| `EffectLedger.begin` 支持 `force=True` | `backend/state/effects.py` |
| mainline 有 operator force-retry 语义；control-plane executor 没有 | `_run_publish_attempt` 的 `force_publish` |
| `execute_action` 是 mainline 未来的执行入口 | P4 方案 |

## 2. 决定（locked）

1. `PublishOutcome` 增加可选审计字段：`published_at`、`error_type`、`recovery`、
   `result_known`；`_outcome_from_status` 从平台 payload 读取（类型不合法则忽略）。
2. `_publish_receipt_result` 将上述字段写入 receipt.result（空值仍省略，沿用
   "absent ≠ empty" 规则）。
3. `execute_action(..., *, force: bool = False)`：force 只用于越过 effect-ledger 的
   blocking 状态；已有 receipt 仍原样返回；**不暴露到 HTTP API**（由 mainline 入口在
   operator force-retry 时传递）。
4. 本票不改 mainline dispatch（仍走 attempt），保持全量绿；B2/B3 后续切换。

## 3. 要求

1. `backend/creator_agent/execution.py`：outcome 字段 + `_outcome_from_status` 读取。
2. `backend/creator_agent/advisor.py`：receipt extras；`force` 参数贯通
   `execute_action` → `_execute_publish` → `_publish_with_effect_ledger` → `begin(force=force)`。
3. 测试：
   - receipt 携带 published_at/result_known（成功）与 error_type/recovery（失败）；
   - platform payload → outcome 的审计字段解析；
   - 已 UNKNOWN 的 effect：无 force 拒绝，force 后 dispatch 一次、receipt succeeded、
     ledger CONFIRMED、attempt=2。
4. 文档：`publish-action-protocol.md` 分支 B 段记录 B1 落地与剩余 B2/B3。
5. 验证：creator_agent + API + 全量 + ruff + docs gates 绿。

## 4. 结果（2026-11-01）

- [x] outcome/receipt 审计字段
- [x] force seam（operator-only，默认 off）
- [x] 新增 5 个用例；定向 251 passed；全量见 notes

## 5. 不做什么

- 不切换 mainline 执行段（B3）；不改 HTTP API；不改 ledger 状态机。
