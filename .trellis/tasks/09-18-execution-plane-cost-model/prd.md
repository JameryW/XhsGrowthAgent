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
