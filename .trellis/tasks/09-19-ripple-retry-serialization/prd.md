# prd：ripple-retry——守卫答什么、回调要不要

> 票 `09-19-ripple-retry-serialization` · 分支 `feat/ripple-retry-serialization` · 基线 `47ed1666`
> 前置：`docs/execution-plane.md` §7（由 #631 钉代价、#632 钉形状）

## 0. 这一片要回答什么

`docs/execution-plane.md:216` 把两问留给下一任务，并要求**带着 1800 秒**做：

> **守卫答什么，回调要不要。**

§7 第 1 条给的默认方向是「给 ripple-retry **补齐**兄弟路径有的东西」，并列了 4 条缺口
（串行化守卫 / `add_done_callback` / `_background_tasks[...] =` / 被起协程的自身清理）。

本片把两问裁定掉，并**同时推翻那条默认方向**：4 条里只有 **守卫** 能独立成立，另 3 条各有反证
（详见 §3、§4）。所以本片的产出不是「补齐」，而是**一条改动 + 三条带理由的不做**。

## 1. 现状侦察表（每条今天对树核过，行号是交付前值）

| # | 位置 | 事实 |
| --- | --- | --- |
| 1 | `backend/api/routes/_wf_actions.py:38` | `retry_ripple_analysis`，ripple-retry 的处理器 |
| 2 | `backend/api/routes/_wf_actions.py:97` | `_run_retry()`，被起的那个协程；`:176` 直接 `aupdate_state` |
| 3 | `backend/api/routes/_wf_actions.py:181` | `asyncio.create_task(_run_retry(), ...)` —— **起完就丢** |
| 4 | `backend/api/routes/_wf_actions.py:193` | `retry_publish`，兄弟路径 |
| 5 | `backend/api/routes/_wf_actions.py:222` | 兄弟的守卫**注释**：「工作流正在跑（**含正在重试**）时不允许再触发」—— 意图的出处 |
| 6 | `backend/api/routes/_wf_actions.py:228` | 兄弟的守卫：`_runner.process_has_active_task(thread_id)` |
| 7 | `backend/api/routes/_wf_actions.py:361-363` | 兄弟的收尾三连：`create_task` → `add_done_callback` → `_background_tasks[thread_id] = task` |
| 8 | `backend/api/routes/_runner.py:42` | `_background_tasks: dict[str, asyncio.Task[Any]] = {}` —— **key 是 thread_id** |
| 9 | `backend/api/routes/_runner.py:48` | `process_has_active_task`：「*本进程*在跑这个 thread 吗」= 串行化问题 |
| 10 | `backend/api/routes/_runner.py:55` | 它的实现：`thread_id in _background_tasks and not [.].done()` **or** in `_active_sync_executions` |
| 11 | `backend/api/routes/_runner.py:74` | `has_active_execution`：「*任何实例*在跑吗」= 状态推导问题 |
| 12 | `backend/api/routes/_runner.py:91` | 后者把前者 **OR** 进来 |
| 13 | `backend/api/routes/_wf_application.py:1675` | 消费者 2：brief 上传自动 resume（`if not has_active and next_nodes:`） |
| 14 | `backend/api/routes/_wf_runtime.py:99` | `_on_task_done` 的 `stale` 分支：任务正常结束而库仍 `running` ⇒ 写 `stale` |
| 15 | `backend/api/routes/_wf_runtime.py:314` | `_is_orphan_running`：`return not await has_active_execution(...)` |
| 16 | `backend/api/routes/_wf_actions.py:95` | `ripple_timeout = 1800.0` |
| 17 | `backend/api/routes/_wf_actions.py:138` | `asyncio.gather(pred_task, pmf_task)` —— 两个 `max_wait` 是**并发**的 ⇒ 窗口 = 1 个 timeout |

## 2. 量化附录（可复核）

**登记表的读写形态**（`grep -rn "_background_tasks" backend/ --include=*.py`，逐条分类）：

| 形态 | 处数 | 位置 |
| --- | --- | --- |
| 写入 `_background_tasks[id] = task` | **3** | `_wf_actions.py:363` · `_wf_application.py:260` · `_wf_runtime.py:353` |
| 谓词读 `_runner.py:55` | 1 | 定义处自己 |
| `is asyncio.current_task()` **身份守卫的自清理** | 5 | `_runner.py:481` `:517` `:575` · `_wf_actions.py:358` · `_wf_runtime.py:63` |
| **对槽里那个任务直接 `cancel()`** | **3** | `_wf_application.py:663`（`pause_workflow`）· `:1209`（`cancel_workflow`）· `_wf_runtime.py:331`（`_start_resume_task`） |
| **槽被占用就拒绝** | 1 | `_wf_application.py:1516`（`delete_workflow`） |

宿主机函数由 AST 逐一确认（不是按行号猜的）：`:663`→`pause_workflow`、`:1209`→`cancel_workflow`、
`:1516`→`delete_workflow`、`_wf_runtime.py:331`→`_start_resume_task`。

**谓词的消费者**：`process_has_active_task` 在 `_runner` 之外有 **2** 处
（`_wf_actions.py:228` · `_wf_application.py:1675`）；`has_active_execution` 在 `_runner` 之外有 **7** 处
（`_wf_application.py:324/506/747/1046/1077/1293` · `_wf_runtime.py:314`）。

## 3. ★★ 定性要重写：登记表是**每个 thread 一槽**，「补一行」不是代价问题，是**换靶子**

§7 把 `_background_tasks[thread_id] = task` 记作「ripple-retry 缺的那一行」。对着树量下来，它不是
「多一个键」：**这个 dict 的 key 就是 thread_id**，所以写入一条新任务会**顶掉**工作流自己的条目。

探针实测（`_probe_registry.py`，用真模块跑）：

```
entries for one thread after two writes: 1
slot now holds the retry: True
the workflow task is gone from the registry: True
pause/cancel now cancel the retry: True
...and leave the workflow task running: True
```

即：写入之后，`/pause`（`:663`）与 `/cancel`（`:1209`）的 `cancel()` **打到重试身上**，而**工作流照跑**
—— 库里已经写着 `paused`/`cancelled`，真的执行还在写同一个 checkpoint。`/resume`（`_wf_runtime.py:331`）
同形。而工作流自己的条目**再也不会恢复**：它的自清理有 `is asyncio.current_task()` 身份守卫
（`_runner.py:575-576`），被顶掉之后那个 `pop` 永远不成立。

⇒ **这一行的代价不是「30 分钟静默拒绝」，而是把 3 个破坏性动作的靶子换掉。** §7 的代价模型只走了
`process_has_active_task` 的读者，漏掉了**直接读槽的那 3 个 `cancel()` 靶点**；而后者严重得多。

## 4. 两问的裁定（外加被顺带推翻的第三问）

| 问 | 裁定 | 证据 | 不做/做的代价 |
| --- | --- | --- | --- |
| **1. 守卫答什么** | **加**：答「**本进程**在跑这个 thread 吗」，用 `_runner.process_has_active_task(thread_id)`，与兄弟**同一个谓词、同一句文案** | `:222` 的注释写着意图含「正在重试」；`_runner.py:48` 的 docstring 明说它是给「要不要在本进程起一份」用的 | 换来：不再与「本进程正在跑的执行」并发写同一 checkpoint。代价：工作流在飞时（≤1800s）点重试会拿到 `skipped` 而不是起第二份 |
| **2. 回调要不要** | **不要** | `_on_task_done` 的两个分支写的都是**工作流**的列：`:97-99` 把仍 `running` 的库标 `stale`，`:93-96` 把异常写进 `status=error` + `error`。而 ripple-retry 结束**不代表工作流结束**（它只是补一次预测） | 照抄会把**暂停/仍在跑**的工作流说成 `stale`，并把重试自己的异常记成工作流的失败 |
| **3.（新）注册表要不要** | **不要** | §3 的探针：每 thread 一槽 + 3 个 `cancel()` 靶点 + 身份守卫导致条目不可恢复 | 照抄 = 把 `/pause` `/cancel` `/resume` 的靶子换成重试，且工作流条目永久丢失 |

**连带结论**：第 4 条（自身清理）**依赖**第 3 条 —— 没有登记就没有要清理的条目，所以它跟着一起不做。
⇒ §7 的第 1 条从「4 个缺口」改判为「**1 个缺口 + 3 条裁定不做**」。

**★ 但守卫只挡一个方向，这句话必须写下来**：它挡「重试撞本进程的执行」；**挡不住**「执行撞重试」
—— 后者发生在 `_start_resume_task`（`_wf_runtime.py:331`），它 `cancel()` 的是槽里的东西，而
ripple-retry **不在槽里**。所以两个写者仍可能在飞（见 §7 登记 1）。

## 5. 切片表

本票单切片。

| 片 | 内容 | 独立 PR |
| --- | --- | --- |
| **S1** | 只加守卫（1 处）+ 两问裁定写进 §7 + 判据 | 是 |

## 6. 红线 / 不做 / 验收

**不做**（每条都有上面的理由，不是省事）：

1. 不写 `_background_tasks`（§4 问 3）。
2. 不加 `add_done_callback`（§4 问 2）。
3. **不加租约**：§7 第 2 条（让两条路径取租约）需要先裁定**拒租语义**，本片不替它表态。
4. 不动 `process_has_active_task` / `has_active_execution` 的实现与读者集合（除了新增这一个消费者）。
5. 不动 1800 / `gather` 的并发形状、不动两条修复路径的任何既有返回。

**验收**（每条都要能在突变里被单独击杀）：

| # | 判据 | 形状 |
| --- | --- | --- |
| A1 | 本进程在跑该 thread 时，ripple-retry 回 `skipped`，文案与兄弟**逐字相同** | API 级 |
| A2 | 同一情形下，**登记表里的条目还是原来那一条**（没被顶掉）—— 同时钉住守卫与「不写登记表」 | API 级 |
| A3 | 本进程没在跑时，ripple-retry 回 `retrying`，且**登记表仍为空** | API 级 |
| A4 | `retry_ripple_analysis` 的源码里没有 `add_done_callback` | 结构级 |
| A5 | 主张表：`ripple_retry_serialization_guards` `0→1`；`process_has_active_task_consumers_outside_the_runner` `2→3` | 重算 |
| A6 | 主张表新增：登记表**每 thread 一槽**（结构）、两条路径的拒绝文案**同一句**（配对） | 重算 |

## 7. 登记未修（本片不修，带理由）

1. **守卫是单向的。** 「执行撞重试」仍无闸门：`_start_resume_task` 看不见不在槽里的 ripple-retry
   ⇒ 两个写者可以在飞。修它需要 ripple-retry 有自己的键或租约。
2. **两次 ripple-retry 不互斥。** 同因（不进槽）。今天的形状与昨天一致，本片**没有**改变它 ——
   不要把它读成「本片修好了并发」。
3. **两条路径仍不持租约**（§7 第 2 条）。拒租语义未定：照跑（今天）还是拒绝。

## 8. 执行记录

**改动**（6 个已跟踪文件；`uv.lock` 已还原、不入库）

| # | 文件 | 改了什么 | 行数 |
| --- | --- | --- | --- |
| 1 | `backend/api/routes/_wf_actions.py` | **唯一的生产代码改动**：`retry_ripple_analysis` 加守卫（落在 `:62`，插在 `WorkflowNotFoundError` 之后）⇒ 其后所有行号 **+15** | 371 → 386（+15/−0） |
| 2 | `docs/execution-plane.md` | §7 重写（裁定表 4 行 · ★ 登记表为什么不能补 · ★ 守卫是单向的 · 「留给下一任务的输入」1 条）；锚点表 +15 重映射、新增 `:62` 一行；数值表 **+6 行**；§8 不再复述三个自覆盖数 | 334 → 339（+65/−60） |
| 3 | `docs/tool-runtime.md` | 两处 `_wf_actions.py` 引用 +15：`:101→116`（散文与表各一处）、裸 `:119→134`（×2，按同行位置归属） | 196（+3/−3） |
| 4 | `tests/unit/api/test_serialization_guards_stay_local.py` | +3 例（2 → 5）：**拒绝** / **不占槽** / **外国租约不否决** | 145 → 277（+136/−4） |
| 5 | `tests/unit/scripts/test_execution_plane_claims.py` | +3 扫描（写入者 / 读槽并取消 / 同一句文案）+ `_calls_within` + `_registry_declared_value_type`；**+6 条主张**；+2 例（裁定表一致 · 三个登记表扫描的阳性对照） | 617 → 893（+281/−5） |
| 6 | `tests/unit/scripts/test_docs_citations.py` | 语料下界 118 → **116**（实测值），并改掉注释里那组过期的 122/118 | 311 → 316（+7/−2） |
| 7 | `.trellis/tasks/09-19-ripple-retry-serialization/**` | 本票面 + `task.json` | 新增 |

**验收对账**（每条都能被突变单独击杀，见下）

| # | 判据 | 见证 |
| --- | --- | --- |
| A1 | 在跑时回 `skipped`、文案逐字相同 | `test_ripple_retry_refuses_while_this_process_is_running_the_thread`（m01/m02 击杀者） |
| A2 | 登记表条目仍是原来那一条 | 同一用例的 `_background_tasks["t1"] is sentinel`（m04 击杀者） |
| A3 | 没在跑时回 `retrying`、登记表仍空 | `test_ripple_retry_starts_without_taking_the_task_slot`（m04 击杀者） |
| A4 | 源码里没有 `add_done_callback` | 重算 `ripple_retry_done_callbacks = 0` |
| A5 | 消费者 `2→3`、守卫 `0→1` | 重算 `process_has_active_task_consumers_outside_the_runner = 3`、`ripple_retry_serialization_guards = 1` |
| A6 | 槽形状（结构）+ 同一句文案（配对） | 重算 `registry_declared_value_type = asyncio.Task[Any]`、`repair_paths_using_the_shared_serialization_sentence = 2` |
| **A7** | **新（突变自检补出）**：谓词是**本进程**那一个 —— 外国租约不得否决 | `test_ripple_retry_still_runs_past_a_foreign_lease`（m03 击杀者） |
| **A8** | **新（突变自检补出）**：§7 的四个裁定词与四条值主张**互相钉住** | `test_the_ruling_table_agrees_with_the_four_published_values`（m08/m09 击杀者） |
| **A9** | **新（突变自检补出）**：三个登记表扫描必须**读它被指向的树** | `test_the_registry_scans_read_the_tree_they_are_pointed_at`（m19/m20/m22 击杀者） |

**四道门禁**（`uv run …`，全部带 `CODEBUDDY_SAFE_DELETE_ENABLED=0`）

| 门禁 | 结果 |
| --- | --- |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | **548 files already formatted**（与交付前同数 ⇒ 零新增 Python 文件） |
| `mypy backend --python-version 3.12` | `Success: no issues found in 217 source files` |
| `context_compiler_baseline.py --compare --drift-pct 5` | `P1b-S5 context compiler baseline: OK` |
| `scripts/gates/tool_runtime_gate.py` | `P1c-S5 tool runtime: OK` |

**全量测试**：`3664 passed, 3 skipped`，收集总数 **3667**；交付前 `3661 passed / 3 skipped / 3664`
⇒ **+3**，逐条 = 新增的 3 例（API 1 + claims 2）。零失败，本轮连那条已知 flake 都没露出。

**突变自检：23/23 杀死**（0 存活 · 0 收集错 · 0 弱见证；`restore=OK`，三个被突变文件收尾
sha256 与开局快照逐字相等：`02e11dc0970d` / `68909d5afd88` / `af6d8e5030ab`）

分组：**守卫行为 7**（m01–m07）· **裁定表 2**（m08/m09）· **文档值 9**（m10–m18）· **检查器 5**（m19–m23）。
三条最值钱的，都是**存活/弱见证逼出来的**：

- **m03（把谓词换成 `has_active_execution`）在补 A7 之前是活的** —— 同一次运行里另外 4 条 API 用例全绿。
  这正是「守卫答什么」的**反面**：本片采纳的是**串行化**谓词，而没有任何东西钉住这个选择。
- **m08（把「采纳」改成「不采纳」）在补 A8 之前是活的** —— 裁定词是本片的**全部产出**，本来是**零读侧**。
- **m19（扫描器忽略 `root`、改读真实树）与 m22（直接返回它被派去找的答案）**：真实树上数值**照样重算正确**，
  唯一能看见它们的是**合成夹具** ⇒ 补 A9。这与账本里那条老纪律同源：**扫描器必须证明 `root` 参数不是装饰。**

**顺带修掉一处自己的过期数字。** `test_docs_citations.py` 的语料下界一度被写成 **113**（§7 重写中途量到的
中间值），交付前重量为 **116**（= 104 带路径 + 19 裸 − 7 处 host:port）。上一版的口径是**下界取实测值**，
所以 113 是一次**无意的放宽**（少 3）。改回 116，并把注释里那组更早的 122/118 一并换成实测的 123/116。
—— 这正是 §8 一直在说的那件事：**数字只有在有人替它算的时候才是数字。**

**harness 自己的三次失败也记下来**（比突变更值得写，因为下一次会重写它）

1. **锚点命中数声明错**：m02 声明 `hits=1`，实际 **2**（兄弟路径同一句文案）⇒ 预检 `PREFLIGHT-FAIL` 拦下，
   **未写任何文件**。修法：把锚点扩到含下一行的**独有**上下文。
2. **11 条 `TOO-WEAK` 是我的见证声明写错了**：`pytest -q -rf` 的 `FAILED` 行只有 **node id**、没有断言消息，
   而我把**主张 id**（只出现在消息里）当成见证 ⇒ 正确的击杀被记成"没测到"。
   见证因此改成**两个字段**：`witness`（测试名，须出现在 `FAILED` 行）+ `mentions`（片段，须出现在输出任意位置）。
3. **6 条仍 `TOO-WEAK` 且 `FAILED` 为空**：我把 `RULING` / `REGISTRY_CONTROL` 这些**测试名**直接当击杀者
   传给 pytest（要的是 `file::name`）⇒ pytest 以 **rc=4「没找到」**退出、一条都没收集。
   ⇒ 击杀者与见证**分开命名**。

   **三次的共同形状**：harness 报的是「测试没红」，真相是「**我以为在测的那条根本没跑**」。
   与账本里那条纪律同源 —— **存活/弱见证先去读日志，别先怀疑测试。**
