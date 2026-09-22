# §7 的代价模型要能被重算，全文行号要能被解析

> 后续票。`09-18-residue-registries-are-recomputable`（PR #630）把两份文档的 `## 已知残留`
> 变成了可重算的；这张票处理**同一失败模式的第三份拷贝**：`docs/execution-plane.md`
> —— 一份**自称已被机制覆盖**的文档。

## 0. 结论：这份文档的机制是真的，但**覆盖范围**是假的

`docs/execution-plane.md:5` 写着：

> 本文件里的每条 `file:line` 都由 `tests/unit/scripts/test_docs_anchors.py` 钉住 ——
> 改动那些行会让测试变红，而不是让文档悄悄过期（见 §8）。

**这句话有两个问题**：机制只覆盖被标记括起来的表（§6 / §6.1 / §8），而**散文里的行号一个都没钉**。

| 量 | 实测（2026-09-18） |
|---|---|
| 全文 `file:line` 引用（带路径） | **66** |
| 全文裸 `:N` 引用 | **18** |
| 合计行号引用 | **84** |
| `anchor-table` 行数 | 43 |
| `anchor-absence` 行数 | 8 |
| **被标记表钉住的** | **51** |
| ★ **未被任何机制覆盖的** | **33** |

⇒ 散文里的 33 处行号**没有任何东西**在它们过期时变红。本片实测到它们**已经坏了**（见 §1）。

## 1. 侦察表（全部为 2026-09-18 当天实测，探针见 §2）

| # | 文档原文 | 位置 | 实测 |
|---|---|---|---|
| 1 | 「给 `_run_retry` 补注册表写入 —— **一行**，与 `:3008` 同形；**不改变执行语义**，只是让 `/recover` 看得见它。」 | `execution-plane.md:184` | ❌ **两个论断都错**（见 §3） |
| 2 | 同上一句的 `:3008`（另一处：「对比 `:3008` 的 publish-retry 有」） | `execution-plane.md:177`、`:184` | ❌ **`:3008` 不可能存在**：`_wf_actions.py` 全文 **371 行**。真实位置是 `:363`（§8 的表里写对了，两处不一致） |
| 3 | `_wf_models.py:31` `async_mode: bool = Field(default=True` | `execution-plane.md:16` | ⚠️ 只写文件名 ⇒ 从仓根解析不到；真实路径 `backend/api/routes/_wf_models.py` |
| 4 | `_takeover.py:136` 的闸门 / `_takeover.py:105` `_consider` | `execution-plane.md:43`、`:87` | ⚠️ 同上；且 `:83` 对**同一个事实**写的是全路径 `backend/api/routes/_takeover.py:136` ⇒ 一处两种写法 |
| 5 | 「本文件里的每条 `file:line` 都由 `test_docs_anchors.py` 钉住」 | `execution-plane.md:5` | ❌ 51/84 —— **机制的自述也过期了** |
| 6 | （对照）§7 的其余数字：`_runner.py:390` 定义、`start_lease(` 只在 `:418`、`_run_graph_and_persist` **12 个调用点**、`_wf_actions.py:97`/`:319` 两个定义 | §7 | ✅ **全部正确**（程序的复核见 §2） |

★ 六条里 **4 条错**，而其中 **3 条（#1 #2 #5）是「文档关于自己的声称」** —— 这正是本仓反复
付代价的那个形状：**承袭来的文字不会被自己的机制检查，因为机制的覆盖范围也是承袭来的。**

## 2. 量化附录（探针原始输出）

```text
process_has_active_task   def=_runner.py:48   in-module call=_runner.py:91
                          outside=2  [_wf_actions.py:228, _wf_application.py:1675]
has_active_execution      outside=7  [_wf_application.py:324,506,747,1046,1077,1293, _wf_runtime.py:314]
_wf_actions.py            371 行; create_task=[181,361]; _background_tasks[=[363]; gather=[138]; start_lease=0
ripple_timeout            1800.0 (@:95) 用于 :116 与 :135 两处 max_wait
submit_and_wait           :101, :119 —— 由 :138 的 asyncio.gather 并发消费
_run_graph_and_persist    def=390, call sites=12  ✅
start_lease call sites    1 (_runner.py:418);  def=execution_leases.py:496  ✅
_wf_actions.py:97/_run_retry, :319/_run_publish_retry  ✅
行号解析                  解法见 §4；当前 5 处失败（2× :3008、3× 裸文件名）
```

## 3. 要重写的定性：**「一行」是行数，不是代价**

`_run_retry`（`_wf_actions.py:97`）与 `_run_publish_retry`（`:319`）今天都直接
`graph.aupdate_state`。差别只在**注册表**：`:361` 起的 publish-retry 有
`task.add_done_callback(...)` + `_runner._background_tasks[thread_id] = task`，ripple-retry 没有。

文档说补上它是「一行，**不改变执行语义**」。实测不成立 —— `_background_tasks` 是
`process_has_active_task()`（`backend/api/routes/_runner.py:48`）的或条件之一：

| 消费者 | 读到 True 时做什么 |
|---|---|
| `_wf_actions.py:228`（publish-retry 守卫） | 直接回 `skipped`「工作流正在运行，无法重试。」 |
| `_wf_application.py:1675`（brief 上传自动 resume） | `if not has_active and next_nodes:` ⇒ **静默不 resume**（`:1670-1674` 的注释恰好警告过这个静默失效） |

**并波及第三种读者**：`process_has_active_task` 被 OR 进
`has_active_execution`（`_runner.py:91`），后者有 **7 个**状态侧消费者 ⇒ 注册之后
「running vs stale」的答案也会变。

**窗口**：`:101` / `:119` 两个 `submit_and_wait` 由 `:138` 的 `asyncio.gather` **并发**消费，
`max_wait=ripple_timeout`（`:95` = 1800.0）⇒ 不是 2 × 1800，而是 **1800 秒（30 分钟）**。

⇒ 于是「补一行」的真实形状是一次**对换**，而不是一次修复：

- 今天：ripple-retry 与别的任务**并发**写 checkpoint、无人管理（P2b 已登记的那件事）。
- 注册之后：换成**30 分钟内**静默拒绝重试 / 静默跳过 resume（`/resume` 还会直接
  `cancel()` 掉在飞的 ripple-retry，见 `_wf_runtime.py:331`）。

**哪个更好要裁定**，而裁定必须带着 1800s 这个数字做，不能带着「一行」做。

## 4. 要引入的机制：**两件，各管一类**

| 机制 | 管什么 | 先例 |
|---|---|---|
| `anchor-table`（§7 新增一对） | **位置**：§7 引用的每个 `file:line` 上必须逐字出现某个 token | §6 / §6.1 / §8 |
| `claim-table`（§7 新增一对） | **数值**：行数、消费者数、窗口、注册数 | `planning.md`、`outcome-learning.md`、本仓新加的 `residue` 那对 |
| **行号解析规则**（新判据，无表） | **全文 84 处行号引用都必须解析得到、且在范围内** | 本片新立 |

行号解析规则的形状（这一条是本片的**主产出**）：

- `` `path:line` `` ⇒ 相对仓根解析，文件必须存在，`0 < line <= len(file)`；
- `` `:line` ``（裸）⇒ 归属到**同一 `##` 节内最近一次出现的完整路径**（这正是裸引用对读者的含义）；
- 因此**不允许** `` `_takeover.py:136` `` 这种「有文件名、没有目录」的写法 —— 它解析不到，
  而同一个事实在 `:83` 明明写了全路径。

★ 规则对**当前文档**跑过：84 处里 79 处通过、5 处失败（解出 §1 的 #2 #3 #4）。本片把这 5 处
修好，规则才有资格进 CI。**先量规则、再让规则上岗** —— 反过来会得到一条恒红的判据。

## 5. 红线 / 拒绝

- **不改任何生产代码**（`backend/**` 一行不动）。本片只改 `docs/**` 与 `tests/**`。
- **不改 §7 那条裁定**。`start_lease` 的两条修复路径照旧是「登记未修」；本片只让它的**代价**可被重算。
- **不给散文里的每个行号都编一个 token 断言**。84 处里只有被标记表覆盖的才有 token；其余只保证
  「解析得到、在范围内」。**这个上界要写进文档**（§0 的自述改成精确的）。
- **不推翻既有的两张表**（§6 的 34 条分类、§8 的 8 条缺席）。只增行、不改行。

## 6. 切片表

| 片 | 内容 | 独立 PR | 依赖 |
|---|---|---|---|
| **S1** | §7 修 `:3008`×2 与 3 处裸文件名、重写「一行」那条、给 §7 加 `anchor-table` + `claim-table` 各一对、§0 自述改精确；新建 `tests/unit/scripts/test_execution_plane_claims.py`（行号解析规则 + claim 三向闭环 + 阳性对照） | ✅ | 无 |

## 7. 验收

1. 全文每个行号引用都解析得到、且在范围内（含裸 `:N` 的节内归属）；判据在**当前**文档上绿。
2. §7 的每个数字都有一个重算器；每个重算器都在 §7 被发布（双向闭环，同 `residue` 那对）。
3. 每条**零值/布尔**主张都有阳性对照：把同一个扫描器指向一个「东西确实存在」的目录。
   - `ripple_retry_task_registrations` = 0 ⇒ 对照必须答 1（拿 publish-retry 那段真实相邻代码做样本）。
   - `ripple_retry_submits_are_concurrent` = true ⇒ **对照必须答 false**（一段串行样本），
     否则「并发」这个事实只能被一个恒真的检查器发布。
4. 行号解析规则自身有对照：一份**故意坏掉**的夹具文档（越界行号 + 裸文件名 + 无前驱路径的裸引用）
   必须让规则报出全部三类问题。
5. 四道门禁全绿，且 `passed + skipped` 的增量恰好等于新增用例数。

## 8. 待决裁定

- **§7 第 1 条该不该真的去做（注册 ripple-retry 任务）？** 本片只把代价钉住，不做对换。
  裁定要在「并发写 checkpoint」与「30 分钟静默拒绝/跳过」之间选，本片两面都留了数字。

## 9. 执行记录（S1，2026-09-18）

**落地**：`docs/execution-plane.md` 八处改动 + 新建 `tests/unit/scripts/test_execution_plane_claims.py`
（**10 条用例**）。**生产代码零改动**（只改 `docs/**` 与 `tests/**`）。

**发布的主张与实测值**（§7 八个 + §8 三个，全部由判据从代码重算）：

| id | 值 | 出现在 |
|---|---|---|
| `process_has_active_task_consumers_outside_the_runner` | `2` | §7 |
| `status_consumers_of_has_active_execution` | `7` | §7 |
| `run_graph_and_persist_call_sites` | `12` | §7 |
| `start_lease_call_sites_under_backend` | `1` | §7 |
| `ripple_retry_max_wait_seconds` | `1800.0` | §7 |
| `ripple_retry_task_registrations` | `0` | §7 |
| `publish_retry_task_registrations` | `1` | §7 |
| `ripple_retry_submits_are_concurrent` | `true` | §7 |
| `line_number_references_in_this_document` | `102` | §8 |
| `line_numbers_pinned_by_marked_tables` | `56` | §8 |
| `bare_line_number_references_in_this_document` | `16` | §8 |

**修掉的引用腐烂**：`:3008` ×2（文件只有 371 行）· `_wf_models.py:31` / `_takeover.py:136` /
`_takeover.py:105`（裸文件名，从仓根解析不到）· §0 自称「每条 `file:line` 都由
`test_docs_anchors.py` 钉住」而实测 51/84 ⇒ **机制的自述也是承袭来的文字**。

**§7 第 1 条重写后的形状**：行数确实是 1，但代价不是行数。`_background_tasks` 是
`process_has_active_task()` 的或条件 ⇒ 两个消费者读到 True 都不干活（`:228` 回 `skipped`、
`:1675` 静默不 resume），且经 `_runner.py:91` 波及 `has_active_execution` 的 7 个状态侧消费者；
窗口 1800 秒（两个 submit 由 `:138` 的 `gather` 并发）⇒ 它是**对换**，不是修复。

**突变自检：17/17 杀死**（零存活、零 TOO WEAK；每条指名见证者，突变前重写、之后复验基线仍绿）：

发布值漂移（×6，含零值主张被写成非零）· 丢弃一行主张（孤儿重算器）· 发布一条没有重算器的行 ·
删掉一个 `claim-table:end` · **把 `:3008` 原样放回** · 引用丢掉目录 · 行号越界一格
（由既有 `test_docs_anchors.py` 抓）· 消费者扫描忘了排除定义模块 · 并发扫描被写死成常量 ·
注册扫描不再找那一次存储 · 解析规则被掏空成常量 · 裸引用按类别分组（归属错文件）。

★ **解析规则的第一版就有 bug，而且是跑真文档时抓到的**：它把同一行的所有路径与所有裸引用分两批
处理，于是 §0 那行（`_wf_application.py:271` → `:275` → `_wf_models.py:31`）里的 `:275` 被归给了
**后面**那个 195 行的文件。修法是按位置排序；并把「裸引用归属同行的前一个路径」写成**带区分力**的
夹具（`:9` 在 11 行文件里合法、在 3 行文件里越界）⇒ 归属错的规则无法沉默通过。

★ **模式不带扩展名白名单**：早一版列了扩展名，于是静默漏掉 `Dockerfile:81`。**看不见的引用
不可能红**，而白名单正是引用藏身的地方。

**门禁**（2026-09-18）：

| 门禁 | 结果 |
|---|---|
| `pytest tests/ -q` | **3648 passed / 3 skipped** —— 上一片 3638 ⇒ **+10 = 恰好 10 条新用例**，零既有用例被改动 |
| `ruff check .` | All checks passed |
| `ruff format --check .` | **546 files**（545 ⇒ **+1**，就是新文件） |
| `mypy backend --python-version 3.12` | 217 source files（不变） |
| Context Compiler Baseline | drift within threshold |
| Tool Runtime Gate | OK |

★ 两条免费的强断言又都对上：**passed 增量 = 新用例数**，**ruff 文件数增量 = 新文件数**。

**工具侧的一处事故（记在这里因为它是可复现的）**：
`git checkout -- docs/execution-plane.md tests/unit/scripts/test_execution_plane_claims.py` ——
其中一个路径**未跟踪**，git 在 pathspec 阶段就整体失败、**什么都没回退**，而我据此以为「改动已丢」
并差点重做。⇒ **`git checkout --` 的成败必须看退出码，不能看随后的 `git status`**：未跟踪文件
根本不出现在 diff 里，「工作树干净」与「命令没执行」长得一模一样。本片改完**立刻提交**，
就是为了让这类误判不再有代价。
