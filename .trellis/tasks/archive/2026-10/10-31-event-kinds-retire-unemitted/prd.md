# EVENT_KINDS 收口：退休从未发射的 `cost` / `error`（票 5ao）

> 来源：`docs/publish-action-protocol.md`「已知残留」第二条 —— “`EVENT_KINDS` 的
> `cost` / `error` 仍无发射者……读者不会替发射端兜底”。这是核验后剩下的唯一
> **无票、无触发条件**的声明性缺口。

## 1. 目标

让 `EVENT_KINDS` 这个声明集**等于发射端真的会产出的集合**：把从未有过发射者的
`cost`、`error` 两条 kind 退休，并用测试钉住“退休是故意的”。

## 2. 已核实的事实

| 事实 | 证据 |
|---|---|
| `cost` / `error` 自 P1a 起就在声明集里，注释称 “forward-looking, later slices will start emitting” | `backend/db/workflow_events.py` 的 `EVENT_KINDS` 注释 |
| 仓内**从未**有 `kind:"cost"` / `kind:"error"` 的写入：`git log -S'"kind": "cost"' -- backend`、`-S'"kind": "error"'` 均零命中 | 本次实测 |
| 成本已有权威载体：每次 LLM 调用发 `kind:"llm"` 条目并带 `cost_usd`；`/analytics/costs` 从 `llm`/`ripple` 聚合 | `backend/agents/nodes/_base.py::llm_perf_entry`；`backend/services/analytics.py` 的 cost 读侧 |
| 错误的实时通道是 realtime `EventBusService.WORKFLOW_ERROR`；持久面是 `kind:"node"` 条目的 `status`/`error` | `backend/agents/nodes/_base.py::emit_error_event`；`node_perf_entry` |
| `signal_inventory` 只把**未声明**的 kind 报成声明漂移 —— “声明了但没人写”在它那里不可见 | `backend/services/signal_inventory.py`；`tests/unit/signal_inventory` |

## 3. 决定（locked）

**退休，而不是补发射者。** 补 `cost`/`error` 发射端会为同一事实造第二份真相：
成本会同时存在于 `llm.cost_usd` 与 `cost` 条目，错误会同时存在于 realtime 总线、
`node.error` 与 `error` 条目 —— 两个口径一旦漂移，读者无法判断哪个是权威（本仓
在 `EXECUTION_*`/`MULTI_*` 上已反复拒绝这种“第二套真相”）。权威载体已经在案，所以
让声明集追上发射面。

| Topic | Choice |
|---|---|
| 声明集 | `EVENT_KINDS` 去掉 `"cost"`、`"error"`（13 → 11） |
| 防复发 | 新增测试把**完整声明集**钉成字面量；将来要加 kind 必须同时改测试（= 有意识的决定） |
| 注释 | `workflow_events.py` 的 forward-looking 注释改为“已发射的集合 + 两条已在票 5ao 退休及原因” |
| 文档 | `docs/publish-action-protocol.md`「已知残留」第二条改为“已收口”，并写明两条的权威载体 |
| 读者面 | `signal_inventory` 逻辑不动；`event_kinds_readers_outside_its_defining_module = 1` 不变 |

## 4. 要求

1. `backend/db/workflow_events.py`：从 `EVENT_KINDS` 移除 `cost`/`error`；更新注释（为什么不在、权威载体在哪）。
2. 新增 `tests/unit/db/test_workflow_events_kinds.py`：断言声明集恰为 11 条字面量；断言 `cost`/`error` 不在集合里（“退休是故意的”，防止有人顺手加回）。
3. `docs/publish-action-protocol.md`：已知残留第二条 → 已收口（票 5ao），写明 cost/error 的权威载体与新增的守卫测试。
4. `pytest`（signal_inventory、workflow_events、state/events、residue claims）+ `ruff check` / `ruff format --check` 绿。

## 5. 验收

- [x] `EVENT_KINDS` 恰为 11 条，且 `cost`/`error` 不在其中
- [x] 新增测试通过；`test_signal_inventory.py`（它遍历整个 `EVENT_KINDS`）仍绿（41 passed，2 个 tmp_path ERROR 为沙箱环境性）
- [x] 文档“已知残留”不再声称两条开放；claim `event_kinds_readers_outside_its_defining_module` 仍为 1（重算通过）
- [x] 突变自检：把 `"cost"` 加回 `EVENT_KINDS` → `test_the_declared_vocabulary_is_exactly_the_pinned_set` 与 `test_the_retired_kinds_stay_retired` 双双变红；恢复后绿

## 6. 不做什么

- 不新增 `kind:"cost"` / `kind:"error"` 发射端（理由见 §3）。
- 不动 realtime `WORKFLOW_ERROR` 通道与 `/analytics/costs` 读侧。
- 不重新编号/重排 `EVENT_KINDS` 的其余成员。
