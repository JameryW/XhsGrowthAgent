# fix(checkpoint): WorkflowPhase/Mode msgpack allowlist + astream_events v2 + 冒烟删除重试（票 5ct）

> 真实工作流（CLI 与 API 都跑过）暴露的遗留问题：检查点里有 langgraph 不认识的枚举类型，
> 未来版本会拒绝加载旧线程；CLI 还在用已弃用的 `astream_events(v1)`；冒烟在 cancel 后
> 立刻 delete 会撞上 runner 收尾竞态。

## 1. 问题与证据

| # | 问题 | 证据 |
|---|---|---|
| 1 | 每次从检查点恢复都会告警 `Deserializing unregistered type backend.state.enums.WorkflowPhase … This will be blocked in a future version`（`WorkflowMode` 同样） | CLI 真实运行与 API 启动日志都反复出现；LangGraph 默认 permissive msgpack 对未知类型只告警，strict 模式会直接拒绝加载 → 现有线程将不可恢复 |
| 2 | `xhs-growth run` 用 `astream_events(..., version="v1")`，Python 侧报 `LangChainDeprecationWarning` | 真实 CLI 运行日志 |
| 3 | 冒烟在 `cancel` 之后立即 `DELETE /api/workflow/{id}`，runner 还没收尾 → 400 `Cannot delete a running workflow`，历史里留孤儿 | 生产路径冒烟两次出现 `workflow delete → HTTP 400` |

## 2. 修复

| 位置 | 变化 |
|---|---|
| `backend/state/checkpoint_serde.py`（新） | `checkpoint_serde()` 返回显式 allowlist 的 `JsonPlusSerializer`，只放行 `("backend.state.enums","WorkflowPhase")`、`("backend.state.enums","WorkflowMode")`；其余保持 langgraph 默认 |
| `backend/graph/builder.py` | dev SQLite / MemorySaver / prod Postgres 三个 checkpointer 全部注入该 serde（写入与读取一致） |
| `backend/cli/main.py` | `astream_events(..., version="v2")` |
| `scripts/functional_smoke.py` | `cancel` 后若 `DELETE` 返回 400，等 2s 重试一次，避免留下孤儿历史 |
| `tests/unit/state/test_checkpoint_serde.py`（新） | 枚举 round-trip 且**不再产生 unregistered-type 告警**；allowlist 只包含两个枚举；MemorySaver 接受该 serde |
| `docs/deployment.md` | 检查点序列化 allowlist 说明 |

## 3. 验证

- 真实 CLI 运行（`run --niche 家居`，magpie）：exit 0，最终 `planning`；日志中
  `unregistered type` 与 `LangChainDeprecationWarning` **均消失**（切换前每次都有）。
- 生产路径 API（Postgres）+ 带凭据冒烟：**28 checks / 28 PASS / 0 FAIL**，服务端日志无
  unregistered-type 告警。
- 全量测试（开启 `XHS_PG_PARITY_URI`）：见 journal。

## 4. 已知观察（不在本票内）

- start 后 runner 写 checkpoint 期间 `/status`/`cancel` 在嵌入式 PG 上约 12.5s；功能正确，
  性能需在真实部署复核。
- 本地 Windows 上 pytest 打印 summary 后进程偶发不退出（非守护线程）；CI Linux 不受影响，
  属于本地运行环境观察。
- langgraph error 中 `another command is already in progress` 偶发（账号删除与 runner 收尾
  竞争），不影响响应。
