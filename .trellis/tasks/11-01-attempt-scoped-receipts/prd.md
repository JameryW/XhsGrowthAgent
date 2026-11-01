# P4 分支 B 前置：receipt 改为 attempt 级（票 5bq）

> 分支 B B3 核查发现：控制面 receipt 是「每 intent 一条、失败也终态」，而主链语义是
> 「KNOWN FAILED 可重试」。拍板走**路径 1：attempt 级 receipt**。本票只做 receipt
> 域模型/存储/执行语义，不改主链 dispatch（B3 仍在下一票）。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| `execute_action` 先查 receipt，存在即返回 | `advisor.execute_action` |
| receipt 主键 `(account_id, action_id)` | Postgres `PRIMARY KEY (account_id, action_id)` + 内存 dict 同键 |
| 主链 KNOWN FAILED 可重试（账本 FAILED 非 blocking） | `backend/state/effects.py` BLOCKING_STATUSES；harness F2 |
| 分支 B 采用 attempt 级 receipt（用户裁决） | 本会话目标轮问答 |

## 2. 决定（locked）

1. `ActionExecution.attempt: int = Field(default=1, ge=1)`；rest 字段不变。
2. 存储主键 `(account_id, action_id, attempt)`：
   - 内存适配器 key 改三元组；
   - Postgres 建表含 `attempt` 列 + 三列主键；旧库用**幂等迁移**：加列 → 检查主键定义
     （含 attempt 则跳过）→ drop/add 主键；
   - 插入 `ON CONFLICT (account_id, action_id, attempt) DO NOTHING`，回读按 attempt。
3. `get_action_execution(account, action, attempt=None)`：默认返回**最新** attempt
   （兼容旧调用/API），显式 attempt 精确读取。
4. `execute_action` 语义：
   - 最新 receipt 为 **FAILED** → 允许无 `force` 重试（新 attempt，重新 dispatch）；
   - 最新 receipt 为 **SUCCEEDED/UNKNOWN** → 仍终态，原样返回；
   - 显式 `force=True` → 无论状态都新 attempt 重执行（operator 语义）。
5. 每次执行写各自 attempt 的 receipt；`execution_id` 仍为独立 uuid。

## 3. 要求

1. `backend/creator_agent/models.py`：`attempt` 字段 + 注释。
2. `backend/db/creator_agent.py`：内存 key、get/create、建表 SQL、幂等迁移。
3. `backend/creator_agent/repository.py` + `advisor.py`：签名透传 attempt。
4. `docs/publish-action-protocol.md`：记录裁决落地。
5. 测试：失败无 force 可重试（attempt 1→2、ledger CONFIRMED）、成功无 force 终态、
   force 在成功后重执行（attempt 2）。

## 4. 结果（2026-11-01）

- [x] 域模型/内存/Postgres 适配器同步
- [x] 迁移幂等（旧库加列并替换主键；新库建表即三列主键）
- [x] 三个执行语义用例通过；定向 `creator_agent + db + api creator_agent + contract` 469 passed
- [x] 全量结果见 notes

## 5. 风险/边界

- 本地无 Postgres 实例：迁移 SQL 只由 CI 的 parity 套件覆盖，本地不可验证。
- 控制面 API 行为变化：FAILED 的 intent 再次 execute 会真正重执行（与账本语义一致），
  需要 B4 在文档/claim 中收口。
- 未改主链 dispatch（B3 下一票）。
