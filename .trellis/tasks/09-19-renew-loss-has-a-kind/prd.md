# prd：失去租约的两种方式 —— 让 `renew` 的「不是你的」与「问不到」分开

> 票号 `09-19-renew-loss-has-a-kind` · 上一片 `09-19-lease-refusal-has-a-reason`（PR #636）
> 入口：那片 §7 第 1 条（本仓根 `.trellis/tasks/09-19-lease-refusal-has-a-reason/prd.md`）

## 0. 这一片要回答什么

`renew` 返回 `bool`，而它的 `False` 有两个来源：**这一行已不是本实例的**（`LOST`）
与**存储答不上来**（`UNKNOWN`）。上一片已裁定：两者**都要停**（红线 4：同一 checkpoint
不许两个写者），所以**行为上没错** —— 错的是这两件事被写成了一个 `False`：

1. 日志把一次存储故障记成一次「租约丢失 / 被接管」，而那不是事实；
2. 将来任何一次「让 `renew` 宽容一点」的改动都会**静默地**把「确知被接管」一起放宽。

本片把它们分成两个值，让心跳把它拿到的**那一个**带出仓，并**把裁定写进判据**：
两档都停是裁定，不是对称 —— 判据读的是比较的**方向**，所以把它写成 `is LOST` 会红。

★ 安全方向与 `acquire` **相反**（上一片 §4 裁定 D）：那边「问不到**要照跑**」，
这边「问不到**照停**」。这不是风格问题：没有租约就开始的 run，风险是**白干**；
丢了租约还在写的 run，风险是**同一 checkpoint 两个写者**。

## 1. 现状侦察表（每条都对树核过；行号是**动代码前**的值）

| # | 事实 | 位置（动前） |
| --- | --- | --- |
| P1 | `renew` 有 **4** 个 `False` 出口：空 id · 内存分支「不是我们的」· `except`（「问不到」）· `renewed` 假（SQL 行数 0） | `execution_leases.py:428 / :437 / :448 / :449` |
| P2 | `_heartbeat_until_cancelled` 对 `False` 只做一件事：`return`（任务**正常结束**，不是 cancelled） | `:561` |
| P3 | `_fence_on_lost_lease` 的判据**只有** `task.cancelled()` ⇒ 「心跳正常结束」= 丢了租约，**不看原因** | `_runner.py:378-380` |
| P4 | 栅栏对 `owner.cancel()`；12 个 `_run_graph_and_persist` 调用点里 **10 处是 `await` 内联**（调用者正在等那个 HTTP 响应），**2 处**在 `create_task` 起的嵌套协程里 | 见 §2 |
| P5 | ★ 模块**已经声明**了一份容忍预算，而心跳**没有用**它：`HEARTBEAT_MISSES_BEFORE_EXPIRY = 3`、`LEASE_TTL_SECONDS = 90.0`，注释写「At least two misses must fit before expiry, otherwise a single slow renew would make a live owner look dead」 | `:83-85` + `:78-82` |
| P6 | `renew` 在 `__all__` 里（公共面），但**全仓只有 1 个调用点** —— 就是那个心跳 | `:656` / `:561` |
| P7 | `docs/execution-plane.md:55` 引 `execution_leases.py:78/:79/:80` 说那三个常量 ⇒ **过期 5 行**（真身 `:83/:84/:85`），而引用判据答「解得到」（文件 371 行） | 见 §2 |

## 2. 量化附录（探针原文，可复核）

### 2.1 12 个 `_run_graph_and_persist` 调用点的形状（P4）

| 文件:行 | 形状 |
| --- | --- |
| `blogger.py:118` · `optimization.py:93` · `optimization.py:157` · `review.py:204` · `review.py:385` | `await` 内联 |
| `_wf_application.py:250` | 在 `async def _run_async()` 里，由 `:258 asyncio.create_task` 起（**后台**） |
| `_wf_application.py:275` | `await` 内联，且外层 `contextlib.suppress(asyncio.CancelledError, WorkflowCancelledError)` ⇒ **栅栏的 cancel 会被吞掉** |
| `_wf_application.py:802 / :828 / :855 / :898` | `await` 内联 |
| `_wf_runtime.py:343` | 在 `async def _resume_async()` 里，由 `:351 asyncio.create_task` 起（**后台**） |

⇒ **10 : 2 是内联**。内联那 10 处里，被栅栏 cancel 掉的是**调用者正在等的那个 HTTP 响应**。

### 2.2 预算的不对称（P5）

| 侧 | 容忍几次续租失败 | 出处 |
| --- | --- | --- |
| 扫描（判过期） | `HEARTBEAT_MISSES_BEFORE_EXPIRY - 1` = **2** | `:83` 的常量 + `is_stale`（`heartbeat_at + ttl <= now`） |
| 拥有者（自己停） | **0** | `:561` 的循环在第一个非 `RENEWED` 上就 `return` |

⇒ **拥有者对自己比整个系统对它更严。** 这是本片**不**裁定的那半条（§5 登记）。

### 2.3 `renew` 与 `renew_outcome` 的调用点（P6）

| 名字 | 全仓调用点 | 读法 |
| --- | --- | --- |
| `renew` | **0** | 心跳不再问布尔的那个问题；这个 `0` 说的是「没有第二个消费者」，**不是**「没有续租」 |
| `renew_outcome` | **2** | 投影一处（`renew` 自己）+ 真正读它的那一处（`_heartbeat_until_cancelled`） |

### 2.4 P7 是一条**新失效面**（本片不修，登记）

现有引用判据只答「`:N` 解得到」。`execution_leases.py:78` **解得到**照样是错的 ——
它上面是注释而不是那个常量。量法：一条引用后面紧跟一个反引号片段，取其中第一个标识符，
问它在那一行上有没有出现。**全文 19 条这种写法，8 条答「没有」**；本片就地修掉 2 条
（§1 的栅栏行、§2 的 TTL 行），余 **6** 条：

| 引用 | 声称 | 那一行实际是 |
| --- | --- | --- |
| `execution_leases.py:569`（动前） | `acquire_outcome` | `async def start_lease(` |
| `_wf_actions.py:120` | `async def _run_retry()` | 一句注释（真身 `:154`） |
| `_wf_actions.py:350` | `async def _run_publish_retry()` | `force_retry = bool(...)`（真身 `:393`） |
| `_wf_application.py:1516` | `delete_workflow` | `bg_task = _runner._background_tasks.get(...)` |
| `execution_leases.py:248` | `WHERE` | `_ACQUIRE_SQL = """` —— **不是错**，是规则误判 |
| `execution_leases.py:78` | `HEARTBEAT_MISSES_BEFORE_EXPIRY = 3` | 一句注释（本片修成 `:83`） |

★ 这张表**不进文档**：它是个数字（19/8/6），而本片不实现那条规则 ⇒ 没有已提交的判据
能重算它。票是历史记录（`docs_citation_rule.py` 的 docstring 明说 `.trellis/` 里的引用
不被维护），数字放这里，规则留给下一片。

## 3. 裁定

### 裁定 A：`renew` 拆成三值，`renew` 变投影（**采纳**）

新增 `RenewOutcome`（`RENEWED` / `LOST` / `UNKNOWN`）与 `renew_outcome`；
`renew` 变成 `await renew_outcome(...) is RenewOutcome.RENEWED`。

**行为边界（可量）**：`False` 的语义**一字未变** —— 两档都投影成 `False`。
`tests/unit/db/test_execution_leases.py` 里 **6 条既有 `renew` 断言一字未改、仍全绿**，
这就是「没有改行为」的证据，不是我的陈述。

### 裁定 B：心跳把原因**带出去**（**采纳**）

`_heartbeat_until_cancelled` 从 `-> None` 变 `-> RenewOutcome`，`return` 它停下的那个值。
`_fence_on_lost_lease` 的 done 回调从 `task.result()` 读它（`.exception()` 先挡一道：
一个抛异常的心跳会让 `result()` 在回调里重抛，而 asyncio 只把它记进日志 ⇒ 那等于放任
一个死掉的租约继续写）。

**为什么不做成新参数**：`LeaseHold.heartbeat` 已经是那个跨边界的对象，`task.result()`
就是它自带的载荷 —— 不新增状态、不新增签名。

**不变量**：栅栏的**判据没变**（仍只看 `task.cancelled()`），两档都停。

### 裁定 C：日志说实话（**采纳**）

改前的那句话对两档都印「execution lease lost for …」—— 一次存储故障被记成一次接管，
而这是这段代码**担保不了**的断言。改后分两句：`lost` / `unconfirmed`。

### 裁定 D：容忍预算 **登记不裁定**（**本片不动**）

见 §5 第 1 条。方向已经可以讨论了（原因有了名字），但裁定它要带着 §2.2 的不对称
与 §2.1 的「10 处内联」一起做。**红线 4 仍然压着这一格。**

## 4. 切片表

| 切片 | 内容 | 判据 |
| --- | --- | --- |
| S1 | `RenewOutcome` + `renew_outcome` + `_renew_in_memory`；`renew` 变投影；`LeaseHold.heartbeat` / `end_lease` 的类型跟着走 | `tests/unit/db/test_renew_outcome.py`（12 条） |
| S2 | 心跳 `-> RenewOutcome` 并分档记日志；栅栏读 `task.result()` 并分档记日志 | 扩 `tests/unit/api/test_lease_fence.py`（+3）、`test_execution_leases.py`（1 条变强） |
| S3 | 文档 §1/§2 与两张表；claims judge 的重算器与正对照 | `tests/unit/scripts/test_execution_plane_claims.py`（6 条新主张 + 1 组新正对照） |

## 5. 红线 / 不做 / 验收

**不做**：

- 不改任何**决定**：两档都停（裁定 D 结论的一部分是「不改」）；
- 不改 `_fence_on_lost_lease` 的判据（仍是 `task.cancelled()`）；
- 不改 `acquire` / `acquire_outcome` / `_takeover._consider` 的任何东西；
- 不删 `renew()` —— 它在 `__all__` 里，是仓外的便捷投影；仓内 0 个调用点是**事实**，
  已写进主张表并注明是哪种 0；
- 不实现 §2.4 那条具名锚点规则（登记，§2.4 已带完整的量与量法）。

**验收**：

1. 两个后端对同一场景答同一个成员（内存后端的集合是子集，**不含 `UNKNOWN`**，由 AST 读出）；
2. `renew` 是投影：三条成员各一条参数化断言；
3. 心跳在三档上：`RENEWED` 继续跑、`LOST` 停并返回 `LOST`、`UNKNOWN` 停并返回 `UNKNOWN`；
4. 栅栏在 `LOST` 与 `UNKNOWN` 上都栅栏，且日志说的是**两个不同的词**；
5. 6 条既有 `renew` 断言一字未改仍全绿；门禁四道全过；全量 pytest 绿。

## 6. 登记未修（带理由，本片不动）

1. **容忍预算**（裁定 D）—— 见 §5 第 1 条（文档侧）。
2. **`release` 的 4 个出口** —— 同形，后果轻（`end_lease` 不据此做决定），**未量**。
3. **具名锚点** —— §2.4，规则与量都给了，但**不进文档**（无判据可重算）。
4. **`_wf_application.py:275` 那处的 `contextlib.suppress`** 会吞掉栅栏的 cancel ——
   它是 §2.1 里唯一「内联但不会 abort 调用者」的一格。**本片只量，不裁定。**

## 7. 留给下一任务的输入

1. **`renew` 的容忍预算**（裁定 D）。方向的**对象**已经有了：`UNKNOWN` 与 `LOST` 是两个值。
   要动它就得带着 §2.2（扫描 2 次 vs 拥有者 0 次）与 §2.1（10 处内联 ⇒ abort 的是
   HTTP 响应）一起裁定。取证方式：先证明「一次抖动」在日志里可识别（本片刚给了它一个名字）。
2. **具名锚点规则** —— §2.4 有完整的量（19/8/6）与量法；它的**自有风险**是
   `execution_leases.py:248` 那种「引用整条语句」的写法会被误判，规则要能区分
   「指那一行的名字」与「指那一行开始的块」。
3. **`release` 的 4 个出口**（§6 第 2 条）。

上面 §2.2 与 §2.3 的数值都有可重算的判据：扫描侧的容忍 **2** 由
`misses_the_scanner_tolerates` 重算，拥有者侧「第一个非 `RENEWED` 就停」由
`heartbeat_stops_on_every_non_answer` 重算，`renew` / `renew_outcome` 的调用点 **0 / 2**
各一条（三者都在 `tests/unit/scripts/test_execution_plane_claims.py`）。§2.4 的 **19/8/6**
是**记录**：本片没为它写规则（§6 第 3 条）。

## 8. 执行记录

**改动表**（7 个已跟踪文件 / **+422 −88**，外加 2 个新文件）

| 文件 | ± | 内容 |
| --- | --- | --- |
| `backend/db/execution_leases.py` | +106 / −27 | `RenewOutcome`；`renew_outcome` + `_renew_in_memory`；`renew` 变投影；心跳 `-> RenewOutcome` 并分档记日志；`LeaseHold.heartbeat` / `end_lease` 类型 |
| `backend/api/routes/_runner.py` | +24 / −6 | 栅栏从 `task.result()` 读原因（`.exception()` 先挡一道）；分档日志 |
| `docs/execution-plane.md` | +39 / −26 | §1 栅栏行、§2 保证 2 + 不保证 4、TTL 脚注的 `:78→:83`、§7.1 第 1 条关闭；锚点表 10 处重定位 + 6 行新增；主张表 6 行新增；三处自计数 |
| `tests/unit/api/test_lease_fence.py` | +125 / −24 | 替身改为返回真 `RenewOutcome`；新类 `TestTheFenceNamesWhatStoppedIt`（3 条）；`test_a_cancelled_heartbeat_does_not_fence` 加「回调里不许 `Exception in callback`」 |
| `tests/unit/db/test_execution_leases.py` | +4 / −2 | `test_heartbeat_stops_when_the_lease_is_lost` 钉住返回的是哪个成员 |
| `tests/unit/api/test_repair_paths_take_the_lease.py` | +3 / −3 | 替身改为返回真 `RenewOutcome` |
| `tests/unit/scripts/test_execution_plane_claims.py` | +121 / −0 | `_misses_the_scanner_tolerates` + `_heartbeat_stops_on_every_non_answer`；6 条主张；扩正对照 |
| `tests/unit/db/test_renew_outcome.py` | 新 267 行 | 12 条用例 |

**门禁**

| 项 | 结果 |
| --- | --- |
| `ruff check .` | All checks passed |
| `ruff format --check .` | **551** files（550 + 1 = 新测试文件）|
| `mypy backend` | **217** source files，0 issue |
| `scripts/gates/tool_runtime_gate.py` | P1c-S5 tool runtime: OK |
| 全量 `pytest` | **3699 passed / 3 skipped**（3683 ⇒ **+16** = 12 + 3 + 1）|
| 突变自检 | **29/29**，`baseline=clean  restore=YES` |

★ 全量里的 `RuntimeWarning: coroutine '_heartbeat_until_cancelled' was never awaited`
是**既有**的：把本片改动 stash 掉、在 `2f0e4802` 上单跑
`tests/unit/api/test_publish_retry.py tests/unit/api/test_recover.py` 同样是
**20 passed / 4 warnings**（当前树也一样）⇒ 与切片无关，只是 GC 归属的计数会在整轮里浮动。

**突变自检首轮 25/29 → 第二轮 29/29，四条 UNWITNESSED 全是判据/测试不够紧**（不是代码缺陷）：

| 首轮 | 为什么没被指定的 witness 杀 | 修法 |
| --- | --- | --- |
| M7 方向扫描把 `IsNot` 写成 `NotEq` | 正对照只放了**错的写法**（`is LOST`），而 `IsNot`/`NotEq` 对错写法都答 False | fixture 里同时放**对的写法**（另一个函数名），断言 True |
| M8 容忍扫描丢掉 `- 1` | 那个 `- 1` 在 **lambda 里**，而正对照自己做减法 | 把减法抽成 `_misses_the_scanner_tolerates(path)`，主张与对照都调它 |
| M10 两个成员共用同一个值 | `_enum_members` 数的是「类体里被赋值的**名字**」，而别名仍是名字（答 3） | **登记**：性质由命名测试守着（witness 改成 `FENCE_UNKNOWN`），不新加一行同类主张 |
| M25 删掉 `if task.cancelled(): return` | 对 `lost` 是 **no-op**（`task.exception()` 在已取消任务上抛 `CancelledError`，asyncio 吞掉）⇒ 当时只是被行号位移**顺带** ping 到 | 给测试加真断言：回调里不许出现 `Exception in callback` |

★ 后两条是**量出来的**，不是推的：M10 的盲区由「别名仍计一个名字」解释，M25 的无效由
「事件两样都不置」解释 —— 它们分别写进 harness 的注释与测试的 docstring。

## 9. 附录：本片自检

- 突变自检 harness：`C:/Users/jamer/aiworks/_mut_renew_kind.py`（**保留**，本文件 §8 引用它）。
  ★ 上一片 `09-19-lease-refusal-has-a-reason` 的 harness 已在收尾清理时被误删，而它的 prd §8.4
  引用着它 ⇒ 那条引用已由 PR #637 改成「记录、不是可重跑的命令」。**本片保留清单按
  `git grep "aiworks/_"` 推出，不按「谁刚写的」推。**
- 探针（一次性，不保留）：`_probe_named_anchors.py`（19/8 那个量）、`_patch_lease_doc*.py`（文档原子补丁）。

