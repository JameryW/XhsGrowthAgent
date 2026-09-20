# 09-20-heartbeat-tolerates-a-hiccup — 拥有者的容忍预算

> 入口：`09-19-renew-loss-has-a-kind`（PR #638）§7 第 1 条
> ——「`renew` 的容忍预算（裁定 D）。方向的**对象**已经有了：`UNKNOWN` 与 `LOST` 是两个值。」

## 0. 这一片要回答什么

`renew` 的两种非答案现在分得开（#638），但**拥有者对一个「问不到」零容忍**：循环在第一个
非 `RENEWED` 上就 `return`，而栅栏据此 `owner.cancel()` —— 同步跑的 run 被 abort 的是
**调用者正在等的那个 HTTP 响应**（§2.3 的表）。

所以本片要回答的是一句**此前没有对象可谈**的话：**一次存储抖动该不该杀掉一个健康的运行？**

两件事必须先量清，否则这句话只能靠感觉答：

1. **安全边界在哪里**——「还能继续写」这件事由**行**决定，不是由拥有者的信念决定。
   `_ACQUIRE_SQL` 的 `WHERE` 把三个条件或在一起，其中与时间有关的那一个（`:290-291`）说：
   **行不老就抢不走**。所以问题等价于「拥有者最晚可以在自己的行变老之前多久停手」。
2. **停手这个动作本身要花时间**——失败的 `renew` 要先跑完、异常要先冒上来，才会被读成
   一个计数。所以余量必须以**整个 interval** 为单位留，不能以「恰好到期」为界。

## 1. 现状侦察表（每条都对树核过；行号是**动代码前**的值）

| # | 事实 | 位置 |
| --- | --- | --- |
| P1 | 心跳循环在第一个非 `RENEWED` 上就 `return`，**零容忍**、不计数 | `execution_leases.py:632-643` |
| P2 | 预算常量：`HEARTBEAT_MISSES_BEFORE_EXPIRY = 3`；`LEASE_TTL_SECONDS = 90.0`；`HEARTBEAT_INTERVAL_SECONDS = TTL / M`（**导出的是同一个决定**） | `:83` / `:84` / `:85` |
| P3 | 扫描侧的判据是「行老了」：`is_stale` = `heartbeat_at + ttl <= now`（内存侧 Python，SQL 侧 `now()`） | `:169` / `_EXPIRE_SQL:313` |
| P4 | ★ **可被抢的唯一时间条件**：`_ACQUIRE_SQL` 的 `WHERE` **三条件或在一起** —— `state <> 'held'` 或 `owner_id = EXCLUDED.owner_id` 或 **`heartbeat_at + ttl <= now()`** ⇒ **行不老就抢不走**（这是本片安全性的全部依据） | `:276-293` |
| P5 | `renew_outcome` 的 docstring **已经点名**把这条留在这里：「the owner itself currently tolerates zero. Widening that is a separate ruling; see `docs/execution-plane.md` §2」 | `:455-461` |
| P6 | `RenewOutcome` 的 docstring 同样点名：「makes a future "be more tolerant of a hiccup" edit a two-branch edit instead of an invisible one」 | `:136-140` |
| P7 | 判据 `_heartbeat_stops_on_every_non_answer` 钉的是「含 `RENEWED` 的比较必须是 `IsNot`」⇒ **改成计数器形状后这条主张会红**（新形状里 `RENEWED` 的比较是 `Is`） | judge `:707-744` / 主张 `:817-819` |
| P8 | 判据 `_misses_the_scanner_tolerates` = `HEARTBEAT_MISSES_BEFORE_EXPIRY - 1` = **2**（扫描侧） | judge `:697-704` |
| P9 | 文档侧有 **4 处**要跟着改：§2 不保证 4 的「拥有者自己容忍 **0** 次」、§7.1 第 1 条（整段关闭）、锚点表里那一行、claim 表里 `misses_the_scanner_tolerates` 的备注 | `docs/execution-plane.md:54-55` / `:274` / `:297` / `:361-363` |
| P10 | 只有 `tests/unit/db/test_renew_outcome.py` 声称「立刻停」（模块 docstring `:21` + 那条参数化用例 `:230`）—— 它是**唯一的**行为见证 | 同左 |
| P11 | 三个常量在 `__all__` 里（`:714-737`），新增常量要跟着进 | 同左 |
| P12 | 内存后端**不会**产生 `UNKNOWN`（`_renew_in_memory` 只有 `{RENEWED, LOST}`）⇒ 本片的改动**只在 PG 形态下可观测** | `:483` / 判据 `test_renew_outcome.py:165` |

## 2. 量化附录（推导与探针，可复核）

### 2.1 安全边界：拥有者最晚在哪里停手

记号：`M = HEARTBEAT_MISSES_BEFORE_EXPIRY = 3`、`I = HEARTBEAT_INTERVAL_SECONDS = TTL / M`。

设最后一次**成功**续租在 `t₀`（`heartbeat_at = t₀`），此后每次尝试都失败。第 j 次尝试发生在
`t₀ + jI`，行在 `t₀ + TTL = t₀ + MI` **变老**（此时才可能被抢，P4）。

若容忍 `n` 次失败（即在第 `n+1` 次失败上停手），**停手动作发生在 `t₀ + (n+1)I + δ`**，
其中 `δ` 是「一次失败被检测到」所花的时间（renew 要先跑完、异常要先冒上来）。

要求：`(n+1)I + δ ≤ MI`，即 `n ≤ M - 1 - δ/I`。

`δ` 不是零，也不该被假设成零 —— 一个**慢**到跨过整个 interval 的 renew 本身就是要防的东西
（`:77-82` 那段注释用的是同一个推理，只是它管的是扫描侧）。以**一个 interval** 作余量：

```
n_max = M - 2 = 1
```

| 侧 | 单位 | 预算 | 出处 |
| --- | --- | --- | --- |
| 扫描（判过期） | miss 数 | `M - 1` = **2** | `:83` 的常量 + `is_stale` |
| 拥有者（自己停） | interval 数 | `M - 2` = **1** | 本片新增，`tolerated = M - 2` |
| 余量（拥有者停手 → 行变老） | interval 数 | `M - 1 - tolerated` = **1** | 推导 |

★ **两把尺子是同一把（都以 `M` 为单位），量出来的数不一样（2 vs 1）** —— 因为量的是两个
不同的东西：扫描侧量「多少次沉默算死」，拥有侧量「多少次失败之后还赶得及停」。**这个不对称是
推导出来的，不是笔误**；把两者写成同一个数（`tol`= 2）会让拥有者恰好停在行变老的那一刻，
也就是**停下来这个动作落在可被抢之后**。

### 2.2 为什么不是「干脆继续跑」

因为 `UNKNOWN` 说的是**我们问不到**，不是**行还在**。拥有者没有能力把「问不到」变成证据；
它能做的只是**用行本身作证据**：只要不越过 `heartbeat_at + ttl`，行就抢不走，写就是安全的。
容忍预算正是「我愿意在没有新证据的情况下跑多久」的显式上界 —— 把它写成从 `M` 推导出来的
一个数，比写成 0（过保守）或写成 `M-1`（越界）都更接近事实。

### 2.3 容忍的代价与收益（两侧都量）

| | 今天（容忍 0） | 本片（容忍 `M-2`=1） |
| --- | --- | --- |
| 一次抖动 | 停手 → 栅栏 `owner.cancel()` → **调用者正在等的 HTTP 响应被 abort**（12 个执行点里 **10 处是内联 `await`**） | 继续跑，记一条「容忍第 1 次」的日志 |
| 两次连续失败 | 同上 | 停手（与今天同样的路径） |
| 写者在行变老之后还在写 | 不会（停得远） | **不会**（余量 1 个 interval） |

### 2.4 可达性（决定本片的可观测性）

`UNKNOWN` 只有两种来源：空 `thread_id`（调用者 bug）与**存储抛异常**（`renew_outcome` 的
`except`）。后者要求 `is_pool_ready()` 为真 —— 没有 PG 时走内存后端，而内存后端**不产生
`UNKNOWN`**（P12）。⇒ **无 PG / 单进程部署下本片不可观测**（同 #636 的那条登记）。

## 3. 裁定

### 裁定 A：采纳「有限容忍」，只给 `UNKNOWN`，预算 = `M - 2`（**采纳**）

- `LOST` → **零预算**，立即停：它是**关于行的事实**，不是沉默。
- `UNKNOWN` → 容忍，**连续的**计数；成功一次即清零（因为成功的 `renew` 会把
  `heartbeat_at` 前移，也就是把「行变老」的时钟重置 —— 计数必须是连续的才与时钟对齐）。
- 预算**从 `M` 推导**，不写字面量，理由与 `:77-82` 那段注释相同（手挑的一对数字会在
  一侧被改动的那一刻漂移）。

### 裁定 B：容忍的那一次要**单独记一条日志**（**采纳**）

`09-19` 那片把「取证方式」定成「先证明『一次抖动』在日志里可识别」。容忍之后，「抖动了但
扛住了」与「什么都没发生」在日志里**同形** —— 那等于把上片刚建立的可识别性又丢掉。
所以容忍时记一条与「停手」不同的消息，且带上计数与预算。

### 裁定 C：把「预算 ≥ 1」钉成断言（**采纳**）

`tolerated = M - 2` 在 `M = 3` 时为 1。若将来有人把 `M` 调成 2，容忍预算变成 **0** ——
特性**静默消失**而没有任何测试会红。所以断言 `tolerated >= 1`（等价于 `M >= 3`），
让那次改动必须显式面对本片（与既有 `assert M >= 2` 同族的做法）。

### 裁定 D：`release` 的 4 个出口、具名锚点规则（**本片不动**，见 §6）

## 4. 切片表

| 切片 | 内容 | 判据 |
| --- | --- | --- |
| S1 | 常量 `HEARTBEAT_TRANSIENT_FAILURES_TOLERATED = HEARTBEAT_MISSES_BEFORE_EXPIRY - 2` + `__all__`；把 `renew_outcome` / `RenewOutcome` docstring 里那两段「currently tolerates zero」改对 | `tests/unit/db/test_execution_leases.py`（派生关系 + `>= 1`） |
| S2 | 循环改成**三行表**：`LOST` 立即停 / `RENEWED` 清零 / `UNKNOWN` 计数、超预算才停；容忍时单独记日志 | 扩 `tests/unit/db/test_renew_outcome.py`（LOST 零预算 · 容忍 N 次后停 · 成功清零 · 容忍可被日志看见） |
| S3 | 判据重述（`heartbeat_stops_on_every_non_answer` → 读「`LOST` 的决定在预算检查**之前**」）+ 新 claim `transient_failures_the_owner_tolerates`；文档 §2 / §7.1 / 两张表 | `tests/unit/scripts/test_execution_plane_claims.py` |

## 5. 红线 / 不做 / 验收

1. **不得越过安全边界**：`tolerated + 1 + 1 <= M`（停手至少比行变老早一整个 interval）。
2. **`LOST` 零预算**，不受计数影响 —— 它必须在预算检查**之前**被决定。
3. **计数必须是连续的**；一次成功即清零（否则计数与 `heartbeat_at` 的时钟脱钩）。
4. 不改 `_ACQUIRE_SQL`、不改扫描侧（`is_stale` / `expire_scan`）、不给 `release` 加预算。
5. 验收：四道门禁 + 全量 `pytest` 全绿，且**既有 6 条 `renew` 断言一字不改**；突变自检全杀。

## 6. 登记未修（带理由，本片不动）

1. **`release` 的 4 个 `False` 出口** —— 同形，后果轻（`end_lease` 不据此做决定），**未量**。
2. **具名锚点规则** —— `09-19` 片 §2.4 有完整的量（19/8/6）与量法；自有风险是
   `execution_leases.py:248` 那种「引用整条语句」会被误判。
3. **本片在无 PG 形态下不可观测**（§2.4）—— 不是缺陷，是可达性事实。

## 7. 留给下一任务的输入

1. **`release` 的 4 个出口**（§6 第 1 条）：`release` 的 `False` 现在与 `renew` 拆之前**同形**
   （空 id / 不是我们的 / `except` / `released` 假），而它的消费者是 `end_lease`。
2. **具名锚点规则**（§6 第 2 条）—— 量已经在了，只差规则。
3. **P2a 三处 `run_publish` 直调语义各不相同**（更早的登记，仍未动）。

## 8. 执行记录（2026-09-20）

| 项 | 实测 |
| --- | --- |
| 分支 | `feat/heartbeat-tolerates-a-hiccup` |
| diffstat | **5 文件，+320 −106**：`execution_leases.py` +61 −23 · `test_renew_outcome.py` +104 −8 · `test_execution_plane_claims.py` +111 −48 · `test_execution_leases.py` +20 −0 · `execution-plane.md` +24 −27 |
| `ruff check .` | All checks passed |
| `ruff format --check .` | **551** files（与 #638 相同 —— 本片不新增 `.py` 文件） |
| `mypy backend --python-version 3.12` | Success: no issues found in **217** source files |
| `tool_runtime_gate.py` | P1c-S5 tool runtime: OK |
| 全量 `pytest` | **3703 passed / 3 skipped**（#638 是 3699 ⇒ **+4**） |
| 突变自检 | **17/17**，`baseline=clean  restore=YES` |

**+4 逐条对上**：`test_a_lost_row_stops_without_consulting_the_budget` · `test_the_owner_spends_the_budget_and_then_stops` · `test_a_renewal_resets_the_count`（以上 `test_renew_outcome.py`）· `test_the_owner_budget_is_derived_and_leaves_a_whole_interval`（`TestLeaseBudget`）。本片不新增测试文件 ⇒ ruff 文件数不变，是同一件事的另一个面。

**既有断言零改动**（红线 5）：`test_execution_leases.py` 是 **+20 −0**（纯追加）；`test_renew_outcome.py` 的 8 行删除**逐行都在模块 docstring 里**（那段「两个非答案都停机」现在是假的 —— `UNKNOWN` 被容忍一次，所以必须重述）。9 条既有用例的断言体一字未动。

### 突变自检：17 条，全杀

harness = `C:/Users/jamer/aiworks/_mut_heartbeat_budget.py`（**保留**，本节引用它 —— 保留清单按「谁引用它」推导，不按「谁刚建的」，见 #637 那次的教训）。

三条最值钱的：

1. **M05「预算变成它恰好等于的那个字面量」** —— `HEARTBEAT_MISSES_BEFORE_EXPIRY - 2` → `1`。**每一个值断言都还是绿的**（1 就是 1），文档的两张表也还是绿的。只有「从推导重算 + 断形状」那一半能杀它，而那一半的存在只能由**同批进来**的阳性对照证明（夹具 `M = 5` ⇒ 必须答 3）。这是 #636/#638 那条空转形态的第三次现身：**值等于任何常数的判据都自带不了对照。**
2. **M07「协调突变」** —— 把推导改成 `- 1` **并且**把文档那行一起改成 `2`。claim 表当场自洽（`2 == 2`），只剩 `test_the_owner_budget_is_derived_and_leaves_a_whole_interval` 站着。**单侧突变隔离不出它** —— 两处必须同时满足旧读数，这条判据才成为唯一见证者（#632 那条的形状）。
3. **M09「顺序反转但行为不变」** —— 把预算检查提到循环开头（`misses = 0` ⇒ 首次 `0 > 1` 为假，运行期不抛异常）。**每一条行为用例都还是绿的**：在它们观测计数的那一刻，两种读法的读数一致。只有「读顺序」的判据看得见它 —— 这正是本片把裁定从**运算符**搬进**顺序**的代价与收益。

其余 14 条按「每个性质一条」铺：文档三张表的每一行各一（M01–M04，含 §8 那张**关于自己**的自述表）· 扫描侧与拥有者不同数（M06）· 两个数各自漂移（M08）· `LOST` 早退被删（M10）· `LOST` 报成另一个非答案（M11）· 计数改成累计（M12）· 边界 `>` → `>=`（M13）· 容忍那一次不被日志看见（M14）· 两条新扫描各自被硬编码成它公布的值 / 真（M15 / M16）· 顺序判据的比较方向读反（M17）。

### 一处本片自己踩到的坑（写下来免得下一片再踩）

**文本模式读文件会把 CRLF 折成 LF。** 补丁脚本里 `open(PATH, encoding="utf-8")` 一读，多行锚点（用 `\r\n` 拼的）**永远匹配不到** —— 而且写回时会把**整个文件静默改成 LF**。修法：一律 `read_bytes()` → 解码 → 在 LF 上匹配与插入 → 写回时还原文件自己的行尾 → 断言**字节**（`crlf == lines`、`lone_lf == 0`）。本片这条在**写盘前的预检**就被抓到（`anchor found 0 times`），零损失。

与之配对的一条：**§8 那张自述表里的三个数必须在改动全部落盘之后重新量**，不能复用中途值 —— 上一片（#635）就留过一次中途值当"下界"。本片三个数（`134` / `71` / `18`）是补丁收尾后由判据自己报出来的。
