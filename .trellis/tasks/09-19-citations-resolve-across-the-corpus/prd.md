# 09-19-citations-resolve-across-the-corpus

## 0. 一句话

`docs/execution-plane.md` §8 宣布了「**新写的引用一律写全路径**」，并把这一档的检查写在自己名下 —— 而**全仓没有任何机制在文档语料上执行这句话**，且**已经有一处违规**。本片把这条规则推广到全部 29 份自有 md，并给出一条**不靠例外表**的判别式，把「引用」与「主机:端口」分开。

## 1. 现状侦察（2026-09-19 对树核实）

| # | 位置 | 事实 |
| --- | --- | --- |
| 1 | `tests/unit/scripts/test_execution_plane_claims.py:65` | `_PATH_LINE = re.compile(r"`([A-Za-z0-9_./-]+):(\d+)(?:-(\d+))?`")` —— 引用的形状 |
| 2 | `tests/unit/scripts/test_execution_plane_claims.py:309` | `_rot(text, root)` —— 唯一实现「每条引用都解析得到」的地方；**只被这一份文档的用例调用** |
| 3 | `tests/unit/scripts/test_docs_anchors.py:20` | `DOC = REPO / "docs" / "execution-plane.md"` —— 标记表的检查器也写死在这一份文档上 |
| 4 | `docs/execution-plane.md:296-300` | §8 自述：「散文里的行号是第二档……这一档由 `tests/unit/scripts/test_execution_plane_claims.py` 检查……**新写的引用一律写全路径**」 |
| 5 | `docs/tool-runtime.md:190` | 违反第 4 条：`（`_wf_actions.py:101` 与 `:119`）` —— **裸基名** |
| 6 | 全仓 `anchor-table` / `anchor-absence` 块 | **只存在于 `docs/execution-plane.md`**（6 处：`:107` `:152` `:225` `:277`） |

**结论**：§8 那句话不是「机制的自述不准」，而是**声明的范围比机制大**：机制在，责任区只有一份文档。这与 #631 修掉的「§0 自称每条都被钉住、实测 51/84」是同一族，只是这一处**还没坏透**（下面第 4 项就是它坏的第一处）。

## 2. 量化附录（原始数字，可复核）

### 2.1 语料口径

**定义（形状规则，不是目录例外表）**：*所有路径分量都不以 `.` 开头的受版本控制的 `*.md`*。

```
git ls-files '*.md'                    -> 488
去掉任一分量以 . 开头的路径            ->  29   <- 语料
```

| 分组 | 数量 |
| --- | --- |
| `docs/**` | 22（含 `docs/adr` 6、`docs/acceptance` 1） |
| 仓根 `*.md` | 6（`AGENTS.md` `CLAUDE.md` `CONTEXT.md` `CONTRIBUTING.md` `README.md` `README.zh-CN.md`） |
| `frontend/README.md` | 1 |
| **合计** | **29** |

被排除的 459 份全是 `.trellis/**`（票面——历史记录，不回填）、`.claude/**`、`.cursor/**`（vendored 的 Trellis skill 文档，不是本仓的）。

### 2.2 引用分布（按语料口径实测）

| 文件 | 带路径 `路径:行号` | 裸 `:行号` |
| --- | --- | --- |
| `docs/execution-plane.md` | 97 | 17 |
| `docs/tool-runtime.md` | 2 | 2 |
| `docs/deployment.md` | 1 | 0 |
| `docs/security.md` | 1 | 0 |
| `CLAUDE.md` | 2 | 0 |
| **合计** | **103** | **19** |

全语料共 **30 个不同的 `name:digits` token**（去重后）。

### 2.3 ★ 误报面比直觉窄：模式要求「数字后紧跟反引号」

`_PATH_LINE` 的 `(\d+)` 之后**必须**是收尾反引号 ⇒ 下列写法**根本不会**被当成引用：

| 写法 | 为什么不算 | 结论 |
| --- | --- | --- |
| `` `pgvector/pgvector:pg15` `` | `:` 后是 `p`，不是数字 | 天然安全（否则它带 `/`，必被判「没有这个文件」） |
| `` `redis:7-alpine` `` | `7` 后是 `-`，不是反引号 | 天然安全 |
| `` `node:22.11` `` | `22` 后是 `.` | 天然安全 |

⇒ 需要判别式去处理的，只剩「`:数字` 恰好是结尾」这一种形状。

### 2.4 ★ 四个「解析不到」的 token，形状完全相同

`root / token` 不是文件的 token 全语料**只有 4 个**：

| token | 出处 | 树里有同名文件吗 | 判定 |
| --- | --- | --- | --- |
| `_wf_actions.py` | `docs/tool-runtime.md:190` | **有** —— `backend/api/routes/_wf_actions.py` | **真缺陷**：裸基名 |
| `host.containers.internal` | `docs/deployment.md:406` | 无 | **不是引用**（host:port） |
| `localhost` | `docs/security.md:49` | 无 | **不是引用**（host:port） |
| `postgres` | `CLAUDE.md:291` / `:354` | 无 | **不是引用**（镜像 tag） |

**「一条真缺陷」与「三条不是引用」的形状一模一样** —— 今天的 `_rot` 对四者都只报 `no such file`，所以它**区分不了**「文档写错了」与「文档在说一个端口」。

### 2.5 ★ 判别式：树里有没有这个文件

`git ls-files` 共 **2338** 个文件，其中**重名基名 94 组** —— 所以「歧义基名」分支**不是假设**，是必需品：

| 探针 token | basename 索引命中 |
| --- | --- |
| `_wf_actions.py` | `['backend/api/routes/_wf_actions.py']`（唯一） |
| `Dockerfile` | `['Dockerfile']`（唯一，且在仓根） |
| `localhost` | `[]` |
| `postgres` | `[]` |
| `host.containers.internal` | `[]` |

### 2.6 ★ 修复不是排版：修完 `:119` 才第一次被检查

`docs/tool-runtime.md:190` 今天的状态是：`_wf_actions.py` 归属失败 ⇒ 紧随其后的裸 `:119` 的 `last` 指向一个**解析不到的路径** ⇒ `_size` 返回 `None` ⇒ **静默跳过**。修成全路径之后，`:119` 才进入范围检查。

已核对内容**本来就对**（`backend/api/routes/_wf_actions.py` 371 行）：

```
101:             pred_task = ripple.submit_and_wait(
119:             pmf_task = ripple.submit_and_wait(
```

⇒ 本片**只改引用形式，不改任何主张值**。

## 3. 要重写的定性

> 票面（以及 §8 那句话）把这件事写成「**文档里的行号会腐烂**」的一条纪律。按上面量出来的东西，缺的不是纪律，是**两个东西**：
>
> 1. **规则的作用域。** 「每条引用都解析得到」实现得挺好（`_rot` 五种失败形态、区间两端都查、同行按位置归属），但它的**责任区**是一份文档。§8 那句「新写的引用一律写全路径」是对**整个文档语料**的规范，而执行它的机制只覆盖 1/29。
> 2. **判别式。** 推广的时候会立刻撞上四条同形 token —— 而其中三条**根本不是引用**。一份带例外表（`if token in {"localhost", "postgres"}`）的实现会同时做错两件事：漏掉没登记过的新端口，以及把「不是引用」写成本仓的一条知识。真判别式必须是**可推导**的：**这个 token 在树里是不是一个文件的名字（或者一类文件的类型）**。
>
> ⇒ 所以本片的产出不是「多扫 28 份文档」，是**一条带判别式的规则**，加上一句 §8 的自述修正：责任区从「本文件」变成「语料」。

## 4. 判别式（要写进代码的那个版本）

一个带反引号的 `X:N` 被当成**引用**，当且仅当满足下列任一条：

| # | 条件 | 它买到什么 | 语料里的活实例 |
| --- | --- | --- | --- |
| a | `X` 含 `/` | 全路径的错字/漂移会红 | 103 处里的 100 处 |
| b | `root / X` 是文件 | 无斜杠但真实存在的路径（仓根文件） | `` `Dockerfile:81` `` |
| c | 树里存在文件的名字就叫 `X` | **裸基名**违规会被抓到并给出正确全路径 | `` `_wf_actions.py:101` `` |
| d | `X` 的最后一个后缀是**字母开头**的，且树的文件名里出现过该后缀 | **裸基名的错字**（名字本身都不存在）也红 | 语料里没有，夹具里有 |

不满足任一条 ⇒ **不是引用**，一律跳过（今天能正确跳过 `localhost:8000` / `host.containers.internal:9223` / `postgres:15`）。

**为什么 (d) 不是扩展名白名单**：后缀集合是从**树本身**推的（`Path(name).suffix` 的并集），不是手写的。所以它随仓增长而增长，也不会漏掉 `Dockerfile:81`（那条走 (b)）。**要求后缀字母开头**是一条形状规则而不是列表：`127.0.0.1:8000` 的 `.1` 因此天然出局。

**已知残差（写进文档，不假装没有）**：一个既不含 `/`、名字不在树里、后缀也不在树里出现的 token（例如在别的地方写的 `some_other_repo.py:5`）会被跳过。这是**故意**的：本仓的规范是「引用一律写全路径」，所以这条残差只覆盖**本来就违反规范**的文字。(a) 已经把「全路径写错」全部收进来了。

## 5. 切片表

**一片（S1）**，独立 PR。没有拆分的理由：规则搬一次、扫一次、修一处、改一句自述，四件事共用同一份语料快照，拆开只会让中间态需要两份实现。

| 文件 | 动作 |
| --- | --- |
| `tests/unit/scripts/docs_citation_rule.py` | **新增**（非 `test_` 前缀 ⇒ 不被收集）。引用规则的唯一实现：形状、判别式、语料枚举、`_rot` |
| `tests/unit/scripts/test_docs_citations.py` | **新增**。全语料扫描 + 语料口径断言 + 4 条夹具（阳性对照） |
| `tests/unit/scripts/test_execution_plane_claims.py` | 删掉本地的重复实现，改为从上面那份模块 import（**单一所有者**）；那份文档的覆盖率主张（114/60/17）不动 |
| `docs/tool-runtime.md:190` | 裸基名 → 全路径（**唯一的内容改动**，只改形式） |
| `docs/execution-plane.md` §8 | 自述修正：责任区、判别式的四条、残差 |

## 6. 红线

- **零 `backend/**` 改动**（`mypy backend` 的文件数必须不变）。
- 不改 `docs/**` 的**任何主张值**（只改引用形式与机制自述）。
- **不碰 §7 的两问**（守卫答什么 / 回调要不要）—— 那是**下一入口**，本片只把它的代价钉着。
- 不顺手加第五件事。
- 不把 `.trellis/**` 纳入语料（票面是历史记录）。

## 7. 验收

| # | 判据 |
| --- | --- |
| 1 | 全语料扫描在**未改动的树**上只报 `docs/tool-runtime.md:190` 一处（修之前），修之后为 0 |
| 2 | 夹具证明判别式的**两个方向**都存在：`` `_wf_actions.py:101` `` 报「裸基名 + 正确全路径」；`` `localhost:8000` `` / `` `host.containers.internal:9223` `` / `` `postgres:15` `` **一处都不报** |
| 3 | 夹具证明 (d) 承重：`` `_wf_actins.py:101` ``（后缀在树里、名字不在）必须红，而 `` `localhost:8000` `` 必须绿 —— **两者的差别只有后缀** |
| 4 | 语料枚举有下界断言（≥29）与「`docs/` 在、`.trellis/` 不在」的方向断言 —— 防扫描器悄悄收窄 |
| 5 | 规则只有一份实现（`test_execution_plane_claims.py` 不再有 `_PATH_LINE` 的字面定义） |
| 6 | 四道门禁全绿，且 `passed` 增量 == 新用例数、`ruff format --check` 文件数增量 == 新文件数 |
| 7 | 突变自检：每条突变都有具名见证者，零 TOO WEAK / 零 UNWITNESSED |

## 8. 待决裁定（本片不做）

1. **守卫答什么**（`process_has_active_task` 在 ripple-retry 路径上应当回答什么，带着 1800 秒窗口）。
2. **回调要不要**（`_on_task_done` 会把仍 `running` 的工作流标成 `stale`，没有守卫的路径不能照抄）。

两条都来自 `docs/execution-plane.md:216`，且**有顺序**。本片与此无关，不顺手回答。

## 9. 执行记录（S1，2026-09-19）

**落地形状**（与 §5 的切片表一一对应）：

| 计划 | 落地 |
| --- | --- |
| 规则搬到一个模块 | 新增 `tests/unit/scripts/docs_citation_rule.py`（246 行）：形状、判别式、语料枚举、`_rot` |
| 新增语料判据文件 | 新增 `tests/unit/scripts/test_docs_citations.py`（313 行）：**9 条用例** = 2 条语料/扫描 + 2 条搬来的规则夹具 + 5 条判别式夹具 |
| 判据文件改为消费共享规则 | `test_execution_plane_claims.py` 782 → 617 行：`from docs_citation_rule import _PATH_LINE, _cited`；删掉本地重复实现与 3 条用例（1 条被语料扫描取代、2 条规则夹具搬到规则旁边） |
| 修那处违规 | `docs/tool-runtime.md:190` 裸基名 → 全路径 |
| 自述修正 | `docs/execution-plane.md` 321 → 334 行，§8 的散文档自述 |

★ **计数换了语义而数字没动**：`_cited` 现在只数**被判为引用**的 token，而 `docs/execution-plane.md`
的三个自覆盖数（114 / 60 / 17）经复核**一字不变** —— 它那 97 处带路径的引用全部解析得到。
这是**复核出来的**，不是推出来的（本片最该防的就是「换了语义，数字看着差不多就放过」）。

### 9.1 跑起来才暴露的（原以为 vs 实测）

| # | 原以为 | 实测 |
| --- | --- | --- |
| 1 | 5 份文档在引用行号（`deployment` / `security` / `CLAUDE.md` / `exec-plane` / `tool-runtime`） | 判别之后只有 **2** 份 —— 前三份**一个引用都没有**。第一版下界断言（≥5）就是照那个原始数字写的，跑起来当场判红 ⇒ **照原始计数写的下界，会把误报按构造保留下来** |
| 2 | `_how` 的四条分支「先问树」 | 少了「**有斜杠即路径**」这一支：`backend/api/old/_runner.py:2`（一条漂移的全路径）被报成「裸基名，你是想说 `backend/api/routes/_runner.py` 吧」。夹具（两条路径同处一个合成树、一条真一条假）当场红 |
| 3 | 修 `tool-runtime.md:190` 只是把引用写全 | **语义也变了**：修完之后紧跟它的裸 `:119` 才第一次被纳入范围检查（此前归属路径解析不到 ⇒ `_size` 返回 `None` ⇒ 静默跳过） |
| 4 | 语料枚举用 `git ls-files` 才权威 | 走树 **0.02 s**、891 个文件，与 `git ls-files`（2338 个，含点目录）在语料上**完全一致** ⇒ 用文件系统走树，不引入对 git 的依赖，也不受「未跟踪文件」影响 |

### 9.2 量化（2026-09-19 对树实测，权威口径）

| 量 | 值 |
| --- | --- |
| 语料（自有 md，路径分量无点开头） | **29**（`docs/` 22 + 仓根 6 + `frontend/` 1） |
| 原始 backticked `name:digits` token | **122** |
| 判别为引用 | **118**（剔掉 4 个：`postgres:15` ×2、`localhost:8000`、`host.containers.internal:9223`） |
| 有引用的文档 | **2** |
| 树里文件 / 重名基名 | **891** / **94** |

### 9.3 门禁

| 门禁 | 结果 |
| --- | --- |
| `pytest tests/ -q` | **3658 passed / 3 skipped**（上一片 3652 ⇒ **+6** = 9 新 − 3 搬走） |
| `ruff check .` | All checks passed |
| `ruff format --check .` | **548 files**（+2 = 新文件数） |
| `mypy backend --python-version 3.12` | **217 source files**（不变 ⇒ 生产代码零改动） |
| Context Compiler Baseline | OK（drift within threshold） |
| Tool Runtime Gate | OK |
| 突变自检 | **18/18 杀死**，零存活 / 零 TOO WEAK / 零 UNWITNESSED / 零 ERROR，`restore=OK` |

突变里最值钱的三条：

- **M16**：把 `docs/tool-runtime.md:190` 的裸基名**改回来** ⇒ 语料扫描红。证明扫描器读的是**真语料**，
  而不是它自己造出来的样本。
- **M17**：往 `CLAUDE.md` 塞一条假的 `backend/nope/nowhere.py:3` ⇒ 语料扫描红。证明语料**不止 `docs/`**。
- **M15**：把 `_PATH_LINE` 收窄成只认 `backend/` ⇒ `docs/execution-plane.md` 的 `114` 主张红。
  证明 exec-plane 的判据读的**就是**这份共享规则 —— **单一所有者不是口号**。

### 9.4 登记未修（本片不假装它们不存在）

1. **残差**：既无斜杠、名字不在树里、后缀也不在树里出现的 token 会被跳过（例如在别处写的
   `some_other_repo.py:5`）。这是**故意**的 —— 本仓规范是引用一律写全路径，所以这条残差只覆盖
   **本来就违反**那段规范的文字；带斜杠的错字一条都跑不掉。
2. **裸 `:N` 的归属仍是节内推断**（同一节内最近一次出现的完整路径）。换文件之后它会静默指错 ——
   与上一版相同，未变。
3. **只有 `docs/execution-plane.md` 有标记表**（`anchor-table` / `anchor-absence`）。其余 28 份
   没有，本片**不建** —— 建表要求逐条钉 token，那是另一件事。

### 9.5 下一入口

仍是 `docs/execution-plane.md:216` 的那两问，且**有顺序**：**守卫答什么**（`process_has_active_task`
在 ripple-retry 路径上应当回答什么），然后**回调要不要**（`_on_task_done` 会把仍 `running` 的
工作流标成 `stale`）。都要带着 **1800 秒**窗口做。本片与此无关，未动。
