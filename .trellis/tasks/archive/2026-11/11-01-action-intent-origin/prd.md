# P1b-1：控制面意图身份模型泛化（origin + mainline 空 creator/audience）（票 5bb）

> 上下文：P1b（见 `docs/publish-action-protocol.md`）卡在身份模型上——`ActionIntent`
> 需要 `creator_id`/`audience_id`/`decision_id`，而主链只有「工作流 + 人工审批」，
> 没有 creator/audience。本票落地 **Option A 的模型半步**：让 durable intent 能诚实地
> 表达「这是主链产生的」而不借用创作者身份。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| `ActionIntent` 原先强制 `creator_id`/`audience_id` 非空 | `backend/creator_agent/models.py`（min_length=1） |
| 唯一构造点在控制面 advisor | `backend/creator_agent/advisor.py` 的 `plan_action`（`action = ActionIntent(...)`） |
| 存储是整行 `payload_json`，不是分列 | `backend/db/creator_agent.py` 的 `creator_agent_actions` 表（account_id/action_id/status/payload_json…） |
| 读侧用 `ActionIntent.model_validate(payload)` | `_action_from_row` |
| 主链没有 DecisionRecord（creator_agent 概念：audience/model_revision/ranked candidates） | 发布链路与 `DecisionRecord` 字段 |

## 2. 决定（locked，Option A 的窄版本）

1. 新增 `ActionOrigin`（`creator` / `mainline`）；`ActionIntent.origin` 默认 `creator`，
   **旧行（无 origin 键）读作 creator**，不重写任何 durable 行。
2. `creator` origin：`creator_id`/`audience_id` 必须非空（保持既有语义）。
3. `mainline` origin：二者必须为空 —— 主链不得借用创作者身份；由模型校验在边界拒绝。
4. 存储无需列迁移（`payload_json` 自解释）；`ActionIntentRequest` 与公开 API 不变。
5. 唯一构造点仍是 advisor —— `action_intent_construction_sites` 保持 `1`；
   `mainline_action_intent_producers` 保持 `0`（本票不构造 mainline intent）。

## 3. 要求

1. `backend/creator_agent/models.py`：`ActionOrigin` + `ActionIntent` 字段与校验；
   `creator_agent/__init__.py` 导出。
2. 测试 `tests/unit/creator_agent/test_action_intent_origin.py`：
   - creator 缺任一 id → 拒绝（含纯空白）；
   - mainline 空双 id → 接受；mainline 携带任一 id → 拒绝；
   - 旧 payload（无 origin）→ creator；
   - 真仓库往返保留 origin（mainline 与 creator 两种）；
   - 序列化行包含 origin。
3. 文档：`docs/publish-action-protocol.md` 的 P1b 段落记录「A 的模型半步已落地」与
   剩余 P1b-2；不改 claim 数值。
4. 验证：`tests/unit/creator_agent`、`tests/unit/api`、`tests/contract`、doc gates 绿；
   ruff/format 绿。

## 4. 结果（2026-11-01）

- [x] `origin` 模型 + 校验 + 导出；旧行兼容
- [x] 真仓库（内存回退）往返保留 origin 与空 creator/audience
- [x] creator_agent 197 passed；api+contract 712 passed；doc gates 12 passed；ruff 绿
- [x] 全量 pytest 4741→（本票后）待跑：见 task.json notes

## 5. 不做什么

- 不产生 mainline decision 记录、不在主链构造 intent（P1b-2）。
- 不改 `ActionIntentRequest`/公开 API/执行器语义；不动 DB 列。
