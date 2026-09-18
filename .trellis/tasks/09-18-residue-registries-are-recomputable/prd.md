# 让两份文档的「已知残留」变成可重算的判据

> 后续票。父任务 `09-11-runtime-upgrade` 已于 2026-09-18 关闭（PR #628），这张票处理它
> 留下来的**机制缺口**，不是它的某一条登记项。

## 0. 结论：缺的不是「记录」，缺的是「机制」

本仓已经有三种把主张变成判据的做法，且各自有先例：

| 做法 | 钉什么 | 先例 |
|---|---|---|
| `anchor-table` / `anchor-absence` | **位置**（`file:line` 上的 token 在不在） | `docs/execution-plane.md` + `tests/unit/scripts/test_docs_anchors.py` |
| `claim-table` | **数值**（文档发一个值，测试从代码重算） | `docs/planning.md` + `test_planning_claims.py`、`docs/outcome-learning.md` + `test_outcome_learning_claims.py` |
| 直接断言 | 行为 | `TestTheTwoParsersCannotBeMerged`、`ROUTERS_WITHOUT_AN_EDGE` 的反向断言 |

**五份带「残留」清单的文档里，两份一种机制都没有**：

| 文档 | 残留小节 | 机制 |
|---|---|---|
| `docs/execution-plane.md` | §7 | ✅ anchor-table + anchor-absence |
| `docs/planning.md` | §4 登记未修 | ✅ claim-table |
| `docs/outcome-learning.md` | §4 | ✅ claim-table |
| **`docs/publish-action-protocol.md`** | `## 已知残留` | ❌ **纯散文** |
| **`docs/tool-runtime.md`** | `## 已知残留` | ❌ **纯散文** |

这两节里的每一条都是**关于代码可测量的事实**（「仍无发射者」「仍无写入者」「仍直调 X」），
却没有任何东西会因为它被修好而变红。**这正好是 PR #629 修掉的那个失效模式的另一份拷贝**：
一条登记被结掉了，记录继续声称它开放，而没有任何机制察觉。

⇒ 本片的产出：**给这两节各加一个 `claim-table`，并加一个把它们从代码重算的判据。**
改的是文档与测试，**不改生产代码**。

## 1. 侦察表（全部为 2026-09-18 当天实测，探针见 §2）

| # | 文档原文主张 | 位置 | 实测（重算方式） |
|---|---|---|---|
| 1 | 「主链仍不经控制面：`publisher` 直接调 `run_publish`」 | `docs/publish-action-protocol.md:125` | `run_publish` 直接调用点 **3 处**：`backend/agents/publisher.py:480`、`backend/api/routes/_wf_actions.py:326`、`backend/api/routes/free.py:419`（AST 扫 `backend/**`，排除函数定义本身） |
| 2 | （同上，**待决问题 1 无落点**的成因）「今天没有任何产生 PublishIntent 的主链调用者」 | `docs/publish-action-protocol.md:143` | ⚠️ **`PublishIntent` 在 `backend/` 里零命中** —— 它是 P2a 票面计划行的**设计名**（`archive/2026-09/09-11-p2-action-model-mainline/prd.md:7`），落地对象叫 **`ActionIntent`**。`ActionIntent(` 构造点全仓 **1 处**：`backend/creator_agent/advisor.py:420`（控制面内）⇒ 主链产出确实为 **0**，但**主张里的名字必须换成落地名**，否则下一个读者 grep 到零命中会以为文档写错了 |
| 3 | 「`EVENT_KINDS` 的 `cost` / `error` 仍无发射者；`EVENT_KINDS` 本身除自己的 `__all__` 仍没有读者」 | `docs/publish-action-protocol.md:127-129` | `EVENT_KINDS` 定义在 `backend/db/workflow_events.py:43`、在 `:226` 的 `__all__` 里；**定义模块之外零 import**（`state/events.py:43` 只是注释里提到它，AST 看不到）⇒ 读者 **0** |
| 4 | 「`account_credentials` 表仍无写入者」 | `docs/publish-action-protocol.md:131`、`docs/tool-runtime.md:172` | `INSERT INTO (public.)account_credentials` 全仓 **0 命中**；该表只有 DDL（`db/accounts.py:70`）、一条读（`:446`）、一条清理 `DELETE`（`db/system_config.py:264`） ⇒ 写入者 **0**（**同一条事实被两份文档各说一遍**） |
| 5 | 「`_wf_actions.py:101` 的 ripple-retry 仍直调 `RippleService.submit_and_wait`」 | `docs/tool-runtime.md:164` | `backend/api/routes/` 里 import `RippleService` 的文件 **3 个**：`_wf_actions.py`、`_wf_artifacts.py`、`system.py`（后两个是进度查询与健康缓存，不是执行路径）⇒ **执行路径上的直调点 1 处** |
| 6 | 「L1 参数类型是原样反射的……没有归一化」 | `docs/tool-runtime.md:167` | ⚠️ **本条无法机械重算**（「归一化存在与否」是一个设计判断，不是树的形状）。按 `planning.md` 的先例，**不能给它编一个谓词** ⇒ 本片把它标为「未重量」并写明理由，而不是假装量了 |
| 7 | （对照用）`docs/execution-plane.md` §7「两个不持租约的 checkpoint 写入者」 | `execution-plane.md:171-172` | 已由 anchor 机制钉住，**本片不重复**。实测佐证：`_wf_actions.py`（371 行）里 `start_lease` 调用 **0**、`asyncio.create_task` **2**（`:181`、`:361`）、`aupdate_state` **3**（`:176`、`:289`、`:329`） |

**票面核对**：本票不引用任何写票时的行号；§1 的每个数字都是开工当天从树上量的。

## 2. 量化附录（探针原始输出）

探针（只读）扫 `backend/**/*.py`：AST 取 `ast.Call` 的函数名与 `ast.ImportFrom` 的 name，
SQL 用正则扫 `INSERT INTO`。原始结果：

```text
run_publish direct call sites: publisher.py:480, _wf_actions.py:326, free.py:419   -> total = 3
ActionIntent constructions:    creator_agent/advisor.py:420                        -> total = 1
EVENT_KINDS importers outside db/workflow_events.py: []                            -> 0
INSERT INTO account_credentials: []                                                -> 0
RippleService importers in api/routes/: _wf_actions.py, _wf_artifacts.py, system.py -> 3 files
start_lease( callers: _runner.py (生产唯一), execution_leases.py (定义处)            -> 2 files
_wf_actions.py: lines=371 lease_calls=[] create_task=[:181, :361] aupdate_state=[:176, :289, :329]
```

## 3. 要重写的定性：**「登记」这个词在这一仓有两种含义，混淆会静默丢东西**

- **含义 A（票面级）**：某张票在收尾时写下「这件事本片不做，留给下一个任务」。父任务的
  「八条登记」属于此类，收拢在已归档的 `task.json` 里。
- **含义 B（文档级）**：某份文档在自己的 `## 已知残留` 里声明「这里还剩什么」。同一个事实
  可能在 A 与 B 里各出现一次，也可能只在 B 里出现。

**实测：两者并不相等。** `account_credentials` 无写入者出现在**两份文档的 B 里**（§1 #4），
却**不在父任务 A 的那八条里**。所以「八条登记未修」这句话如果被读成「已知残留一共八条」，
就是错的 —— 而**没有机制能让这句话变红**。

⇒ 本片不试图把 A 与 B 合并成一张表（那会制造一个新的、更难维护的副本）；本片刻意做的是
**让 B 变成可重算的**，这样 A 与 B 的差集至少是**可枚举**的，而不是靠人去读散文对。

## 4. 切片表

| 片 | 内容 | 独立 PR | 依赖 |
|---|---|---|---|
| **S1** | 两份文档各加一个 `claim-table`；新建 `tests/unit/scripts/test_residue_claims.py` 重算它们（闭环三向 + 零值主张的阳性对照）；把 §1 #2 的落地名与 §1 #6 的「未重量」写进文档 | ✅ | 无 |

## 5. 红线 / 拒绝

- **不改任何生产代码**（`backend/**` 一行不动）。本片只改 `docs/**` 与 `tests/**`。
- **不修任何一条残留**。它们的处境不因被量过而改变；本片只让「被修好了」这件事**变红**。
- **不给 §1 #6 编谓词**。量不出来的主张宁标「未重量」，也不写一个恒真的检查。
- **不把两份文档的 `account_credentials` 那一条合并成一处引用** —— 两份文档各自要被单独读懂，
  这是既有取舍，本片不推翻（判据里会对同一个谓词跑两次，代价可接受）。
- 不引入新依赖；`claim-table` 的标记沿用 `planning.md` 的既有拼写。

## 6. 验收

1. 两份文档的 `## 已知残留` 各含一对 `claim-table` 标记，且标记成对、块内有行（防静默截断）。
2. 每条已发布的主张都有一个重算器；每个重算器都在文档里被发布（双向闭环）。
3. 至少 4 条主张的发布值是 **0 / 空集**（「没有读者」「没有写入者」「没有主链产出者」），
   **每条零值主张都要有阳性对照** —— 把同一个扫描器指向一个「东西确实存在」的目录，
   证明它还能发现东西。**没有对照的零值主张 = 一个被掏空的检查器也能让它保持绿。**
4. 有一条阳性对照证明**测试夹具本身有区分力**（构造一个「有写入者」的样本，断言扫描器答 1）。
5. 四道门禁全绿，且 `passed + skipped` 的增量恰好等于新增用例数。

## 7. 待决裁定

- **残留在文档之间的重复要不要收敛？** 本片取「不收敛」（见 §5）。若将来同一事实在三份以上
  文档里出现，再考虑「一处声明 + 其余引用」的写法，并给引用本身加一条存在性断言。

## 8. 执行记录（S1，2026-09-18）

**落地**：`docs/publish-action-protocol.md` + `docs/tool-runtime.md` 各加一对 `claim-table` 标记
（共 7 条主张）；新增 `tests/unit/scripts/test_residue_claims.py`（7 条用例）。**生产代码零改动**。

**发布的主张与实测值**：

| id | 值 | 出现在 |
|---|---|---|
| `mainline_run_publish_direct_call_sites` | `3` | publish-action-protocol.md |
| `action_intent_construction_sites` | `1` | publish-action-protocol.md |
| `mainline_action_intent_producers` | `0` | publish-action-protocol.md |
| `event_kinds_readers_outside_its_defining_module` | `0` | publish-action-protocol.md |
| `account_credentials_inserts` | `0` | **两份都有**（刻意的重复） |
| `api_route_modules_importing_ripple_service` | `3` | tool-runtime.md |
| `ripple_service_direct_call_sites_in_api_routes` | `2` | tool-runtime.md |
| `tool_gate_allowed_prefix` | `backend.tools.runtime.` | tool-runtime.md |

**顺带改掉的两处命名/遗漏**（都在本片的文档改动里）：计划行的 `PublishIntent` 在 `backend/`
零命中 ⇒ 写明落地名 `ActionIntent`；`tool-runtime.md` 原先只点 `_wf_actions.py:101`，
同文件 `:119` 还有第二处 `submit_and_wait` ⇒ 补上。

**突变自检：10/10 杀死**（每条指名见证者测试；每条突变前重写原文、之后复验基线仍绿）：
published 值漂移 · 零值主张被写成非零 · 两份文档的同名主张互相矛盾 · 发布一条没有重算器的行 ·
掏空 `run_publish` 扫描器 · 掏空 `EVENT_KINDS` 扫描器（**只有阳性对照能看见**）·
把凭据扫描器放宽成匹配表名 · 删掉一个 `claim-table:end` 标记 · 去掉「控制面之外」过滤器 ·
把行解析器放宽成不要求反引号（**由孤立检查抓住，不是重算检查**）。

★ **harness 自己第一次报出全绿假象**，两个 bug：`witness in failed` 对 list 是**精确匹配**而非子串
（9 条全误报 SURVIVED）；跨行锚点里的 `\n` 永远匹配不到 CRLF 文件（2 条报 TOO WEAK 而根本没被应用）。
**本仓第一号老坑第二次咬人** —— 修法是先归一化成 LF 再匹配、回写时按原文件 EOL 还原。

**门禁**（2026-09-18）：

| 门禁 | 结果 |
|---|---|
| `pytest tests/ -q` | **3638 passed / 3 skipped** —— 上一片收集总数 3634 ⇒ **+7 = 恰好 7 条新测试**，零既有用例被改动 |
| `ruff check .` | All checks passed |
| `ruff format --check .` | **545 files**（544 ⇒ **+1**，就是新文件） |
| `mypy backend --python-version 3.12` | 217 source files（不变） |
| Context Compiler Baseline | drift within threshold |
| Tool Runtime Gate | OK |

★ 两条免费的强断言都对上了：**passed 增量 = 新测试条数**，且 **ruff 文件数增量 = 新文件数**。

**工具侧的一处自省**：回写 `task.json` 的脚本把「EOL 纯 CRLF」的断言放在了 `write_bytes`
**之后**，于是它自己先把 4 行 LF 写进了一份 CRLF 文件、再报断言失败。**断言要跑在「打算写进去的
字节」上，不是跑在写完之后的文件上** —— 与「先归一化再校验」是同一条纪律的另一面。
