# prd：两条修复路径取不取租约——以及 §7 的判据圈错了集合

> 票 `09-19-repair-paths-lease-verdict` · 分支 `feat/repair-paths-lease-verdict` · 基线 `4471e0fa`
> 前置：`docs/execution-plane.md` §2/§7（#631 钉数值、#632 钉形状、#634 钉守卫与登记表裁定）
> 交付：PR **#635** · commit `436f4f73` · CI 8/8

## 0. 这一片要回答什么

§7 的「留给下一任务的输入」只有一条，且它宣称代价是量过的：

> **给这两条路径取租约，或给 ripple-retry 一个自己的键。** 需要先决定拒租时是「照跑」还是
> 「拒绝」，即重新回答一次裁定 2 在修复路径上的适用性。今天的形状是：
> `backend/api/routes/_wf_actions.py` 里 `start_lease` 调用 **0** 处，直接 `aupdate_state` **3** 处。
> 改完之前，「执行撞重试」这个方向没有闸门。

三段话里有三个可检验的东西：**「两条」这个集合靠什么圈出来**（§3）、**拒租谁说了算**（§4）、
**「改完之前没有闸门」的因果对不对**（§4 第 2 行）。本片把三问都答掉，并**同时推翻其中两条**：

- §7 用的判据（「直接写 checkpoint、不取租约」）对树里 **20** 处成立 —— 它圈不住自己点名的 2 处；
- 「取租约」与「给一个自己的键」不是**替代**关系（§7 写的是「或」），它们关的是**两个不同的洞**；
- 「改完之前没有闸门」这句只对一半：「取租约」关掉的是**修复先到**那一侧，而**扫描先到**那一格
  在裁定 2 之下**关不掉** —— 要关得先把两种拒绝分开，那是本片**登记不修**的第一条。

`_fence_on_lost_lease` 的取消靶子是 `asyncio.current_task()`（`_runner.py:373`），**不读登记表** ——
这条是「修复路径不必进槽也能被栅栏」的证据，也是本片裁定**不需要「自己的键」**来拿过期保护的原因。

## 1. 现状侦察表（每条都对树核过；行号是本片**动代码前**的值）

| # | 位置 | 事实 |
| --- | --- | --- |
| 1 | `backend/api/routes/_runner.py:390` | `_run_graph_and_persist`：唯一取租约的执行入口，12 个调用点 |
| 2 | `backend/api/routes/_runner.py:414-418` | 取租约：`with contextlib.suppress(Exception)` 里内联 import + `await start_lease(...)` |
| 3 | `backend/api/routes/_runner.py:421-423` | 装栅栏：`lease_heartbeat is not None` 才装 |
| 4 | `backend/api/routes/_runner.py:373` | ★ `owner = asyncio.current_task()` —— 栅栏的靶子**与登记表无关** |
| 5 | `backend/api/routes/_runner.py:477` | `if lease_lost.is_set(): raise` —— 被栅栏取消的执行**不写状态** |
| 6 | `backend/api/routes/_runner.py:570-583` | `finally`：先弹登记表（身份守卫）再 `await end_lease(...)` |
| 7 | `backend/api/routes/_wf_actions.py:112` | `_run_retry`（ripple-retry 的协程），`:191` 写 checkpoint，`:196` 起任务 |
| 8 | `backend/api/routes/_wf_actions.py:334` | `_run_publish_retry`，`:344` 写 checkpoint，`:376` 起任务并进槽 |
| 9 | `backend/api/routes/_wf_actions.py:304` | `retry_publish` 体内的 `force_publish` 写入（处理器体内，不是后台协程） |
| 10 | `backend/db/execution_leases.py:496` | `start_lease` 签名：拒租返回 `None`，**调用方照样跑**（裁定 2） |
| 11 | `backend/db/execution_leases.py:520-532` | `end_lease`：`heartbeat.cancel()` + `gather(return_exceptions=True)` + `release()` |
| 12 | `backend/db/execution_leases.py:206-223` | `_ACQUIRE_SQL`：`WHERE state <> 'held' OR owner_id = EXCLUDED.owner_id OR heartbeat_at + ttl <= now()` |
| 13 | `backend/db/execution_leases.py:535-550` | `thread_is_held`：`state is HELD and not is_stale(now)` —— 它**算**新鲜度而不是读 `state` |
| 14 | `backend/api/routes/_takeover.py:177` | `expire_scan()` 的调用点（在 `takeover_scan` 里） |
| 15 | `backend/api/routes/_takeover.py:127-134` | 节点安全闸门：`takeover_verdict(pending)` 不过 ⇒ `refused`，**不 acquire** |
| 16 | `backend/api/routes/_takeover.py:139` | 第二道闸门 `if not await acquire(thread_id)` |
| 17 | `backend/api/app.py:1357-1365` | 生产接线：`startup_takeover_scan(app)` + `create_task(takeover_scheduler(...))` |
| 18 | `backend/config/settings.py:91-92` | `takeover_enabled: bool = True` · `takeover_interval_seconds: float = 60.0` |
| 19 | `backend/state/machine.py:46-47` | `has_active_task` 只在**优先级 9/10**起作用：`stale` ↔ `running` |
| 20 | `backend/api/routes/_wf_application.py:1077` | `/recover` 只放行 `ERROR`/`STALE`，其余拒绝 |
| 21 | `backend/api/routes/_wf_runtime.py:331` | `_start_resume_task` 的取消靶子 = `_background_tasks.get(thread_id)` |

## 2. 量化附录（AST 取证，可复核）

**A. checkpoint 写入者的普查。** `await <x>.aupdate_state(...)` 的调用点（AST `ast.Call` + `ast.Attribute`），
按「宿主函数」归属：

| 文件 | 处数 | 宿主函数 |
| --- | --- | --- |
| `backend/api/routes/_wf_application.py` | 8 | `start_workflow` · `pause_workflow` · `resume_workflow`(×2) · `cancel_workflow` · `upload_brief_file` · `upload_images` · `trigger_analytics` |
| `backend/api/routes/review.py` | 4 | `submit_review` · `submit_ripple_decision` · `update_copy_content`(×2) |
| `backend/api/routes/_wf_actions.py` | 3 | `retry_ripple_analysis._run_retry` · `retry_publish` · `retry_publish._run_publish_retry` |
| `backend/api/routes/optimization.py` | 2 | `submit_draft` · `select_version` |
| `backend/api/routes/_wf_runtime.py` | 1 | `_resume_past_evaluator_pause` |
| `backend/api/routes/blogger.py` | 1 | `select_blogger` |
| `backend/api/routes/evaluation.py` | 1 | `run_evaluation` |
| `backend/api/routes/_runner.py` | 2 | `_run_graph_and_persist`（**在**统一入口内，属被覆盖的那一档） |

⇒ 统一入口**之外**的外部写入点 **20** 处 / **7** 个文件。**§7 只点了 2 处。**

**B. 租约 API 的调用点（全部，含宿主）**：

| API | 处数 | 位置 |
| --- | --- | --- |
| `start_lease` | **1** | `_runner.py:418` in `_run_graph_and_persist` |
| `end_lease` | **1** | `_runner.py:583` in `_run_graph_and_persist` |
| `thread_is_held` | **1** | `_runner.py:68` in `_lease_is_held` |
| `expire_scan` | **1** | `_takeover.py:177` in `takeover_scan` |
| `acquire` | **2** | `_takeover.py:139` in `_consider` · `execution_leases.py:511` in `start_lease` |

**C. 时间预算**（决定竞争窗口的宽度的那几个数）：

| 量 | 值 | 出处 |
| --- | --- | --- |
| 租约 TTL | **90.0 s** | `execution_leases.py:79` |
| 心跳间隔 | **30.0 s**（= TTL / 3） | `execution_leases.py:80`（由 `:78` 的 miss 数推出） |
| 接管扫描间隔 | **60.0 s**（`max(5.0, ...)`） | `settings.py:92` · `app.py:1349` |
| ripple-retry 窗口 | **1800.0 s** | `_wf_actions.py:110`（两个 `submit_and_wait` 是 `gather` 并发，`:153`） |
| 发布安全网 | 900.0 s | `tools/runtime/catalog.py:92` |
| Ripple 安全网 | 3600.0 s | `tools/runtime/catalog.py:82` |

**D. 断电时刻的可见性差**：崩溃后 `/status` 从 **90 s**（TTL）起把该 thread 报成 `stale`，
而扫描的下一趟在**最多 60 s**之后 ⇒ 「人看见 stale 并点了修复」与「扫描接管」在同一个
**60 s 量级**的窗口里竞争。这个数就是 §4 里「扫描先到」那一格的概率宽度。

## 3. ★★ 判据不圈集合：§7 点名的两个不是靠它给的判据圈出来的

§7 的小标题写「边界之外：**两个**不持租约的 checkpoint 写入者」，正文给的判据是
「它们直接写 checkpoint，**不取租约**」。按 §2-A，这条判据对 **20** 处成立。

所以 §7 的**集合是对的、判据是错的** —— 与 #634 推翻的「补一行注册表」、#631 推翻的「一行、
不改变执行语义」同族：**承袭来的便利文字，没有对着树重算过**。

真正把这 2 处分出来、且 AST 可重算的性质是**这一条**：

> 写入发生在「**宿主处理器用 `asyncio.create_task` 起一个嵌套协程、由该协程自己写**」的那条路上。

其余 18 处都写在**请求处理器的同步体内**，分两半都能验：

- 写完就返回、执行根本不发生：`start_workflow` 的 `waits_for_brief_upload` 分支（`:226` → `:236` `return`）、
  `pause_workflow`（`:659`）、`cancel_workflow`（`:1192`）；
- 写完**接着**起一个走统一入口的任务：`resume_workflow`（`:736`/`:997`）→ `_start_resume_task` →
  `_run_graph_and_persist`（`_wf_runtime.py:342-353`）⇒ 执行那一半**是被租约覆盖的**。

⇒ 这条判据顺带解释了为什么恰好是这 2 处需要被接管侧看见：**只有它们的执行整段落在租约之外**。
§7 的判据要对齐成上面这句，否则读者会以为「不取租约的写入者只有两个」，而树里是二十个。

## 4. ★★★ 裁定

| 问题 | 裁定 | 依据（可重算） |
| --- | --- | --- |
| 两条修复路径取不取租约 | **采纳** | 见下 A |
| 拒租时照跑还是拒绝 | **照跑**（维持裁定 2） | 见下 B |
| 要不要给 ripple-retry 一个自己的键 | **不采纳**（登记） | 见下 C |
| 统一入口的取租约要不要并入同一实现 | **采纳** | 见下 D |

**A. 取租约买到的两件事，与代价三件。**

买到：
- **(B1) 「修复先到」那一侧关上了。** 修复持有新鲜心跳的行 ⇒ `expire_scan()` 不会把它翻成
  `expired` ⇒ `_consider` 看不到它；即便有人抢在 `expire_scan` 与 `_consider` 之间调 `acquire`，
  `_ACQUIRE_SQL` 也会因「行是 HELD 且 `heartbeat_at + ttl > now()`」而拒绝（§2-C 的数：TTL 90 s ≫ 心跳 30 s）。
  **今天这一侧是开着的**：没有任何行为修复路径说「这块 checkpoint 有人正在写」。
- **(B3) 栅栏接得住它。** `_fence_on_lost_lease` 的靶子是 `asyncio.current_task()`（`:373`），
  **不读登记表** ⇒ 一个刻意不在槽里的任务照样在丢租约时被 cancel，且 `lease_lost` 会让
  `CancelledError` 分支不写状态。**这是「不需要自己的键也能拿到过期保护」的证据。**

代价（三条都量过，都要登记）：
- **(C1) 修复期间 `/recover` 会拒绝。** 租约被 `has_active_execution` 读到 ⇒ `derive_status` 报 `running`
  ⇒ `_wf_application.py:1077` 的「仅 error/stale 可 recover」不通过。ripple-retry 最长 **1800 s**。
  这是**正确的那一侧**（确实有人在写这份 checkpoint），但它是新行为。
- **(C2) 状态面的可见面只有一格。** `derive_status` 里 `has_active_task` 只在优先级 9/10 用到
  （`machine.py:46-47`）：有 `next` 而无人跑 ⇒ `stale`；有 `next` 而有人在跑 ⇒ `running`。
  其余分支全部短路 ⇒ 这次改动能改变的**只有 `stale → running`**。对一个刚被点了重试的 thread，
  `running` 比 `stale` 更准。
- **(C3) ★ 租约泄漏不会导致自动重发。** 修复协程若被 `kill -9`，行变 silent、90 s 后被翻成 `expired`，
  扫描会考虑它 —— 但**节点安全闸门会拒绝**：publish-retry 的待跑节点含 `publisher`
  （`irreversible`），ripple-retry 停在 `ripple_gate`（`needs_human`）
  ⇒ `takeover_verdict` 不过 ⇒ `_takeover.py:127-134` 直接 `refused`，**连 `acquire` 都不到**。
  ★ 这条是**必须量**的：不量它就不能采纳，因为「修复的租约泄漏 ⇒ 扫描替它续跑 ⇒ 可能真的发帖」
  是这次改动最重的风险，而它被一张**已有的注册表**挡住了。

**B. 拒租语义 = 照跑，这是既有裁定而不是本片的自由选择。** `start_lease` 的 docstring
（`execution_leases.py:504-509`）与 §2 非保证 1 都已写明：把执行挂在租约的回答上，会在存储答不上来时
fail-closed。⇒ §7「为什么当时不修」里那句「给它们单独加租约会引入新的**拒租分支**」**是错的** ——
裁定 2 之下没有拒租分支，只有「没装上栅栏、也没装可释放的东西」。同段另一句
「会引入新的失败模式」**是对的**，指的就是上面 C1 与 C3，本片把它们量出来并各自处置。

**C. 「自己的键」不是租约的替代品。** §7 写的是「**或**」，但两者关的是**两个洞**：
租约关跨进程/重启侧（本片采纳的那条），自己的键关**进程内**的「`_start_resume_task` 取消槽里的人」。
后者今天的确还对 ripple-retry 开着，且**只有它对它开着**：

- 取消靶子 = `_runner._background_tasks.get(thread_id)`（`_wf_runtime.py:331`）；
- publish-retry **在**槽里 ⇒ 该方向对它**已经**关了（`_start_resume_task` 会 cancel 它）；
- ripple-retry **刻意不在**槽里（#634 的裁定：那个 dict 每 thread 一槽，写入是换靶子）⇒ 仍开着。

关它要新增一个**只有 `_start_resume_task` 读**的可取消登记表 ⇒ 新增一个 cancel 靶子面，
而窗口宽度就是 §2-D 的 60 s 量级。本片**登记不修**（§7 第 1 条）。

**D. 并入同一实现。** 否则「取租约」这条规则会有两处实现，
§2 非保证 3 那句「租约只覆盖……那一条路径」就只剩字面为真。并入之后全仓 `start_lease(`/`end_lease(`
仍是各 **1** 处，只是**执行者从 1 个变成 3 个** —— 判据从「一个函数取租约」升级成
「一个实现、三个执行者」，这才是这句话该被钉住的形态。

## 5. 切片表

| # | 改动 | 文件 |
| --- | --- | --- |
| 1 | 抽出 `_execution_lease`（`@contextlib.asynccontextmanager`）：**取租约 + 装栅栏 + `finally` 释放**的唯一实现 | `backend/api/routes/_runner.py` |
| 2 | `_run_graph_and_persist` 改用它（行为不变，纯搬运） | `backend/api/routes/_runner.py` |
| 3 | 两条修复路径改用它（新行为：持租约、受栅栏） | `backend/api/routes/_wf_actions.py` |
| 4 | 修 `thread_is_held` docstring 里「`expire_scan` 没有生产调用者」这句假话 | `backend/db/execution_leases.py` |
| 5 | §2 非保证 3 重写；§7 判据重写 + 裁定表 + 新增 claim/anchor 行 | `docs/execution-plane.md` |
| 6 | 新用例（行为面 + 谓词面 + 泄漏面） | `tests/unit/api/test_repair_paths_take_the_lease.py`（新） |
| 7 | 新主张从代码重算 | `tests/unit/scripts/test_execution_plane_claims.py` |

## 6. 红线 / 不做 / 验收

**不做**：
- 不改 `acquire` / `start_lease` / `end_lease` 的签名与返回值（裁定 2 不动）；
- 不改 `_start_resume_task` 的取消行为（§7 第 1 条，登记）；
- 不改两条修复路径的守卫谓词（#634 的裁定，已有 3 条用例钉住）；
- 不给两条路径加 `add_done_callback` 或写 `_background_tasks`（#634 已裁定）。

**验收**：
1. 两条修复路径在**真模块**上验到：执行期间库里有 HELD 行、`owner_id` 是本实例、结束时是 RELEASED；
2. **拒租照跑**：`start_lease` 抛异常 / 返回 `None` 时两条路径仍然跑完并返回 200；
3. **栅栏接得住不在槽里的任务**：只有 ripple-retry 那条能验（它不在槽里）；
4. **泄漏面**：lib 里静置到过期后，`_consider` 对它 `refused`（而不是 `taken_over`）；
5. `derive_status` 的可见面只有 `stale → running` 一格；
6. 原有 3664 条用例全绿；门禁四道全过。

## 7. 登记未修（带理由，本片不动）

1. **`acquire` 把两种拒绝答成同一个 `False`**（活着的持有者 / 存储答不上来）。
   ⇒ 「**扫描先到 + 接管成功**」那一格仍然双写：修复路径拿到 `None` 之后按裁定 2 **照跑**。
   要关它必须先把两种拒绝分开（改签名或加一个 reason），而那是租约 API 的改动，不在本片。
2. **ripple-retry 对 `_start_resume_task` 不可见**（进程内「执行撞重试」）。
   理由与窗口见 §4-C。
3. **修复期间 `/recover` 拒绝**（C1），最长 1800 s。方向正确但需运维知道。
4. **`expire_scan` 的生产可达性此前没有任何判据钉住** —— 本片在 §8 的 claim 表里补一条。

## 8. 执行记录

### 8.1 改动表（实测：`git diff --stat`）

| 文件 | 改动 |
| --- | --- |
| `backend/api/routes/_runner.py` | 抽 `_execution_lease`；`_run_graph_and_persist` 改用它（整体重缩进 +4）；`from collections.abc import AsyncIterator` |
| `backend/api/routes/_wf_actions.py` | 两条修复协程各包一层 `_execution_lease`；模块 docstring 改掉「不取租约」那半句 |
| `backend/db/execution_leases.py` | `thread_is_held` 的 docstring：删掉与同文件 `:31` 相悖的「`expire_scan` 无生产调用者」 |
| `docs/execution-plane.md` | §2 非保证 3 改写；§6 三行重映射；**§7 重写**；**§7.1 恢复 #634 的裁定表**；anchor 表重映射 + 4 行；claim 表 + 9 行；§8 自覆盖三行重测 |
| `docs/tool-runtime.md` | 两处 `_wf_actions.py` 行号重映射（`:116 → :129`、`:134 → :147`） |
| `tests/unit/scripts/test_execution_plane_claims.py` | 5 个新扫描 + 9 个新重算器 + 第二个裁定表读取器 + 一条覆盖全部新扫描的正向对照 |
| `tests/unit/api/test_repair_paths_take_the_lease.py` | **新** 6 条，真模块上端到端验租约 |

### 8.2 验收逐条对照（`## 6` 的 6 条）

| # | 判据 | 落在哪 |
| --- | --- | --- |
| 1 | 执行期间库里有 HELD 行、结束时 RELEASED | `test_ripple_retry_holds_the_lease_while_the_simulation_runs` · `test_publish_retry_holds_the_lease_while_it_publishes` —— 从**工作内部**观察，不看端点回包 |
| 2 | 拒租照跑 | `test_a_refused_lease_does_not_gate_the_work` |
| 3 | 栅栏接得住不在槽里的任务 | `test_the_fence_reaches_a_task_that_is_not_in_the_registry` —— 只有 ripple-retry 能验 |
| 4 | 泄漏面被 `refused` 而不是 `taken_over` | `test_a_leaked_repair_lease_cannot_be_taken_over` |
| 5 | 可见面只有 `stale → running` | 判据表 `derive_status_mentions_of_has_active_task` = 1（一处 `if` 同时决定优先级 9/10） |
| 6 | 原有 3664 条全绿 + 门禁四道 | 见下 |

**「异常时也释放」**不在票面 6 条里，但它是这次改动**唯一新增的失败模式** ⇒
`test_the_lease_is_released_when_the_work_raises` 单独钉住，不靠推理。

### 8.3 门禁（四道 + 两道额外，全过）

| 门禁 | 结果 |
| --- | --- |
| `ruff check .` | All checks passed |
| `ruff format --check .` | **549** files already formatted |
| `mypy backend --python-version 3.12` | Success: no issues found in **217** source files |
| 全量 `pytest tests/ -q` | **3672 passed / 3 skipped**（基线 3664 ⇒ **+8** = 新文件 6 条 + 判据 2 条；无 flake） |
| `scripts/benchmarks/context_compiler_baseline.py --compare --drift-pct 5` | drift within threshold；coverage `declared=14 present=14` |
| `scripts/gates/tool_runtime_gate.py` | OK；`declared == invoked`；catalogue 10/10 |

**+8 = 6 + 2 这条分解本身就是断言**：它同时说明**零条既有用例被改动**。

### 8.4 突变自检（`C:/Users/jamer/aiworks/_mut_lease_verdict.py`，23 个突变）

```
killed 23/23
baseline=clean  restore=YES
```

- 9 个移动 §7 新增的 claim 值 · 3 个翻转租约裁定表的裁定 · 2 个翻转 §7.1 的守卫裁定 ·
  2 个破坏 anchor 表（一个是行号漂一格，一个是符号名写错）· 1 个让 ripple-retry 悄悄不取租约（源码侧）·
  6 个把判据侧扫描打坏。
- ★ **其中 3 个把新扫描硬编码成它公布的值**（`_if_tests_mentioning` / `_definitions` /
  `_create_task_targets` 各 `return 1`）——**claim 表杀不掉它们**（值确实是 1），
  只有同批进来的**正向对照**能杀。这是本片加那条对照的直接原因。
- 第一次跑时父进程没关掉沙箱的删除护栏，`LOCK.unlink` 抛 `SystemExit` ⇒ **23/23 已全部计数、
  树已还原，但摘要行被吞掉、退出码变 1**。修法是把收尾挪到摘要之后并容错 ——
  **「工具自己报的结论」也要能被工具证明**。
- ★★ **这个脚本已不存在**（2026-09-19 由 #636 补记）：#636 收尾清理仓外临时产物时把它一并删了 ——它只存在于 `C:/Users/jamer/aiworks/`，而那份保留清单当时只登记了 #636 自己的 harness。⇒ **上面这 23/23 是记录，不是可重跑的命令。** 突变自检的完整写法（witness 与 mentions 分开、TOO WEAK 与 SURVIVED 分列、锚点唯一性预检、收尾断言）留在 skill `xhs-recover-trellis-slice-delivery`；同族**可重跑**的实例是 `C:/Users/jamer/aiworks/_mut_lease_reason.py`（#636，27 个突变）。**教训：仓外产物的保留清单要按「谁引用它」推导，不是按「谁刚写的」** —— 后者会把上一片的证据删掉。

### 8.5 commit / PR

- commit：`436f4f73`（`feat/repair-paths-lease-verdict`，基线 `4471e0fa`）
- PR：**#635** —— CI **8/8 全过**（纯文档提交之前的第一次运行，py3.11 与 py3.12 都绿，无 flake）
- 门禁四道 + 两道额外，均在**将要提交的这棵树上**跑过；突变自检 `restore=YES` 由收尾 sha256 比对给出
