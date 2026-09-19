# prd：两种不同的「不」——让租约的拒绝带上原因

> 票 `09-19-lease-refusal-has-a-reason` · 分支 `feat/lease-refusal-has-a-reason` · 基线 `47315fa8`
> 前置：`docs/execution-plane.md` §2（非保证）/§5（接管的安全边界）/§7（#635 留下的那一格）
> 交付：PR **#（回填）**

## 0. 这一片要回答什么

§7「留给下一任务的输入」第 1 条：

> **把两种拒绝分开。** `acquire` 现在对「活着的外部持有者」与「存储答不上来」答同一个 `False`
> （`backend/db/execution_leases.py:206` 的 `WHERE` 子句把它们合并了），而裁定 2 只覆盖后者。
> 分开之前，「扫描先到」这一格没有闸门，窗口是一个 `takeover_interval_seconds`（默认 60s）量级。

本条有三个可检验的东西，逐个量：

1. **合并到底发生在哪几处**（§2）：`acquire` 有 **3** 个 `False` 出口，而**内存后端只有 1 个** ——
   ⇒ **两个后端对「拒绝」的语义今天就已经不一致**，而模块 §0 第一条性质说的就是不许「一个状态两个答案」。
2. **「扫描先到」这一格是不是真的有闸门缺口**（§3）：在**同进程**里没有缺口（#634 的守卫 + 同
   `owner_id` 必然授予），缺口只在**≥2 个持有者同时活着**时出现 —— 滚动发布就是。
3. **同一个形状在 `renew` 上第二次出现，而它的安全方向是反的**（§4）：`renew` 的 `False` 有 **4** 个出口，
   其中 `except` 那一个的含义是「问不到」，而 `_fence_on_lost_lease` 把它当作「确知丢了」——
   **一次数据库抖动会 cancel 掉一个健康的运行**。这条本片**登记不修**，但要把它的方向写下来。

## 1. 现状侦察表（每条都对树核过；行号是**动代码前**的值）

| # | 位置 | 事实 |
| --- | --- | --- |
| 1 | `backend/db/execution_leases.py:312` | `acquire(...) -> bool`：**唯一**对外的授予接口 |
| 2 | `backend/db/execution_leases.py:320` | `False` 出口 ①：`thread_id` 为空（调用方 bug） |
| 3 | `backend/db/execution_leases.py:340` | `False` 出口 ②：`except Exception` —— **存储答不上来** |
| 4 | `backend/db/execution_leases.py:343` | `False` 出口 ③：`granted` 为假 —— **活着的外部持有者** |
| 5 | `backend/db/execution_leases.py:206` | `_ACQUIRE_SQL` 的 `WHERE`：三个条件或在一起，拒绝时答不出是哪一个 |
| 6 | `backend/db/execution_leases.py:284` | `_acquire_in_memory`：**只有 1 个 `False`**（`:299`，外部持有者）—— 内存后端无法「答不上来」 |
| 7 | `backend/api/routes/_takeover.py:139` | `acquire` 消费点 ①，`:136-138` 的注释**明文写下**这个合并 |
| 8 | `backend/db/execution_leases.py:511` | `acquire` 消费点 ②，在 `start_lease` 里，只留 `heartbeat`，**丢掉原因** |
| 9 | `backend/api/routes/_runner.py:414` | `start_lease` 的唯一生产调用点，在 `_execution_lease` 里 |
| 10 | `backend/api/routes/_runner.py:392` | `_execution_lease` 产出 `asyncio.Event`（只有「丢没丢」） |
| 11 | `backend/db/execution_leases.py:346` | `renew(...) -> bool`：**4** 个 `False` 出口（`:355` 空 id · `:364` 不是我们的 · `:375` except · `:376` `renewed` 假） |
| 12 | `backend/db/execution_leases.py:488` | `renew` 的**唯一**调用点，在 `_heartbeat_until_cancelled` 里 |
| 13 | `backend/api/routes/_runner.py:376` | `_fence_on_lost_lease`：心跳自己结束 ⇒ 认定丢租约 ⇒ `owner.cancel()` |
| 14 | `backend/api/routes/_wf_actions.py:70` | ripple-retry 的进程内守卫（#634）⇒ 同进程那一侧已有闸门 |
| 15 | `backend/api/routes/_wf_runtime.py:331` | `_start_resume_task` 读**登记表**（不是租约）来决定取消靶子 |

## 2. 量化附录（探针原文与 AST 取证，可复核）

### 2.1 每个函数的「否」出口数（AST：`Return` 常量 / `Name` / `Compare`）

```
acquire: 3 -> [(343, 'Name(granted)'), (320, 'False'), (340, 'False')]
renew:   4 -> [(376, 'Name(renewed)'), (355, 'False'), (375, 'False'), (364, 'False')]
release: 4 -> [(402, 'Name(released)'), (386, 'False'), (401, 'False'), (391, 'False')]
```

`except` 块返回裸 `False` 的函数：`acquire` · `renew` · `release`（`get_lease` 返回 `None`）。

### 2.2 ★★ 两个后端今天就答得不一样

`_acquire_in_memory` 的 `False` 出口**只有 1 个**（`:299`，且条件是 `owner_id != _instance_id and not is_stale`）。
内存后端**没有「答不上来」这一档**（它不会失败），而 SQL 后端把 `except` 折进同一个 `False`。
⇒ **同一个问题在两个后端上的答案集合不同** —— 这正是模块 §0 第一条性质要消灭的形状
（「一行对一个读者活着、对另一个读者死了，就是这个任务要删掉的『一个状态两个答案』」）。

### 2.3 ★★ 「扫描先到」这一格：同进程内没有缺口

探针（真模块、内存后端）：

```
P1 same instance re-acquires       -> first True, second True
P2 a fresh foreign owner holds it  -> acquire 答 False，type 是 bool，说不出原因
P3 empty thread_id                 -> 同一个 False
P4 renew on a foreign-owned row    -> renew False，而 thread_is_held True
```

- **P1 是关键**：`_ACQUIRE_SQL` 的 `WHERE` 含 `execution_leases.owner_id = EXCLUDED.owner_id`
  ⇒ **本进程永远能重新授予自己**。所以「本进程的扫描先接管、本进程的修复后到」**根本不会被拒绝**，
  租约在这一格里什么也没挡；挡它的是 `process_has_active_task`（#634，`:70`），因为
  `_start_resume_task` 会写登记表（`:331`）。
- ⇒ **缺口只在「≥2 个持有者同时活着」时出现**：滚动发布（旧容器还在跑、新容器收到请求）、
  或多个实例。那时 `owner_id` 不同 ⇒ `acquire` 拒绝 ⇒ **修复路径照跑** ⇒ 同一 checkpoint 两个写者。
- 生产镜像 `Dockerfile:81` **没有 `--workers`** ⇒ **单进程**，所以**本机部署形态下这条改动不可观测**。
  这不削弱它：滚动发布与多副本都是正常形态，而租约存在的理由正是「跨进程可见」。

### 2.4 P4 那句话本身是证据

同一个存储、同一瞬间：`renew('T')` 答 `False`、`thread_is_held('T')` 答 `True`。
两个问题不同（「还是我的吗」 vs 「有人在跑吗」），所以这不是矛盾 —— 但它证明一件事：
**`renew` 的 `False` 说的是「不是你的」，不是「没人要」**。把「不是你的」与「问不到」合成一个 `False` 之后，
`_fence_on_lost_lease`（`:376`）对两者都 `owner.cancel()`。

## 3. ★★★ 裁定

### 裁定 A：`acquire` 的拒绝拆成三值（**采纳**）

`AcquireOutcome(StrEnum)`：`GRANTED` / `HELD_BY_LIVE_OWNER` / `UNKNOWN`。

- `HELD_BY_LIVE_OWNER` 的条件可以写死：**行存在、`state == held`、`owner_id != 本实例`、且未过期**
  —— 与 `_acquire_in_memory:293-299` 的合取逐字对应（那边**已经**是这个判据，SQL 侧只是没说出来）。
- 空 `thread_id` 归入 `UNKNOWN`：调用方没给出可回答的问题，与「存储答不上来」一样是「我们不知道」。
  **它保持今天的行为**（照跑），并在 §6 登记。
- `acquire() -> bool` 保留为投影（`is GRANTED`）⇒ 既有 60+ 条 `acquire` 断言**一字不改**。

### 裁定 B：`start_lease` 把原因一起交出来（**采纳**）

返回 `LeaseHold(outcome, heartbeat)` 一个 frozen dataclass。理由：**只有一处实现**这条性质
（#635 建立的）不允许再加一个「带原因的取租约」函数；把原因丢掉再让调用方重新问一次，
既是第二次往返，也引入新的竞态。「投影」与「第二实现」的区别在于有没有第二个决定，
这里没有。

代价：`start_lease` 的 4 条既有断言要改（见 §5），其中一条会**变强**（从 `is None` 变成断言是哪种拒绝）。

### 裁定 C：两条修复路径对 `HELD_BY_LIVE_OWNER` **拒绝**，统一入口不变（**采纳**）

- 两条修复路径：`HELD_BY_LIVE_OWNER` ⇒ **不写 checkpoint、不起执行**，改为写一条 `workflow_events`
  + 日志（渠道与 `_takeover._record` 同源：遥测不是状态）。
- **统一入口 `_run_graph_and_persist` 保持今天的行为**（拒绝也照跑）：它的拒绝语义由
  `/recover`（`_wf_application.py:1077` 只放行 error/stale）等端点拥有，不在本片射程内。
  ⇒ 因此 `_execution_lease` **产出判定结果，由调用方各自裁定**，而不是自己决定。
- **行为变化的边界（可量）**：`GRANTED` 与 `UNKNOWN` 两档行为**完全不变**；
  `HELD_BY_LIVE_OWNER` 在**单进程**下不可达（§2.3 的 P1）⇒ **本机部署形态下零可观测变化**。
  变化的只有「≥2 个持有者同时活着」这一格，而那一格今天是双写。

### 裁定 D：`renew` 的同形合并 **登记不修**（**本片不动**）

方向是**反的**：`acquire` 侧「问不到要照跑」（裁定 2），`renew` 侧「问不到要停手」
（红线 4：同一 checkpoint 不许两个写者）。今天两边都取最保守的一侧，所以**行为上没错**，
错的是**这两件事被写成了一个 `False`** ⇒ 将来任何一次「让 renew 宽容一点」的改动都会静默地
把「存储抖动」与「确知被接管」一起放宽。**登记为下一入口**（§7）。

## 4. 切片表

| 切片 | 内容 | 判据 |
| --- | --- | --- |
| S1 | `AcquireOutcome` + `acquire_outcome` + `acquire` 变投影；`LeaseHold` + `start_lease` 返回它 | `tests/unit/db/test_acquire_outcome.py` |
| S2 | `_execution_lease` 产出 `LeaseFence`（`outcome` + `lost`）；两条修复路径按原因裁定 | 扩 `tests/unit/api/test_repair_paths_take_the_lease.py` |
| S3 | 文档 §2/§5/§7/§8 与两张表；claims judge 的扫描与主张 | `test_execution_plane_claims.py` |

## 5. 红线 / 不做 / 验收

**不做**：

- 不改 `acquire()` / `renew()` 的**布尔投影**语义（`acquire` 的 60+ 条既有断言必须全绿、一字不改）；
- 不改统一入口 `_run_graph_and_persist` 的拒绝语义（裁定 C）；
- 不改 `renew` 的任何行为（裁定 D，登记）；
- 不改 `_fence_on_lost_lease` 的取消条件；
- 不改 `_takeover._consider` 的裁定（它对两种拒绝都停，是安全的，且已由 §5 写明）。

**验收**：

1. `acquire_outcome` 在**两个后端**上对同一场景答同一个值（含「外部持有者」与「存储答不上来」）；
2. 「两个后端答案集合不同」这条**不再成立**，且由判据钉住；
3. `start_lease` 被拒时 `LeaseHold.outcome` 说出是哪一种；
4. 两条修复路径在 `HELD_BY_LIVE_OWNER` 下**不写 checkpoint**（可观测：`aupdate_state` 零调用）；
5. `UNKNOWN` 下两条修复路径**仍然跑完**（裁定 2 不变）；
6. 原有 **3672** 条用例全绿（`start_lease` 的 4 条按裁定 B 改强）；门禁四道全过。

## 6. 登记未修（带理由，本片不动）

1. **`renew` 的同形合并**（裁定 D）—— 见 §7 第 1 条。
2. **空 `thread_id` 归入 `UNKNOWN`**：它是调用方 bug 的守卫，与「存储答不上来」不同源。
   分成第四档会让枚举里出现一个**永远不该被调用方看到**的值；保持合并，但**在 docstring 里写明**。
   （判据只能钉「它答 `UNKNOWN`」，钉不住「调用方不该传空」—— 那是类型层面的事。）
3. **修复路径的拒绝对调用方不可见**：`retry_ripple_analysis` 已经返回 200 了，协程再拒绝
   没法改那个响应。可观测渠道是 `workflow_events` + 日志。**要让它可见需要端点级别的预检**，
   而那需要一个只读的「谁持有」接口（今天的 `thread_is_held` 不区分是不是自己）。
4. **`release` 也有 4 个 `False` 出口**（`:386` 空 id · `:391` 不是我们的 · `:401` except · `:402` `released` 假）。
   未合并的后果比前两个轻：`end_lease` 不据此做决定。**登记。**

## 7. 留给下一任务的输入

1. **`renew` 的「不是你的」与「问不到」要分开**（§4 裁定 D）。安全方向与 `acquire` **相反**：
   `acquire` 要「问不到照跑」，`renew` 要「问不到照停」。分开之后才谈得上讨论
   「一次存储抖动该不该 cancel 一个健康运行」—— 今天这句话没有可讨论的对象。
   带**量出来的**代价：`_fence_on_lost_lease` 会 `owner.cancel()`，而同步执行的 run 被 abort 的是
   **调用者正在等的那个 HTTP 响应**（§5 已写明）。
2. **`release` 的 4 个出口**（§6 第 4 条）—— 同形，后果轻，未量。

下面两张表把上面这些**位置**与**数值**钉住（前者的机制同 §6；后者由
`tests/unit/scripts/test_execution_plane_claims.py` 从代码重算）。

## 8. 执行记录

（交付时回填：改动表 · 验收逐条对照 · 门禁 · 突变自检 · commit/PR）
