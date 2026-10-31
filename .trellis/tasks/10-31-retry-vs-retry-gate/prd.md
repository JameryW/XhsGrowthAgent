# 重试撞重试串行化闸门（票 5an）

> 来源：`docs/execution-plane.md` §7.1「留给下一任务的输入（一条）」——
> “重试撞重试仍没有闸门……要问的是：一个既不该进槽、又该被守卫看见的任务，
> 需要什么形状的表？未量。” 本票补上这张表和它的守卫。

## 1. 目标

同一进程内，两条修复路径（`retry_ripple_analysis` / `retry_publish`）互相看不见彼此，
两次重试可以同时在飞。本票让“线程上已有一次重试在起/在跑”成为两个入口守卫能看见的事实，
且**不**把任何表扩宽成通用 busy 谓词。

## 2. 已核实的现状（缺陷）

| 事实 | 证据 |
|---|---|
| 两个入口守卫都只读槽：`process_has_active_task` | `backend/api/routes/_wf_actions.py:101` / `:335` |
| ripple-retry 刻意不写槽，写 `_detached_tasks` | `_wf_actions.py:283-285`；`_runner.py:63-75` 的裁定注释 |
| `_detached_tasks` 的唯一读者是取消者，不回答“忙不忙” | `_runner.py:78-100`；claim `busy_answerers_reading_the_detached_registry = 0` |
| 租约分不开同进程两个持有者（`owner_id` 是进程） | `execution_plane.md` §7.1；`grant_paths_that_readmit_the_same_owner = 2` |
| 跨进程重试撞重试已被租约挡住（`HELD_BY_LIVE_OWNER` → stand down + 拒绝事件） | `_wf_actions.py:159-165` / `:450-459` |

⇒ 缺的只是**同进程**这一格，且不能靠槽、不能靠租约、不能靠把 `_detached_tasks`
接进 `process_has_active_task`（那会一次扩散到 12 个调用点，是 §7.1 明确拒绝的“换靶子”）。

## 3. 决定（locked）

| Topic | Choice |
|---|---|
| 表形状 | `_runner._retry_tasks: dict[str, asyncio.Task[Any]]` —— **每 thread 至多一个“正在起/在跑的重试”任务**；与槽（每 thread 一个**工作流**任务）和 `_detached_tasks`（**取消靶子**）是三个不同问题 |
| 领取 | `claim_retry(thread_id, task)`：同步 check-and-set；调用点紧贴 `create_task`，**中间没有 await**，因此两个并发请求不可能都领到 |
| 失败方处理 | 领不到 → `task.cancel()`（协程尚未获得执行权，零副作用）→ 返回 `skipped` |
| 清理 | 登记时挂 done callback（在 `_runner` 内），`is` 身份守卫后 pop —— 取消/异常/正常结束都覆盖（`cancel()` 后协程的 `finally` 可能根本不执行） |
| 谓词 | `retry_in_flight(thread_id)`：只被两个重试入口读；**不** OR 进 `process_has_active_task` / `has_active_execution` |
| 拒绝文案 | 与既有守卫同一句 `工作流正在运行，无法重试。`（`repair_paths_using_the_shared_serialization_sentence = 2` 保持） |
| 方向 | 仍只挡「重试撞本进程的执行/重试」，不挡反向「执行撞重试」（既有裁定：`_start_resume_task` 取消槽占位者，ripple-retry 由 `cancel_detached_and_wait` 取消） |

## 4. 要求

1. `backend/api/routes/_runner.py`：新增 `_retry_tasks`、`retry_in_flight`、`claim_retry`（含 done callback 清理），docstring 写明它**不是**第三个“忙不忙”答者、为什么不进槽。
2. `backend/api/routes/_wf_actions.py`：两个入口守卫加 `or _runner.retry_in_flight(thread_id)`；在各自 `create_task` 之后、写注册表之前 `claim_retry`；领不到 → cancel + `skipped`。
3. 测试 `tests/unit/api/test_retry_vs_retry_gate.py`：
   - ripple in-flight 时第二次 ripple-retry → skipped，且只起 1 个任务；
   - publish-retry in-flight 时 ripple-retry → skipped；ripple-retry in-flight 时 publish-retry → skipped（两个方向）；
   - 任务结束后表项被清、下一次重试可再起（正常结束与 cancel 两条路径）；
   - `retry_in_flight` 不进 `process_has_active_task` / `has_active_execution`（静态断言或行为断言）；
   - 两个并发入口只有一个领到（用事件 rendezvous，不用时钟）。
4. `docs/execution-plane.md`：§7.1 把“留给下一任务的输入”改为“已结掉”，写清表形状、领到的保证、没关掉的方向与跨进程边界；§7 claim 表新增可重算值（表的写点/读者/守卫数），并同步 `tests/unit/scripts/test_execution_plane_claims.py` 的 `_CLAIMS`。
5. `ruff check` / `ruff format --check` / 定向 pytest 绿；既有 claim 值不得漂移（`busy_answerers_reading_the_detached_registry` 仍为 0）。

## 5. 验收

- [ ] 两次 ripple-retry 只有一次落任务（行为测试）
- [ ] ripple ↔ publish 两个方向互斥（行为测试）
- [ ] 任务正常结束 / 被 cancel 后都能重试（清理正确）
- [ ] 通用 busy 谓词未被扩宽（claim 值 0 + 静态断言）
- [ ] execution-plane claim 表与 `_CLAIMS` 双向一致（`test_execution_plane_claims.py` 全绿）
- [ ] `ruff check` / `ruff format --check` 绿
- [ ] 突变自检：删掉 claim 调用 / 让两个入口共用一个永久占位 / 去掉 done callback 清理 → 对应断言分别变红

## 6. 不做什么

- 不改租约粒度与接管语义（§6 已裁定：改它 = 改整个执行平面）。
- 不改 `_detached_tasks` 的读者口径（取消者仍只有它一个）。
- 不做跨进程重试声明（租约已覆盖；再做一层会是第二套真相）。
- 不做 Run 级预算、不做 attempt 级重放（§4.1 / §8 F7 边界不变）。
