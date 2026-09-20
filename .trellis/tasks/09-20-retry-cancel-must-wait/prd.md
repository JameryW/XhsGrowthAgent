# 09-20-retry-cancel-must-wait — 取消一个不在槽里的任务

> 入口：`docs/execution-plane.md` §7.1 的「留给下一任务的输入」**唯一一条** ——
> 「**ripple-retry 在进程内不可取消。** 关它需要一张**只有 `_start_resume_task` 读**的可取消登记表
> —— 也就是新增一个 cancel 靶子面。publish-retry 因为**在**槽里，这一方向已经关了。」
> 该条自带要求：**量它的代价**再裁定（先例：§2 里 #639 对 `_fence_on_lost_lease` 的
> 12 个调用点 / 10 处内联 `await` 的量法）。

## 0. 这一片要回答什么

§7.1 把「进程内『执行撞重试』」这一格留了下来，理由是**槽不能补**（每 thread 一槽，写作是换靶子）、
而**租约也不关这一格**（「`_start_resume_task` 不读租约，它只读登记表」）。于是它把结论落成
「需要一张新的可取消登记表」，并**明确标注这是估的**，要求下一片先量。

本片量了四件事，其中**两件把登记自己的文字推翻了**：

1. **靶子真的不存在**（§2.1）：按 `:252` 的原样起任务，三个直接读槽的动作与两个「忙不忙」谓词
   全答「没人跑」。
2. **★ 登记给的理由是错的**（§2.2）：租约**不是**「没被读」，而是**读了也答不出** —— 两个后端的
   授予路径都按 `owner_id` **认自己**（`_ACQUIRE_SQL:301` 的第二个 `OR` 项、`_acquire_in_memory:384`
   的反条件），而 `owner_id` 是**实例**级的 ⇒ 同进程的第二个持有者必得 `granted`。
   这条一量出来，「新登记表」就从**设计偏好**变成**唯一可行的那扇门**。
3. **「两个写者」实测成立**（§2.3）：A 持租约不放时，B 走统一入口，`graph.ainvoke` 调用 **1** 次。
4. **★★ 按字面关法会引入一个新 bug**（§2.4）：取消**不 await** ⇒ 被取消者退场时的 `end_lease`
   把 **resume 刚拿到的那一行**置 `released` ⇒ resume 的 `renew` 答 `lost` ⇒ **resume 被自己的
   栅栏取消**。实测：`held=False` / `lost`；`cancel` 后 `await` 则 `held=True` / `renewed`。
   ⇒ 「等它退完」不是礼貌，是**这条修复的正确性条件**。

所以本片的裁定是 **采纳（开门）**，并且**多带一条条件**：那一下 `cancel` 必须等。

## 1. 现状侦察表（每条都对树核过；行号是**交付前**的值，S1 落地后同文件内的行号会动，见 §8.1）

| # | 事实 | 位置 |
| --- | --- | --- |
| P1 | 槽是 **每 thread 一槽**：`dict[str, asyncio.Task[Any]]`，**3** 处写入者（`_wf_actions.py:449` publish-retry · `_wf_runtime.py:353` resume · `_wf_application.py:260` 统一入口的另一条） | `_runner.py:45` |
| P2 | 槽的直接读者 **5** 处（`.get(` 形式）：**3** 处取消占位者（`_wf_application.py:663` pause · `:1209` cancel · `_wf_runtime.py:331` `_start_resume_task`）、**1** 处拒绝删除（`_wf_application.py:1516`）、**1** 处身份守卫（`_wf_runtime.py:63` 的 done 回调） | 同上 |
| P3 | ★ ripple-retry 的 `create_task` **赋值给局部变量**，从不入任何表；publish-retry 入槽并有 done 回调 | `_wf_actions.py:252` vs `:447-449` |
| P4 | publish-retry 有身份守卫的自清理（`is asyncio.current_task()` 才 pop）；ripple-retry 没有 | `_wf_actions.py:443-445` |
| P5 | `_start_resume_task` 取消占位者时**不 await**（`existing_task.cancel()` 后直接往下走） | `_wf_runtime.py:331-333` |
| P6 | 统一入口**明确不咨询**租约结论：「The outcome is deliberately not consulted here.」⇒ `HELD_BY_LIVE_OWNER` 也不是它的门 | `_runner.py:508-512` |
| P7 | 栅栏的靶子是 `asyncio.current_task()`，**不读登记表** ⇒ 不在槽里的任务照样在丢租约时被 cancel | `_runner.py:384` / `:404-405` |
| P8 | ★ **授予路径按 `owner_id` 认自己**：SQL 侧 `WHERE ... OR owner_id = EXCLUDED.owner_id`；内存侧拒绝条件里含 `existing.owner_id != _instance_id` ⇒ **同进程第二个持有者必得 `granted`** | `execution_leases.py:301` / `:384` |
| P9 | ★ **释放路径也只按 `owner_id`**，且没有每任务的引用计数：`WHERE thread_id = %s AND owner_id = %s`（无 `state` 条件）；内存侧 `current.owner_id != _instance_id` 才拒 | `execution_leases.py:314-319` / `:551` |
| P10 | `end_lease` = 停心跳 + `release(thread_id)`，包在 `suppress(Exception)` 里；`_execution_lease` 的 `finally` 无条件调它 ⇒ **被取消的任务退场时也会释放那一行** | `execution_leases.py:730-742` / `_runner.py:474-481` |
| P11 | 心跳间隔 = `90/3` = **30s**；`LOST` 零预算、立即停 | `execution_leases.py:83-85` / `:640` |
| P12 | `_start_resume_task` 调用点 **8** 处（`_takeover.py:148` · `_wf_application.py:737 995 1000 1158 1679 1862` · `_wf_runtime.py:253`） | 探针实测 |
| P13 | 「本进程/任何实例忙不忙」的答者调用点共 **12** 处（`process_has_active_task` 4 + `has_active_execution` 8）⇒ 新表若被 OR 进去，可见面是 12 处，而不是 1 处 | 探针实测 |
| P14 | §7 已有一行裁定「**给 ripple-retry 一个自己的键** = 不采纳」，它说的是**槽**的键（#634）；本片开的是**另一张表** —— 两者不是同一个决定，文档必须写清（§3 裁定 B） | `docs/execution-plane.md:218` |

## 2. 量化附录（探针，真模块实测，不是推的）

探针两个，都在仓外保留（§8.3）：

- `C:/Users/jamer/aiworks/_probe_retry_cost.py` —— 实验 1/2/3/4/5（靶子存在性 · 两个写者 · 账目 · 退场连带）。
- `C:/Users/jamer/aiworks/_probe_retry_teardown.py` —— 退场连带的最小复现（实验 4 的单文件版）。

### 2.1 靶子真的不存在（实验 1）

按 `_wf_actions.py:252` **原样**起任务（同一个 `name=`），然后逐个问现有的答者：

```
_background_tasks.get('t1')       -> None
process_has_active_task('t1')     -> False
has_active_execution('t1')        -> False
task 自己还在跑                    -> True
asyncio.all_tasks() 按名字找到     -> 1 条  'ripple-retry-t1'
```

★ 最后一行是这一节的**反例见证**：把手**存在**，就在 `asyncio.all_tasks()` 里，名字唯一且由
`:252` 亲手写死。所以「取消不了」不是「任务不可达」，而是**没有任何人往那个地方看**。
（本片没有选「按名字扫 `all_tasks()`」这条路：名字是字符串契约，不是声明 ——
而仓里已有的口径是「快照与它 pin 的实现之间必须有一条**会被重算的**关系」。）

### 2.2 ★ 租约分不开同进程的两个任务（实验 2）

同一个进程里 A 先取租约并持有，B 再取：

```
A 取租约 -> granted
B 取租约 -> granted        ← 不是 held_by_live_owner
```

原因在两侧的**授予**路径里各一行（P8）：SQL 的 `WHERE` 把「同一 `owner_id`」也算成可授予，
内存后端把「`owner_id` 相同」排除在拒绝条件之外。⇒ **租约的持有单位是进程，不是任务。**

这条把 §7.1 的理由替换掉：

| 原登记的说法 | 实测 |
| --- | --- |
| 「取租约也不关这一格：`_start_resume_task` **不读**租约，它只读登记表」 | 读了也没用 —— **租约答 `granted`**。它关不了这一格不是因为没人问，而是因为**这一问的粒度不对** |

⇒ 「新登记表」由此从**设计偏好**升级成**唯一可行的那扇门**（改租约粒度 = 改接管语义，见 §6）。

### 2.3 「两个写者」实测成立（实验 2 下半）

A 持租约期间，B 走**真正的**统一入口 `_run_graph_and_persist`，数它调了几次 `graph.ainvoke`：

```
B' 走 _run_graph_and_persist: graph.ainvoke 调用次数 -> 1
```

`1` = 第二个写者落了地。这与 P6（统一入口明确不咨询租约结论）互相印证：
**租约的栅栏只挡「丢租约之后还写」，不挡「一开始就没有拿到」。**

### 2.4 ★★ 退场会抽掉接任者脚下的那一行（实验 4/5）

被取消的任务退场时会走 `_execution_lease` 的 `finally`（P10）→ `end_lease` → `release`，
而 `release` **只按 `owner_id`** 认领（P9）⇒ 它置的是**同一个实例的那一行**，也就是说
**接任者刚拿到的那一行**。实测两侧对照：

| 关法 | 接任者的行 | 接任者的 `renew` | 接任者的下场 |
| --- | --- | --- | --- |
| `cancel()`，**不 await**（= `_wf_runtime.py:333` 现有写法） | `held=False` | `lost` | **被自己的栅栏取消** |
| `cancel()` 后 **await** 到它退完 | `held=True` | `renewed` | 正常 |

⇒ **「等」是这条修复的正确性条件，不是一个更好的写法。** 也正因为这一条，
「按字面把登记表补上」不是本片的做法 —— §3 裁定 A 把它写成**两半**。

### 2.5 账目（实验 3，AST 数）

| 量 | 读数 | 出处 |
| --- | --- | --- |
| 槽 `_background_tasks[...] = ` 写入者 | **3** | P1 |
| 槽 `.get(` 读者 | **5**（其中 **3** 处取消占位者） | P2 |
| 「忙不忙」答者调用点 | **12** | P13 |
| ripple-retry 起任务处入表次数 | **0** | P3 |
| ripple-retry 自身清理次数 | **0** | P4 |
| `_start_resume_task` 调用点 | **8** | P12 |

⇒ 新表若要**与槽等价**，代价是 3 个取消读者 + 1 个拒绝读者 + 12 个答者；
若只关**登记那一条**（进程内「执行撞重试」），代价是 **1 个读者**。本片取后者，并把
「它**不是**一个忙不忙答者」也钉成判据（§3 裁定 B）。

## 3. 裁定

### 裁定 A：**采纳** —— 开门，但写成两半：靶子 + **等**（**采纳**）

原登记说「一张只有 `_start_resume_task` 读的可取消登记表」。实测（§2.4）说这句话**不完整**：
只补表会让 resume 自杀。所以采纳的是**两半**：

1. 一张**detached 登记表** —— 只装「刻意不进槽的任务」（今天只有 ripple-retry），
   **只有抢占者读**；它**不**并入 `process_has_active_task` / `has_active_execution`
   （P13：那 12 处答者是这个表的**反例面**，不是消费面）。
2. 那一下取消**必须等到被取消者退完** —— 因为它的退场会释放**接任者将要用的**那一行租约
   （§2.4）。这条由 `cancel_detached_and_wait` 的实现承载。

### 裁定 B：把「它**不是**第三张忙不忙表」与「它**在**表里」**都**钉成判据（**采纳**）

单向的判据会在这件事上失效：只钉「它在表里」，那么把它 OR 进两个谓词（可见面 12 处）
不会有任何一条变红；只钉「它不在两个谓词里」，那么把它从表里删掉（本片要关的洞重新打开）
也不会有任何一条变红。⇒ 两个方向各一条，且都是**从树重算**的（§4 的 S3）。

### 裁定 C：与 §7 已有的「不采纳」**不冲突**，但文档必须写清（**采纳**）

P14：§7 的裁定表里已经有一行「**给 ripple-retry 一个自己的键** = 不采纳」，那是**槽**的键
（#634 的判据：每 thread 一槽 + 3 个取消读者 ⇒ 写入是换靶子）。本片开的是**另一张表**。
两者在同一条文档里相邻，读起来极易被当成「同一个决定判了两次」⇒ §7.1 必须把那句
「自己的键」**限定成「槽里的键」**，并把本片这张表与它的区别写成一行可核的对偶：
**槽的读者会写工作流的列（3 个取消 + 1 个拒绝 + 1 个身份守卫），新表的读者只取消。**

### 裁定 D：`_start_resume_task` 只加**一处**取消，不动槽那一处的写法（**采纳**）

槽那一路（P5，不 await）**保持原样**：它取消的是工作流的任务，那个任务退场走的是
`_run_graph_and_persist` 的 `CancelledError` 分支 —— 它**先看 `lease.lost`**、再看身份守卫
（`_runner.py:566-571`），行为已经钉过。改它会把本片的面从「1 处」扩到「4 处」，
而 §2.4 量出来的那个自杀条件是**同一个实例内所有任务共享一行租约**导致的，不是槽那一路的问题。
⇒ 本片只给**新表**那一半加 await，并在代码里写明为什么两半不一样。

## 4. 切片表

| 切片 | 内容 | 判据 |
| --- | --- | --- |
| S1 | `_runner.py` 声明 `_detached_tasks` 与其唯一读者 `cancel_detached_and_wait`（docstring 写「等」是正确性条件及其实测）；`_wf_actions.py` 的 `retry_ripple_analysis` 登记 + `_run_retry` 加身份守卫的 `finally` 自清理；`_wf_runtime.py` 的 `_start_resume_task` 加一处 `await _runner.cancel_detached_and_wait(thread_id)` | 既有 `ripple_retry_task_registrations = 0`（槽）**保持不变** |
| S2 | 行为判据：①登记表里的任务会被 `_start_resume_task` 取消**且**在它返回前已 done；②**正对照**：没进表的任务不受影响；③§2.4 的两侧对照（不 await ⇒ `lost`，await ⇒ `renewed`）落在 `cancel_detached_and_wait` 的契约上 | `tests/unit/api/` 新增/扩充 |
| S3 | 主张：新增 4 条（两条租约授予的后端证据 · 新表的写入点数 · 新表的取消读者数 · 那一下是否等）并把 `ripple_retry_self_cleanups` 由 `0` 改成 `1`；每条配正对照；文档 §7.1 结掉该条、§7 把「自己的键」限定成槽的键、锚点/自覆盖数重算 | `tests/unit/scripts/test_execution_plane_claims.py` · `test_docs_anchors.py` · `test_docs_citations.py` |

## 5. 红线 / 不做 / 验收

1. **不改租约的粒度**：不动 `_ACQUIRE_SQL` / `_RELEASE_SQL` / `_acquire_in_memory` / `release`
   / `renew` 的任何一行 —— §2.2/P8/P9 是**证据**，不是待改的地方（改它 = 改接管语义，见 §6）。
2. **不动槽那一处的写法**（裁定 D）：`_background_tasks` 的 3 个写入者、5 个读者、`process_has_active_task`
   的返回语义**一字不改**；`ripple_retry_task_registrations` 必须仍是 `0`。
3. **不把新表 OR 进两个谓词**（裁定 B 的一半）：`process_has_active_task` / `has_active_execution`
   不得出现 `_detached_tasks`。
4. **不改 `create_task` 的目标名**：`_registrations(ACTIONS, "_run_retry")` /
   `_submits_are_concurrent(ACTIONS, "_run_retry")` / `_own_task_writers(ACTIONS)` 都以
   `_run_retry` 这个名字为锚；改名会让它们抛 `AssertionError`（不是红，是**炸**）。
   ⇒ 自清理写在 `_run_retry` **原地**，不外包一层。
5. 既有 `release` / `renew` / `acquire` 相关断言一字不改。
6. 验收：四道门禁 + 全量 `pytest` 全绿；突变自检全杀。

## 6. 登记未修（带理由，本片不动）

1. **租约的粒度是进程，不是任务**（P8/P9）：这是**设计**，不是缺陷 —— 接管扫描问的是
   「有没有别人在写这个 thread」，而那个「别人」就是实例。改成任务粒度会让同一实例的
   两次执行互相拒绝，而滚动发布那一侧要的正是「同实例可立即重取」。**本片只把它写成证据。**
2. **进程内的「重试撞重试」仍没有闸门**：`retry_ripple_analysis` 的守卫读的是槽（P2），
   而它自己不在槽里 ⇒ 两次重试可以同时在飞。这与本片关的那一格**同源**（不可见），
   但**方向不同**（那是并发守卫，本片是抢占靶子）。**未量，本片不碰**（§7）。
3. **`_active_sync_executions`** 是槽谓词的第二半（P2 之外），本片未动。

## 7. 留给下一任务的输入

1. **重试撞重试可以同时在飞**（§6 第 2 条）：`_wf_actions.py:101` 的守卫与
   `retry_publish:302` 是同一个谓词，但**两条路径的可见性不同** —— publish-retry **在**槽里
   （P3），所以它读槽是**有效**的；ripple-retry 不在槽里，它读槽是**空的**。
   ⇒ 下一片要问：**一个既不该进槽、又该被守卫看见的任务，需要什么形状的表？**
   本片刚证明「一张只被抢占者读的表」**不是**它（裁定 B：新表的读者只取消，不回答忙不忙）。
2. **`renew` 的零调用点要不要处理**（#638 的登记，仍未动）。
3. **P2a 三处 `run_publish` 直调语义各不相同**（更早的登记，仍未动）。

## 8. 执行记录

**S1 · S2 · S3 全部落地**（分支 `feat/retry-cancel-must-wait`）。

| 切片 | 落地内容 | 位置 |
| --- | --- | --- |
| S1 | `_runner.py` 声明 `_detached_tasks` 与它的**唯一读者** `cancel_detached_and_wait`（docstring 写「那一下 `cancel` 必须等」的依据 + §2.4 的两行实测 + 引 `execution_leases.py:301 / :314 / :384`）；`_wf_actions.py` 的 `retry_ripple_analysis` 登记 + `_run_retry`（**原名不动**，红线 4）加身份守卫的 `finally` 自清理；`_wf_runtime.py` 的 `_start_resume_task` 只加**一处** `await _runner.cancel_detached_and_wait(thread_id)` | `_runner.py:75-103`（+40）· `_wf_actions.py:262-270` · `_wf_runtime.py:342-343`（+10） |
| S2 | 行为判据 **5** 条：进新表 ⇒ 被 resume 取消**且**在它返回前已 `done()`；正对照：没进表的任务不受影响；★ `test_without_the_wait_the_successor_fences_itself` **故意测坏写法**（`cancel` 不 await ⇒ 后继者被自己的栅栏取消），`test_the_wait_keeps_the_successors_lease` 是它的正对照；§2.2 那条「同进程第二个持有者也得 `granted`」钉成 `test_the_lease_cannot_see_a_second_executor_in_this_process` | `tests/unit/api/test_detached_task_cancel.py`（**新**，182 行） |
| S3 | 主张 **6** 列 + **5** 条正对照（两条授予路径 · 新表写入点数 · 新表取消读者数 · 那一下是否等 · 自清理的身份守卫 · 新表**没有**被 OR 进「忙不忙」）；`ripple_retry_self_cleanups` `0 → 1` 并连同 `publish_retry_self_cleanups` 登记进 `_CONVERGED_PROPERTIES`；§7.1 结掉该条、原处换成「重试撞重试」；§7 的「自己的键」**限定成槽里的键**；26 处锚点重映射 + 自覆盖数 `143 → 155` | `test_execution_plane_claims.py`（+334/-14）· `test_docs_anchors.py`（+66/-1）· `docs/execution-plane.md`（+63/-45） |

**门禁**：`ruff check .` 全绿 · `ruff format --check .` **552** files（上票 551，**+1 = 恰好等于本片新增文件数** ⇒ 顺手证明没夹带别的文件）· `mypy backend --python-version 3.12` **217** source files 干净 · `scripts/gates/tool_runtime_gate.py` OK。
**全量**：**3705 → 3716**（**+11**，逐条对上：新文件 **+5** · `test_docs_anchors.py` **+1** · `test_execution_plane_claims.py` **+5** 条新正对照。`_CLAIMS` 是**函数内迭代**、该文件全文没有 `@pytest.mark.parametrize` ⇒ 新增主张行**不产生新用例 ID**；`git diff HEAD` 里也**没有**一条被删的 `def test_`），3 skipped。
**突变**：**11/11 killed**，`restore=YES`，harness = `C:/Users/jamer/aiworks/_mut_retry_cancel.py`（可重跑）。11 条**没有一条**是 `SyntaxError` 假杀（harness 会把 `BROKEN MUTANT` 单列）。

### 8.1 与我自己写下的假设相悖的五条

1. **★★ 登记给的理由是错的，而这一条把「设计偏好」变成了「唯一可行的那扇门」。** §7.1 的原话是
   「`_start_resume_task` 不读租约」—— 读起来像「租约这条路没人走」。实测（§2.2）是**读也答不出**：
   两个后端的授予路径都按 `owner_id` 认自己（`_ACQUIRE_SQL:301` 的第二个 `OR` 项 ·
   `_acquire_in_memory:384` 的反条件），而 `owner_id` 是**实例**级的 ⇒ 同进程的第二个持有者必得
   `granted`。⇒「加一张新表」不再是「比改租约省事」，而是**唯一能分开同进程两个执行者的门**。
2. **★★ 按字面关法会引入一个新 bug，所以「等它退完」是正确性条件，不是礼貌。** 只 `cancel()` 不
   `await` ⇒ 被取消的任务退场时 `_execution_lease` 的 `finally` **无条件**调 `end_lease`
   （§2.4：释放路径只按 `owner_id`、没有任何每任务引用计数）⇒ **resume 刚拿到的那一行被置
   `released`** ⇒ resume 的 `renew` 答 `lost` ⇒ **resume 被自己的栅栏 `_fence_on_lost_lease` 取消**。
   实测：不 await ⇒ `held=False` / `lost`；await ⇒ `held=True` / `renewed`。⇒ 本片因此只给**新表**
   那一半加 `await`，**槽那一路故意不动**（裁定 D）。
3. **★「包一层 `try/finally` 只加 6 行」是我估的，实测是 +16（两倍多）。** 4 空格重排把 4 处
   长行推过 100 列 ⇒ `ruff format` 把它们折成多行（`_record_lease_refusal` +2 · `print(...FAILED...)`
   +3 · `refify_updates` +2 · `reason = (...)` +3）。⇒ 同文件内 `:252` 之后的引用**全部**从 +6 变成
   +16：P3 的 `:252 → :268`、P4 的 `:443-445 → :461-463`、`:447-449 → :465-467`（后两者是 +18，
   因为本片在那一段还加了 1 行注释 + 1 行登记）。**§1 表头那句「行号是交付前的值」救了这一条** ——
   26 处锚点是一轮**机制**重映射过的，不是手改的。
4. **★★「行号级的否定行」会静默腐烂，而引用判据在原理上看不见它。** 主张表里原有一行说
   「`_wf_actions.py:252` **不是**登记点」。S1 之后 252 变成了别的行，而这行**照样绿**（引用判据只问
   `path:line` **存在**吗）。修法是**结构性的**：新增 `_unpinned_absence_rows(text)` —— 要求**每一条
   带行号的否定行**所指的位置必须同时被**肯定表**钉住（同一行出现在肯定表里 ⇒ 它是个被声明过的行，
   不是随手写的行号）+ 2 条正对照。顺手在重映射里另抓到 **6 处**「解得到、但配错了符号」的**承袭**腐烂
   （`_runner.py:433 / 408 / 376 / 646` · `_wf_actions.py:120 / 350`）—— 与 #640 §8.1 第 2 条同类，
   引用判据同样看不见。
5. **★ 文档补丁本身不是幂等的（过程发现）。** 几段新文字**包含**旧文字 ⇒ 两阶段替换跑第二遍也会再插
   一次（首轮 11/11，二轮把 4 个块各复制了一份）。修法不是「小心点」，是**按 11 个「只在新文字里出现」
   的标记把 `main()` 闸住**（全在 ⇒ 跳过；全不在 ⇒ 执行；否则报错退出）。二轮起输出
   `skip: already applied (11 markers present)`。

### 8.2 登记未修（本片新增，带理由）

1. **`cancel_detached_and_wait` 没有超时。** `await asyncio.gather(task, return_exceptions=True)`
   如果要退的那个任务**吞掉 `CancelledError`**（或卡在同步调用里不回事件循环），
   `_start_resume_task` 会**无限等**。这是「等是正确性条件」的**代价**：本片用「等」换掉了「自杀」，
   但**吞异常那一侧没量**。**未量，不碰。**
2. **进程内的「重试撞重试」仍没有闸门**（§6 第 2 条 / §7 第 1 条重申）：`retry_ripple_analysis` 的守卫
   读的是**槽**，而它自己**不在**槽里 ⇒ 两次重试可以同时在飞。本片开的是**另一格**（取消靶子），
   方向不同（那是并发守卫，需要一张**既不该进槽、又该被守卫看见**的表）。**未量，不碰。**
3. **新表对 12 个「忙不忙」答者仍不可见** —— 这是裁定 B 的**代价**，不是缺陷：
   `process_has_active_task` / `has_active_execution` 现在会**明知不完整**地回答「没人跑」。
   但「刻意」这一点**没有判据**：`test_the_new_table_is_not_a_busy_answerer` 只能证明「**没有**被 OR
   进去」，不能证明「**应该**不被 OR 进去」。这条只由 `docs/execution-plane.md` 的文字担着。
4. **新表的条目生命周期只靠 `_run_retry` 的 `finally`**（槽那一路还有 done 回调，新表没有）。若进程
   被硬杀，条目会留在字典里 —— 但那时进程也没了。⇒ 这一条**只在「同进程重建执行平面」的假想形态下**
   才成立，本片**不建**这个形态，故不补 done 回调。

### 8.3 仓外产物（保留清单按「谁引用它」推导，不按「谁刚写的」，见 #637 那次的教训）

| 文件 | 谁引用它 |
| --- | --- |
| `C:/Users/jamer/aiworks/_mut_retry_cancel.py` | §8 的 **11/11 killed** —— 可重跑 |
| `C:/Users/jamer/aiworks/_probe_retry_cost.py` | §2 的五个实验（靶子存在性 · 两个写者 · 账目 · 退场连带）—— 可重跑 |
| `C:/Users/jamer/aiworks/_probe_retry_teardown.py` | §2.4 退场连带的最小复现（实验 4 的单文件版）—— 可重跑 |
| `C:/Users/jamer/aiworks/_probe_retry_cancel.py` | §1 **P12** 那次「`_start_resume_task` 8 个调用点」的静态普查 —— 可重跑 |

★ 四个都按**全路径**登记（照 #640 §8.3 的形状）：只写文件名的话 `git grep "aiworks/_"` 找不到它，
「谁引用它」这条规则会在它身上失效。**P12 原来只写了「探针实测」，出处是本片补上的。**
其余本轮临时脚本（锚点重映射 · 引用核验 · 文档补丁 · EOL 归一 · 票据补丁）与全部输出文件已清掉。
