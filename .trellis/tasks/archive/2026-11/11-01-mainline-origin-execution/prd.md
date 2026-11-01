# P3b-1：控制面执行器支持 mainline-origin intent 与回执（票 5bf）

> P3 要把主链/retry/free 三条 `run_publish` 直调接到控制面执行器
> （`CreatorAdvisor.execute_action`）。切换前必须先让执行器能执行 P1b-2 产出的
> `origin=mainline` intent —— 那类 intent 没有 `DecisionRecord`，而当前执行器强制
> 加载它、回执也强制携带 creator 身份。本票补上这条能力，不动三条直调。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| mainline intent 由 review 审批产生，`status=CONFIRMED` | 票 5bc（`record_mainline_publish_intent`） |
| 执行器当前强制 `get_decision(action.decision_id)`，缺失即拒 | `advisor.execute_action` |
| 回执模型强制 creator/audience/`model_revision>=1` | `models.ActionExecution` |
| 仓库写回执时再查 DecisionRecord 并比对 model_revision | `db/creator_agent.create_action_execution`（memory + postgres 两处） |
| 仓库已有同 action 幂等（先查已有回执直接返回） | `execute_action` 开头 + 仓库 `ON CONFLICT DO NOTHING` |
| 执行器只对 PUBLISH 调 dispatcher，其余 capability 按未接线拒绝 | `execute_action` 分支 + `ActionCapabilityNotWiredError` |

## 2. 决定（locked）

1. `ActionExecution` 新增 `origin: ActionOrigin = CREATOR`；`creator_id`/`audience_id`
   默认空串，`model_revision: int | None = None`。校验：
   - creator origin：三者必须齐（`model_revision` 非 None，且 `>=1`）；
   - mainline origin：三者必须空/None（不借创作者身份；`None` 而非 0，0 会和真实
     revision 撞车）。
2. `execute_action`：
   - `origin=mainline` → **不加载** `DecisionRecord`（审批身份就是 `decision_id`）；
   - mainline 只允许 PUBLISH；其他 capability 抛 `ActionCapabilityNotWiredError`，
     **不产生回执**（与既有 “未接线必须吵” 一致）；
   - 回执经单一 `_record_execution(action, result=..., decision=..., publish_outcome=...)`
     写入，两种 origin 共用一条持久化路径。
3. 仓库 `create_action_execution`：mainline-origin 跳过 DecisionRecord 查询/比对；
   其余语义（intent 必须 CONFIRMED、`_validate_action_execution_source`、
   同 action 幂等返回同一回执）保持不变。
4. creator_agent 既有行为逐字段不变；**三条直调不动**，claim 仍 `3`。

## 3. 要求

1. `backend/creator_agent/models.py`：`ActionExecution` 字段 + 校验。
2. `backend/creator_agent/advisor.py`：mainline 分支、单一回执写入点、import `ActionOrigin`。
3. `backend/db/creator_agent.py`：mainline-origin 跳过 decision provenance（memory + postgres）。
4. 测试 `tests/unit/creator_agent/test_mainline_execution.py`：
   - 主链 intent 执行一次 → mainline 回执（origin/空 creator/None model_revision/
     decision_id/status/note_id），dispatcher 收到正确的 PublishRequest；
   - 二次执行返回同一回执且只 dispatch 一次；
   - 失败发布 → FAILED 回执；
   - 非 publish / 非 CONFIRMED 的 mainline intent 被拒且无回执；
   - 回执模型拒绝混合身份（mainline 带 creator/model_revision；creator 缺三者）。
5. 文档：`docs/publish-action-protocol.md` 记录 P3b-1 与剩余 P3b-2；claim 不变。
6. 验证：creator_agent/db/api/contract 定向 + 全量 + ruff 绿。

## 4. 结果（2026-11-01）

- [x] 执行器 mainline 分支 + 单一回执写入点 + 仓库 provenance 分支
- [x] 7 个新用例；creator_agent 既有 204 用例全绿
- [x] 定向（creator_agent+db+api+contract）1079 passed
- [x] claim 仍 3；全量见 notes

## 5. 不做什么

- 不切三条直调（P3b-2）、不动 `EffectLedger` 六态/幂等语义、不改公开 API。
- 不把 mainline intent 的创建提前到审批点以外（P1b-2 的边界不动）。
