# Run 身份协议（agent-os 矩阵行 2 的 Run 缺口）

> 状态：实现中（票 5x）。来源：`docs/agent-os-upgrade-2026q4.md` §2「五实体映射与缺口」——
> Task/Step/Attempt/Effect 有；**Run 缺**。票 5w 明确「不补 Run 实体……Run 缺口单独登记」。
> 本票只补 **Run**：让 resume 与 rerun 能从 `run_id` 区分。

## 1. 目标

给同一个 `thread_id`（Task）上的一次执行生命周期一个**有名字、可查询的 Run 实体**：

- `/start` 铸造第一个 `run_id`（`run_seq=1`），写入初始 state，并 emit `kind:"run"` 事件；
- gate / pause / error / stale 的 **resume** 与 `/recover` **复用**现有 `run_id`（不铸造、不强制新事件）；
- completed / cancelled 上的 **terminal restart**（现有 `/resume` 路径把 phase 拉回 SCOUTING）铸造**新** `run_id`（`run_seq += 1`），emit 新 `kind:"run"` 事件；
- `/status`（以及 start/resume 响应）回显当前 `run_id` / `run_seq` / `run_cause`，使观测面能区分「同一次执行的继续」与「同 thread 的重开」。

## 2. 不变量

1. **Task ≠ Run**：`thread_id` 仍是 Task；`run_id` 是 Task 内一次执行。同一 thread 可有多次 Run。
2. **Attempt / Effect 不混用**：Run 是执行生命周期；Attempt 仍是节点内 LLM 尝试；外部副作用仍由 Effect 账本负责。
3. **数据最小化**：run 事件不含 goal/brief/content；只留身份、cause、seq、时间。
4. **确定性 id**：`run_id` 由 `(thread_id, run_seq, started_at)` 派生（`run_` + sha256[:16]）；同输入同 id；`run_seq` 不同必不同 id。
5. **封闭 cause 词表**：`start / resume / rerun / recover`。
   - `start`：`POST /start` 铸造
   - `rerun`：terminal restart 铸造
   - `resume` / `recover`：复用既有 run（事件可选；本票对复用路径**不强制**再写一条 run 事件，避免把「继续」误读成「新开」）
6. **零控制流变更**：不改变 pause/gate/error/recover 的图重入语义；只在铸造点写入 `run_id`/`run_seq`/`run_cause` 并 emit 遥测。
7. **legacy 兼容**：旧 checkpoint 无 `run_id` 时，status 回显 `run_id=null`（或空）；第一次需要铸造的路径（新 start，或 terminal rerun）再写入——不在每次 resume 上偷偷回填，以免把「旧执行」伪装成「新 Run」。

## 3. 落点

| 文件 | 变更 |
|------|------|
| `backend/state/runs.py` | 新纯库：`RunCause`、`run_id`、`run_entry`、`next_run_seq` |
| `backend/state/events.py` | `RUN_EVENT_KIND = "run"` |
| `backend/db/workflow_events.py` | `EVENT_KINDS` 增 `"run"` |
| `backend/state/schema.py` | `run_id` / `run_seq` / `run_cause` 字段 |
| `backend/state/goal.py` | `compile_initial_state` 铸造 `run_seq=1` + `run_id` + `run_cause=start` |
| `backend/api/routes/_wf_application.py` | start 后 emit run 事件；terminal restart 铸造新 run 并 emit；status/start/resume 响应带 `run_id` |
| `docs/agent-os-upgrade-2026q4.md` | §2/§3 行 2 改「Run 有」；新增 §5.10 落地记录 |

## 4. 验收

- `tests/unit/state/test_runs.py`：词表封闭、id 确定性（含 seq）、校验、字段白名单、无内容字段、`next_run_seq`。
- `tests/unit/state/test_goal.py`：初始 state 含 `run_id`/`run_seq=1`/`run_cause=start`。
- 应用层测试：terminal restart 铸造新 `run_id` 且 `run_seq` 递增；pause/error resume **不**改 `run_id`。
- 突变自检：删 run 记录、resume 与 rerun 共用 id、id 不含 seq、cause 词表漂移、events 未注册 run → 断言红。
- `ruff` / `mypy backend` / 相关单测绿。

## 5. 不做什么

- 不做 Run 级预算字段（F7 SKIP 仍在；本票不借机编造 budget）。
- 不做 attempt 级重放（§4.1 判据未满足）。
- 不加独立 Postgres `runs` 表（事件 + checkpoint 字段足够；与 Attempt 一致）。
- 不改前端必接：响应多字段，旧客户端忽略即可（additive）。
- 不把 `/recover` 做成新 Run（它是同一次执行的恢复策略）。
