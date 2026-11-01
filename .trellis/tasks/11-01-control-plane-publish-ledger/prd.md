# 控制面 execute 路径接入 EffectLedger 六态账本（票 5bi）

> 背景：架构升级总表 row 5 的最后一条残留 —— `creator_agent` 控制面 `execute` 的
> publish 路径直连 Gateway，幂等只靠 `ActionExecution` receipt；而 receipt 是在平台
> 调用**之后**才写的。崩溃落在两者之间时，重试看起来像"从未尝试过"，可能**发两篇**。
> 本票把控制面 publish 也接到六态账本上，收掉这条残留。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 主链发布在 submit 前写 `EffectLedger` IN_FLIGHT，按结果结算 | `backend/agents/publisher.py` 的 `_write_publish_record`/`EffectLedger.begin` |
| 控制面 execute 先 dispatch、后写 receipt | `advisor._execute_publish` → `_publish` → `execute_action` 末段 `create_action_execution` |
| 账本状态机：PREPARED→IN_FLIGHT→CONFIRMED/FAILED/UNKNOWN，BLOCKING = IN_FLIGHT/CONFIRMED/UNKNOWN/RECONCILING | `backend/state/effects.py` |
| intent 的 `idempotency_key` 在仓库按 account 唯一 | `db/creator_agent` 的 `(account_id, idempotency_key)` 唯一约束 |
| 现有 typed 409 映射模式 | `backend/api/errors.py` + `routes/creator_agent.py` 的 `execute_creator_action` |

## 2. 决定（locked）

1. **账本在 dispatch 前 claim、dispatch 后结算**：
   `_execute_publish` 末尾改为 `_publish_with_effect_ledger(action, request)`：
   - `EffectLedger.begin(effect_id, tool_name="xhs.publish", task_id=action_id, request_digest=content_hash)`；
   - 已处于 blocking 状态 → `ActionPublishAlreadyAttemptedError`（dispatch 0 次）；
   - dispatcher 正常返回 → 按 outcome mark：PUBLISHED→CONFIRMED、UNKNOWN→UNKNOWN、FAILED→FAILED；
   - dispatcher **抛异常** → mark UNKNOWN（绝不用 FAILED；异常可能发生在提交之后）后原样抛出。
2. **账本 key 与主链账本分离**：新 namespace `("publish","intent_effects")`，effect_id =
   `f"{account_id}::{idempotency_key}"`。主链按内容哈希 `publish_id` 记账，控制面按调用方
   idempotency_key 记账；共用 key 空间会让无关字符串与内容哈希互撞。
3. **typed 拒绝**：`ActionPublishAlreadyAttemptedError(action_id, account_id, prior_status)`
   → API `CreatorActionPublishAlreadyAttemptedError` 409
   `ERROR_CREATOR_ACTION_PUBLISH_ALREADY_ATTEMPTED`，details 带 prior_status；
   同其他 pre-Gateway 拒绝一样写 `publish_blocked` 事件（reason=duplicate_publish）。
4. **store 缺失时**（`artifact_store=None`）：发布会在读 artifact 时先被拒，不会到达
   ledger；ledger 只在有 store 时启用，不用"空账本"假装保护。
5. 不做自动对账：IN_FLIGHT/UNKNOWN 的后续处理与主链一致（需人工/对账流程），
   typed 拒绝即提示先对账。

## 3. 要求

1. `backend/creator_agent/execution.py`：`PUBLISH_EFFECT_NAMESPACE`、`publish_effect_id`。
2. `backend/creator_agent/repository.py`：`ActionPublishAlreadyAttemptedError` + `__all__`。
3. `backend/creator_agent/advisor.py`：`_effect_store`、`_publish_with_effect_ledger`。
4. `backend/creator_agent/__init__.py`：导出新错误。
5. `backend/api/errors.py` + `backend/api/routes/creator_agent.py`：ErrorCode/APIError/映射 +
   `publish_blocked` 事件。
6. 测试：`tests/unit/creator_agent/test_publish_effect_ledger.py`（dispatch 前 IN_FLIGHT、
   结算三态、异常→UNKNOWN+无 receipt、crash-window 重试被拒、prior UNKNOWN 拒绝、
   effect id 按账号作用域）；`tests/unit/api/test_creator_agent.py` 增加 409 映射用例。
7. 文档：`docs/agent-os-upgrade-2026q4.md` row 5 与「接入边界」披露更新（残留收口）。

## 4. 结果（2026-11-01）

- [x] 控制面 publish 走六态账本；crash-window 不再可能二次提交
- [x] typed 409 + `publish_blocked` 事件；无 receipt 时拒绝先于 dispatch
- [x] 单测 8 个 + API 映射 1 个；全量见 notes

## 5. 不做什么

- 不自动对账 IN_FLIGHT/UNKNOWN；不改主链账本/六态语义；不改公开 intent API 形状。
