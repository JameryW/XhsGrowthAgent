# 执行平面（Execution Plane）

> P2b 的交付面。它回答一个问题：**一次工作流执行在进程重启、多实例、以及没有 Postgres 的时候，究竟被承诺了什么。**
>
> 本文件里的 `file:line` 分两档被钉住：**被标记表括起来的**（§6 / §6.1 / §7 / §8）逐字断言某个
> token 出现在那一行；**散文里的**没有 token 可比，只保证解析得到、且在范围内。两档分别由
> `tests/unit/scripts/test_docs_anchors.py` 与 `tests/unit/scripts/test_execution_plane_claims.py`
> 检查 —— 改动那些行会让测试变红，而不是让文档悄悄过期（见 §8）。

## 0. 结论：S4 按裁定 1 降级

裁定 1 的闸门是**证据**：S1–S3 之后若仍拿不到「长任务占住编排进程」的可观测证据，S4 就不做进程外执行，只交文档 + 逐点分类清单。

**拿不到。四条证据：**

| # | 证据 | 为什么它反驳「占用」 |
| --- | --- | --- |
| A | 34 条执行点逐行分类（§6），其中的长任务**全部**由 `asyncio.create_task` 起 | 它们在 await 上跑，不阻塞事件循环 —— 占住的是 thread，不是进程 |
| B | 「请求内同步跑完整条工作流」的路径**存在**（`backend/api/routes/_wf_application.py:271` 的 `else` 分支 → `:275` 的 `_run_graph_and_persist`）但**非默认**（`backend/api/routes/_wf_models.py:31` `async_mode: bool = Field(default=True`） | 唯一真正「占住请求」的形状是可选路径；默认形状不占 |
| C | 长任务的时长有界，且界可静态读出：通用工具网 `backend/tools/runtime/catalog.py:513` `timeout_s=120.0`、发布 `:92` `_PUBLISH_SAFETY_NET_S = 900.0`、Ripple `:82` `_RIPPLE_SAFETY_NET_S = 3600.0` | 「占住」的签名是**无界**；这里有界，且界都落在等外部上 |
| D | 本机无真实运行样本：`.xhs/checkpoints.sqlite` 0 行，`history/*.json` 全是 21 字节的测试残留 | 没有样本，「实测占用」这一档证据拿不到 |

**推论**：Ripple 的 3600s 是唯一的量级异常，但它挂在一条 **await** 上的安全网里，不是阻塞调用。⇒ **进程外执行移交下一任务；S4 的产出是「边界」，不是「迁移」。**

§7 是本次侦察真正的收获：**执行平面的承诺只覆盖 `_run_graph_and_persist`**，而仓里有两个写 checkpoint 的修复路径绕过了它。

## 1. 这个「平面」由三件东西组成

| 件 | 位置 | 作用 |
| --- | --- | --- |
| 租约 | `backend/db/execution_leases.py` | 「谁在跑这个 thread」的可查记录，带 TTL 与心跳 |
| 栅栏 | `backend/api/routes/_runner.py:355` `_fence_on_lost_lease` | 租约没了 ⇒ 正在跑的那个**停下** |
| 接管 | `backend/api/routes/_takeover.py:155` `takeover_scan` + `backend/graph/takeover_safety.py` | 租约过期 ⇒ 有人把它接过来 |

三者缺一不可：只有记录 ⇒ 死进程的行会永远写着 running（S1 之前的状态）；只有接管没有栅栏 ⇒ 接管本身就是红线 4 的双写（S3 补上）。

## 2. 租约保证什么、不保证什么

**保证**

1. **同一 thread 上不会有两个进程同时被授予。** 授予是一次条件更新（内存后端那三个合取条件 —— `backend/db/execution_leases.py:383` `existing.state is LeaseState.HELD` 是其中一条 —— 对应 SQL 侧的 `_ACQUIRE_SQL`（`:288`）的 `WHERE`），不是「先读再写」。
2. **失去租约的执行者会停。** `_fence_on_lost_lease` 以**结束方式**当裁判：`task.cancelled()` ⇒ 这是 `end_lease` 正常收尾，不栅栏；非 cancelled ⇒ 心跳带着它停下时拿到的那个 `RenewOutcome` 结束（见下条 4）⇒ 置事件并 cancel 宿主。`CancelledError` 分支（`backend/api/routes/_runner.py:566` `if lease.lost.is_set():`）**直接 raise、不写状态** —— 写 `cancelled` 会擦掉刚刚发生的接管。

**不保证**

1. **「问不到」不阻止执行，「有人正持有」会 —— 这两件事直到本片才是两个值。**
   `backend/db/execution_leases.py:683` 的 `start_lease` 返回一个 `LeaseHold`（`AcquireOutcome` + 心跳），三条路各按原因裁定：
   - `UNKNOWN`（存储答不上来、或模块都导不进来）**runner 照样跑**，没有栅栏可装。这不是疏漏，是裁定 2：把执行挂在租约的回答上，会在存储答不上来的时候 fail-closed，而那正是租约从「观测」变成「闸门」的方式。
   - `HELD_BY_LIVE_OWNER`（活着的外部持有者）是**证据**，不是证据的缺席 —— 裁定 2 覆盖不到它。两条修复路径因此 **stand down**：不写 checkpoint、不跑 `run_publish`，只留一条 `action` 事件（§7）。统一入口仍然照跑，它的拒绝语义属于 `/recover` 等端点。
   - 接管扫描两档都当终局（`backend/api/routes/_takeover.py:136` 的闸门），因为「不恢复」是那个决定的**安全侧**。
   在此之前这三件事被写成一个 `False`：`acquire` 有 **3** 个 `False` 出口而内存后端只有 **1** 个（它不会失败）⇒ 两个后端对同一个问题**答的集合不一样**。这是本条要消掉的形状，但**不是无条件的** —— 判据是这一条：

   > **一个答案该有几个值，由「谁据此做决定」决定。** 有决定者 ⇒ 两种非答案必须分得开，否则决定会做错；没有决定者 ⇒ 分开只会造出几个**全都会被丢弃**的值。

   「后果轻」不是判据 —— 那是一条**估的**判断，下一片复核不了它，也看不出它哪天不成立。按上面这条重述之后，`release` 仍然塌成一个 `bool`，但依据变成可重算的了：它的读者数是 `0`，由 `tests/unit/scripts/test_execution_plane_claims.py` 每次从树重算（两条判据见 §7 的主张表）。

   | 问题 | 决定者（读值的那一处） | 不做决定会怎样 | 值的个数 |
   | --- | --- | --- | --- |
   | `acquire` / `acquire_outcome` | 接管扫描 `backend/api/routes/_takeover.py:139`：拒绝 or 照跑 | 同一个 checkpoint 两个写者 | **3** |
   | `renew_outcome` | 心跳 `backend/db/execution_leases.py:640`：停 or 继续 | 红线 4 | **3** |
   | `release` | **无** —— 唯一的调用点 `backend/db/execution_leases.py:742` 把答案丢掉 | 退化成 `kill -9` 那条已有路径：行留着 `held`，别的实例最多多等 1 个 TTL | **1** |

   ★ 塌陷的是**值**，不是**理由**：`release` 的 `except` 自己 `logger.warning`（`backend/db/execution_leases.py:561`），所以「问不到」在日志里仍是一个可识别的名字。这是它允许塌成 `bool` 的全部依据。
2. **租约默认不是持久的。** 见 §4。
3. **租约覆盖三个执行者，不覆盖请求处理器里的旁写。** 一个 `_execution_lease` 实现、三个执行者（统一入口 + 两条修复路径），而二十处旁写不在其中 —— 判据在 §7。这是本文件最该被读到的一句。
4. **「被接管」与「问不到」是两档，而且它们**价格不同**。** `renew` 的 `False` 拆成了 `RenewOutcome`（`backend/db/execution_leases.py:138`）：`LOST`（这一行已不是本实例的）与 `UNKNOWN`（存储答不上来）。**方向与上一条的 `acquire` 相反**：那边「问不到要照跑」（裁定 2），这边「问不到照停」—— 没有租约就开始的 run，风险是**白干**；丢了租约还在写的 run，风险是**同一个 checkpoint 两个写者**（红线 4）。
   - `LOST` 是**关于行的事实**：零预算，第一次就停。它必须在咨询预算**之前**被决定（`backend/db/execution_leases.py:627` 的循环把这一档写在计数之前），否则放宽预算会**顺带**把「确知被接管」一起放宽。
   - `UNKNOWN` 是**沉默**，容忍 `backend/db/execution_leases.py:96` `HEARTBEAT_TRANSIENT_FAILURES_TOLERATED` 次**连续**失败（= `HEARTBEAT_MISSES_BEFORE_EXPIRY - 2` = **1**），再一次才停；成功的 `renew` 把计数清零，因为它移动的正是「行变老」的那个锚点。容忍的那一次单独记一行日志 —— 过去「抖动但扛住了」与「什么都没发生」在日志里同形。
   ★ **两把尺子是同一把，量出来的数不一样（扫描 2 / 拥有者 1）**：行要到 `heartbeat_at + ttl`（= 上次成功续租后一整个 TTL）才**变得可被抢**（`_ACQUIRE_SQL` 的最后一个 `OR` 项），而「检测一次失败」本身要花时间（失败的 `renew` 得先跑完才轮得到计数），所以得留**一整个 interval** 作余量 ⇒ 拥有者能容忍的是 `M - 2`，不是扫描侧的 `M - 1`。**把两个数对齐会让拥有者恰好停在行变老的那一刻。**
TTL 与心跳：`backend/db/execution_leases.py:83` `HEARTBEAT_MISSES_BEFORE_EXPIRY = 3`、`:84` `LEASE_TTL_SECONDS = 90.0`、`:85` `HEARTBEAT_INTERVAL_SECONDS` ⇒ 心跳 30s，连丢 3 次判过期。

## 3. 单进程现实 vs 文档拓扑

`docs/deployment.md` 声明的是水平扩展拓扑：

- `docs/deployment.md:9` 画了 `Load Balancer`，`:15` 画了三个 `API #1 / #2 / #3`
- `docs/deployment.md:421` 给了 `--workers 4`
- `docs/deployment.md:429` 给了 `-k uvicorn.workers.UvicornWorker`

镜像实际跑的启动命令是：

- `Dockerfile:81` `CMD ["uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8889"]`

**没有 `--workers`** ⇒ uvicorn 单进程、单事件循环。

把这条写下来的理由不是「文档错了要改文档」，而是它决定**接管在本机部署形态下的语义**：单进程里，本进程持租约、本进程也在扫描，`expire_scan()` 能看到的只有**别的实例留下的**死行。所以

> 在本机部署形态下，自动接管是**为多实例准备的、平时不会触发的能力**。

它今天真正在做的事是另一种情形：`kill -9` 之后**新进程**启动时，扫到**旧进程**留下的过期行（§5 的启动扫描）。

## 4. 没有 Postgres 的时候

`backend/db/execution_leases.py:249` `def durability()` 是唯一回答「这里的租约能不能比这个进程活得久」的读者，`:256` 是它的实现：

- `durable`：租约在 PG 里，跨进程可见，接管有意义。
- `none`：租约只在进程内。重启即消失 ⇒ 没有过期行 ⇒ 扫描扫不到东西，也不需要扫。

这两种状态不能靠「有没有租约」区分，所以 `/health` 把 `durability` 作为 `execution_takeover` 的一个字段发出来（`backend/api/app.py:1615`）。**它是运维唯一能区分「降级的租约」和「看起来持久的租约」的地方。**

## 5. 接管的安全边界

一次接管要同时满足两个独立条件，任一不满足就**拒绝**：

1. **节点安全**（`backend/graph/takeover_safety.py:56` `TAKEOVER_HAZARDS`）：穷举注册表，照 `RETRY_POLICIES` 的先例，未知名抛 `KeyError` —— 因为「回落到默认值」等于给一个没人分类过的节点答 `safe`，那是这里唯一错误的答案。分三档：`safe` / `needs_human` / `irreversible`（成员清单以注册表本身为准，本文件不复述，避免两处腐烂）。`publisher` 是唯一 `irreversible` 的节点：它真的向小红书发帖。
2. **能拿到租约**（`backend/api/routes/_takeover.py:139`）：`acquire` 的两种拒绝 —— 活着的外部持有者、或存储根本答不上来 —— **两种都意味着这次扫描不能继续**，且都不重试，直到那一行再次安静下来。★ 这两件事现在**分得开了**（`backend/db/execution_leases.py:400` 的 `acquire_outcome` 答得出是哪一个），而这里**刻意不分流**：分流会改变这个决定，而本节论证的是「两档都停」才是安全侧。**「答得出来」与「据此分流」是两件事** —— 所以这一行的判据没有变，变的只是它不再是唯一的选择。

只分类**待跑节点**（`state.next`），不按可达集：进 `publisher` 的唯一来源是 `publish_gate`，而它自己是 `needs_human`，这条前提由 `build_graph()` 的边直接钉住（见 §8 提到的测试）。

`backend/api/routes/_takeover.py:105` `_consider` 留了两条跳过：没有 `state.values`（租约活着但 checkpoint 没了 ⇒ 交给 `/recover` 的 `checkpoint_lost` 诊断）、`state.next` 为空（跑完或报错退出 ⇒ 那是人的 `/recover` 路径）。

**已知代价（S2 登记，这里重申）**：崩溃后 TTL 窗口内（90s 量级），`/recover` 会拒绝恢复，因为死进程的租约还没到期。这是刻意的取舍 —— 另一个方向（把「查不到活任务」也当作可以恢复）会在存储故障时起第二份执行。

**接管的副作用要接受**：栅栏会 cancel 宿主 task；若那次执行是同步跑的（§0 证据 B 的那条分支），被 abort 的是**调用者正在等的那个 HTTP 响应**。仍然是更好的那一侧：被 abort 的请求优于同一 checkpoint 上的第二个写者。

## 6. 逐点分类清单（34 条）

读法：`锚点` 是 `file:line`，`证据` 是那一行**逐字包含**的 token（由测试断言，见 §8）。分类含义：

- `LEASE_HEARTBEAT` —— 租约自己的心跳任务。
- `REAL_TASK` —— 一个真的会跑很久的任务。
- `IN_PROCESS_LOOP` —— 服务级常驻循环，随 lifespan 起停。
- `CACHE_WARMUP` —— 预热，只为省掉下一次的等待。
- `POST_RESPONSE` —— 响应之后才做完的收尾，结果不回流给调用者。
- `PLANE` —— 执行平面自身的接线点。

<!-- anchor-table:begin -->

| 锚点 | 证据 | 分类 | 备注 |
| --- | --- | --- | --- |
| `backend/db/execution_leases.py:722` | `asyncio.create_task(` | LEASE_HEARTBEAT | 被调名在 `:723`；由 `end_lease` 取消，取消即正常收尾 |
| `backend/api/routes/_wf_runtime.py:351` | `task = asyncio.create_task(_resume_async())` | REAL_TASK | 走统一执行入口，持租约；注册于 `:353` |
| `backend/api/routes/_wf_application.py:258` | `task = asyncio.create_task(_run_async())` | REAL_TASK | 走统一执行入口，持租约；注册于 `:260` |
| `backend/api/routes/_wf_actions.py:252` | `task = asyncio.create_task(_run_retry()` | REAL_TASK | **取租约、不注册** —— 见 §7 |
| `backend/api/routes/_wf_actions.py:447` | `task = asyncio.create_task(_run_publish_retry()` | REAL_TASK | **取租约**；注册于 `:449` |
| `backend/agents/content_strategist.py:597` | `task = asyncio.create_task(_run())` | REAL_TASK | 不写工作流 checkpoint |
| `backend/api/routes/accounts.py:404` | `background_tasks.add_task(sync_after_login, account_id)` | REAL_TASK | Starlette 后台任务，跟响应生命周期走 |
| `backend/services/creator_stats/client.py:738` | `task = asyncio.create_task(capture(response))` | REAL_TASK | 采集响应，结果进缓存 |
| `backend/services/creator_stats/client.py:844` | `data_ready = asyncio.create_task(_wait_initial_data())` | REAL_TASK | 与 `:845` 竞速，先到先算 |
| `backend/services/creator_stats/client.py:845` | `auth_ready = asyncio.create_task(auth_failed.wait())` | REAL_TASK | 同上 |
| `backend/services/omp_bridge.py:2588` | `task = asyncio.create_task(` | REAL_TASK | 会话级任务 |
| `backend/services/ripple_service.py:805` | `sse_task = asyncio.create_task(` | REAL_TASK | 消费 SSE，上界 3600s |
| `backend/services/xhs_publisher.py:154` | `pending = {asyncio.create_task(_wait(selector))` | REAL_TASK | 多个选择器并发等待 |
| `backend/services/chrome_launcher.py:1685` | `chrome_resources_task = asyncio.create_task(` | REAL_TASK | 与 `asyncio.to_thread` 的探测配合 |
| `backend/api/routes/agent.py:185` | `sender_task = asyncio.create_task(sender())` | IN_PROCESS_LOOP | 会话内发送循环 |
| `backend/services/omp_bridge.py:2160` | `asyncio.create_task(self._drain_stderr())` | IN_PROCESS_LOOP | 子进程 stderr 排空 |
| `backend/services/omp_bridge.py:2163` | `self._reader_task = asyncio.create_task(self._read_stdout())` | IN_PROCESS_LOOP | 子进程 stdout 读取 |
| `backend/services/omp_bridge.py:2867` | `self._idle_timers[session_id] = asyncio.create_task(_idle_timeout())` | IN_PROCESS_LOOP | 空闲超时器 |
| `backend/services/ripple_service.py:264` | `self._bg_task = asyncio.create_task(self._health_check_loop` | IN_PROCESS_LOOP | 服务级健康循环 |
| `backend/api/app.py:1362` | `takeover_task = asyncio.create_task(` | IN_PROCESS_LOOP | 接管扫描；开关在 `:1357`，关停在 `:1469` |
| `backend/api/app.py:1443` | `creator_stats_scheduler = asyncio.create_task(` | IN_PROCESS_LOOP | 采集调度器 |
| `backend/api/routes/agent.py:89` | `_prewarm_tasks[session_mode] = asyncio.create_task(_warm())` | CACHE_WARMUP | 按会话模式预热 |
| `backend/api/routes/public_showcase.py:756` | `task = asyncio.create_task(_run())` | CACHE_WARMUP | 公开页预热 |
| `backend/api/routes/public_showcase.py:842` | `task = asyncio.create_task(_run())` | CACHE_WARMUP | 公开页预热 |
| `backend/api/routes/system.py:207` | `_ripple_probe_task = loop.create_task(_run())` | CACHE_WARMUP | 用的是 `loop.create_task` |
| `backend/api/routes/system.py:326` | `ripple_task = asyncio.create_task(_check_ripple())` | CACHE_WARMUP | 健康检查里的预热 |
| `backend/api/routes/system.py:327` | `memory_task = asyncio.create_task(_check_memory_store())` | CACHE_WARMUP | 健康检查里的预热 |
| `backend/agents/analyst.py:287` | `asyncio.create_task(_safe_evolve` | POST_RESPONSE | 演化写回不回流 |
| `backend/api/routes/free.py:915` | `asyncio.create_task(` | POST_RESPONSE | 响应后收尾 |
| `backend/memory/calibrator.py:73` | `return asyncio.create_task(` | POST_RESPONSE | 校准写回不回流 |
| `backend/api/routes/_wf_runtime.py:102` | `asyncio.ensure_future(_do_update())` | POST_RESPONSE | 用的是 `ensure_future` 而非 `create_task` |
| `backend/api/routes/_runner.py:407` | `heartbeat.add_done_callback(_on_heartbeat_done)` | PLANE | 不是新任务：把栅栏登记到租约心跳的结束回调上 |
| `backend/services/ripple_service.py:214` | `loop.create_task(self._rebuild_client())` | POST_RESPONSE | 重建客户端 |
| `backend/services/xhs_risk_gate.py:357` | `_persist_task = loop.create_task(_run())` | POST_RESPONSE | 风控快照落盘 |

<!-- anchor-table:end -->

**34 条里没有一条是同步阻塞调用。** 这是 §0 证据 A 的原始材料。

### 6.1 执行平面自身的接线点

<!-- anchor-table:begin -->

| 锚点 | 证据 | 分类 | 备注 |
| --- | --- | --- | --- |
| `backend/api/routes/_runner.py:484` | `async def _run_graph_and_persist(` | PLANE | 唯一执行入口，12 个调用点 |
| `backend/api/routes/_runner.py:458` | `hold = await start_lease(thread_id)` | PLANE | **全仓唯一取租约处**，在 `_execution_lease` 里，三个执行者共用；答案（`LeaseHold`）与心跳一起返回，不重新问一次 |
| `backend/api/routes/_runner.py:471` | `lost = _fence_on_lost_lease(thread_id, heartbeat)` | PLANE | 栅栏接线：只有拿到了租约才装 |
| `backend/api/routes/_runner.py:566` | `if lease.lost.is_set():` | PLANE | 被栅栏的 run 不写状态 |
| `backend/db/execution_leases.py:249` | `def durability()` | LEASE | 无 PG ⇒ `none` |
| `backend/db/execution_leases.py:256` | `is_pool_ready()` | LEASE | 唯一判据 |
| `backend/api/app.py:1615` | `execution_takeover = {key: takeover_state.get(key)` | HEALTH | 白名单出口 |
| `backend/graph/takeover_safety.py:56` | `TAKEOVER_HAZARDS: dict[str, TakeoverHazard] = {` | SAFETY | 穷举注册表 |
| `backend/api/routes/_takeover.py:136` | `# The gate.` | SAFETY | 两种拒绝都继续当终局 —— 它们现在分得开，这里刻意不分流（§5 第 2 条） |

<!-- anchor-table:end -->

## 7. 修复路径：租约取到了哪一步，判据怎么圈

`_run_graph_and_persist`（`backend/api/routes/_runner.py:433`）是统一执行入口，它有 12 个调用点，
S1–S3 的全部承诺都落在这 12 条路径上。仓里另有两个**修复路径**：它们被处理器起成独立任务、
**自己驱动执行**：

- `backend/api/routes/_wf_actions.py:120` `async def _run_retry()` —— ripple-retry。
- `backend/api/routes/_wf_actions.py:350` `async def _run_publish_retry()` —— publish-retry。

**判据。** 本文件早先的版本把这两条写成「直接写 checkpoint、**不取租约**」。按那条判据，
树里要圈进 **20** 处：`await <graph>.aupdate_state(...)` 在统一入口之外有 20 个调用点、
分布在 **7** 个文件（`_wf_application.py` 8 · `review.py` 4 · `_wf_actions.py` 3 · `optimization.py` 2 ·
`_wf_runtime.py` 1 · `blogger.py` 1 · `evaluation.py` 1）。其中 18 处写在**请求处理器的同步体内**：
要么写完就返回、执行根本不发生（`start_workflow` 的 `waits_for_brief_upload` 分支、`pause_workflow`、
`cancel_workflow`），要么写完**接着**起一个走统一入口的任务（`resume_workflow` → `_start_resume_task`
→ `_run_graph_and_persist`）。⇒ 能圈住这两处的判据是：

> **处理器起完就丢、由该协程自己驱动执行。**

它同时把这 2 处与 18 处旁写分开，而分开它们的理由正是执行平面的理由：**只有这 2 处的执行整段
落在租约之外**。旁写写的是同一份 checkpoint，但那一次写入是瞬时完成的，不在任何接管窗口里。

**租约。** 两条路径通过 `backend/api/routes/_runner.py:408` 的 `_execution_lease`
（一个 `@contextlib.asynccontextmanager`）取租约 —— 与统一入口**同一个实现**：全仓 `start_lease(`
与 `end_lease(` 仍各只有 **1** 处调用点，只是执行者从 1 个变成 **3** 个。

| 问题 | 裁定 | 依据（可重算） |
| --- | --- | --- |
| 两条修复路径取租约 | **采纳** | 关掉「修复先到」那一侧的接管竞争 |
| 取租约只保留一处实现 | **采纳** | 执行入口与两条修复路径共用 `_execution_lease` |
| 给 ripple-retry 一个自己的键 | **不采纳** | 它关的是另一个洞：进程内「执行撞重试」，见下面「守卫是单向的」 |

**买到的东西。** 修复先到时，它持有一行**新鲜心跳** ⇒ `expire_scan()` 不会把它翻成 `expired`
⇒ 接管扫描根本看不到它；即便有人抢在中间调 `acquire`，`backend/db/execution_leases.py:288` 的
`_ACQUIRE_SQL` 也会因「行是 HELD 且 `heartbeat_at + ttl > now()`」而拒绝。**在此之前这一侧是开着的。**

**栅栏也接得住它。** `backend/api/routes/_runner.py:376` 的取消靶子是 `asyncio.current_task()`，
**不读登记表** ⇒ 一个刻意不在槽里的任务照样在丢租约时被 cancel，且 `lease.lost` 会让
`CancelledError` 分支不写状态。**这是「不需要自己的键也能拿到过期保护」的证据。**

**代价（三条都量过，都要登记）：**

- 修复期间它被算作「有人在跑」⇒ `/recover` 在修复期间拒绝（`backend/api/routes/_wf_application.py:1077`
  只放行 error/stale）。ripple-retry 最长 **1800s**。
- `derive_status` 里 `has_active_task` 只在**优先级 9/10**起作用（`backend/state/machine.py:46-47`）
  ⇒ 这次改动的可见面**只有** `stale → running` 一格，其余分支全部短路。
- ★ **租约泄漏不会导致自动重发。** 修复协程若被 `kill -9`，行变 silent、90s 后被 `expire_scan`
  翻成 `expired`，扫描会考虑它 —— 但**节点安全闸门先拒绝**：publish-retry 的待跑节点含
  `publisher`（`irreversible`）、ripple-retry 停在 `ripple_gate`（`needs_human`）⇒
  `backend/api/routes/_takeover.py:127` 直接 `refused`，连 `acquire` 都不到。
  **不量这一条就不能采纳**：它是这次改动最重的风险，而挡住它的是那张已有的穷举注册表。

**★ 留下的那一格，已由本片关闭。** `_ACQUIRE_SQL` 仍然答不出是哪种拒绝 —— `backend/db/execution_leases.py:300` 的 `WHERE` 把三个条件或在一起，一个 `INSERT ... ON CONFLICT` 的**行数**说不出是哪一格拦下的。分开它们的不是改那句 SQL，而是把判据**重述成合取**：行存在 · `state == held` · `owner_id != 本实例` · 未过期 —— 与内存后端逐字对应，于是 `acquire_outcome` 判得出 `HELD_BY_LIVE_OWNER`，两条修复路径对它就 stand down。
窗口（「`/status` 开始报 stale」到「扫描的下一趟接管」，即一个 `takeover_interval_seconds`，默认 60s 量级）里「扫描先接走、修复后到 ⇒ 两个写者」不再成立。
★ **单进程部署形态下这条改动不可观测**：`_ACQUIRE_SQL` 的 `WHERE` 含 `owner_id = EXCLUDED.owner_id` ⇒ 本进程永远能重新授予自己，这一格只有**≥2 个持有者同时活着**时才出现 —— 滚动发布就是。判据在 `tests/unit/db/test_acquire_outcome.py`（两个后端对同一场景答同一个值）与 `tests/unit/api/test_repair_paths_take_the_lease.py`（该档下 `aupdate_state` 零调用、`run_publish` 零调用）。

### 7.1 兄弟路径那四条性质，以及登记表的裁定（#634）

早先的版本把这两条路径的差异写成「直接写 checkpoint、不取租约」，并据此把缺口列成四条。取租约之后
那句的前半句不再成立（见上），四条也各自有了裁定。后果仍然是精确的，不是笼统的「不够健壮」：

- **`_run_retry` 连任务注册表都没进** ⇒ 起了任务之后没有
  `_runner._background_tasks[thread_id] = task`（对比 `backend/api/routes/_wf_actions.py:449` 的
  publish-retry 有）。★ **这条的后果是「同进程内看不见它」**：`has_active_execution`
  （`backend/api/routes/_runner.py:94` 把登记表 OR 进去）与三个直接读槽的动作都答「没人跑」。
  **但补上登记表并不解决重启那一侧** —— 登记表是进程内的，重启后本来就是空的
  （`backend/api/routes/_runner.py:43` 的注释就写着这一点）。上一版把这两件事写成了一条因果。
- **重启后的可见性只有租约能回答** —— 本片补上了它，所以这一条不再是缺口（见上）。

**两问的裁定。** 上一版把两问留给下一任务，并要求带着 1800 秒做。答完之后有一条被顺带推翻：
「补注册表写入」不是第 4 个缺口 —— 它是**换靶子**。

| 性质 | 裁定 | 依据 |
| --- | --- | --- |
| 串行化守卫 | **采纳** | `backend/api/routes/_wf_actions.py:296` 的注释把意图写成「工作流正在跑（**含正在重试**）时不允许再触发」；`backend/api/routes/_runner.py:51` 的 docstring 说它答的是「本进程要不要起活」。两处**同一个谓词、同一句文案** |
| `add_done_callback` | **不采纳** | `_on_task_done` 的两个分支写的都是**工作流**的列：`backend/api/routes/_wf_runtime.py:93-96` 把异常写进 `status=error` 与 `error`，`:97-99` 把仍 `running` 的库标 `stale`。而 ripple-retry 结束**不代表工作流结束** ⇒ 照抄会把暂停/在跑的工作流说成 stale |
| `_background_tasks[...] =` | **不采纳** | 见下 —— 登记表**每 thread 一槽**，写入是换靶子而不是补一行 |
| 被起协程的自身清理 | **连带不采纳** | 没有登记就没有要清理的条目 |

**★ 登记表为什么不能补：它的 key 就是 `thread_id`。** `backend/api/routes/_runner.py:45` 声明的是
`dict[str, asyncio.Task[Any]]` ⇒ **每个 thread 只有一个槽**。仓里有 3 处写入者，而 **3** 处读者读的
就是槽里的那一个任务并**取消它**：`backend/api/routes/_wf_application.py:663`（`pause_workflow`）、
`:1209`（`cancel_workflow`）、`backend/api/routes/_wf_runtime.py:331`（`_start_resume_task`）；
另有一处（`backend/api/routes/_wf_application.py:1516`，`delete_workflow`）在槽被占用时**拒绝删除**。

探针实测（真模块，不是推的）：同一 thread 写两次之后只剩 1 条，槽里是后写的那个，前一个**从登记表里
消失**，`pause`/`cancel` 的 `cancel()` **打到重试身上**，而工作流照跑 —— 库里写着 `paused`/`cancelled`，
真的执行还在写同一个 checkpoint。工作流自己的条目也**再不会恢复**：它的自清理有
`is asyncio.current_task()` 身份守卫（`backend/api/routes/_runner.py:646`），被顶掉之后那个 `pop`
永远不成立。⇒ 这一行的代价不是「30 分钟静默拒绝」，而是**把三个破坏性动作的靶子换掉**。

**★ 守卫是单向的，这句要一起写。** 它挡「重试撞本进程的执行」，**挡不住**反向的「执行撞重试」 ——
后者发生在 `_start_resume_task`，它取消的是**槽里**的东西，而 ripple-retry 刻意不在槽里。
**取租约也不关这一格**：`_start_resume_task` 不读租约，它只读登记表。所以两个写者仍可能在飞。

**留给下一任务的输入**（一条）。带**量出来的**代价，不是估的：

1. **ripple-retry 在进程内不可取消。** 关它需要一张**只有 `_start_resume_task` 读**的可取消登记表
   —— 也就是新增一个 cancel 靶子面。publish-retry 因为**在**槽里，这一方向已经关了。

> **已从这张清单结掉的两条**（写在这里，因为「结掉」与「删掉」不是一件事）：
> `release` 的 4 个 `False` 出口由 `09-20-release-has-no-decider` 结掉 —— 它**没有**分开，理由是
> **零决定者**：判据与家族表见 §2 不保证 1，两个方向各一条主张在下面的表里。原第 1 条
> （`LOST` 零预算立即停、`UNKNOWN` 容忍 `HEARTBEAT_MISSES_BEFORE_EXPIRY - 2` 次连续失败）由
> `09-20-heartbeat-tolerates-a-hiccup` 结掉，见 §2 不保证 4。
> ★ 这张清单自己出过一次错：`87e55a09` 把原第 3 条提到第 1 位时**没删原件**，于是同一条登记在这里
> 有两份副本、而标题写着「三条」。**副本是承袭来的文字，不是第二条待办。**

下面两张表把上面这些**位置**与**数值**钉住（前者的机制同 §6；后者由
`tests/unit/scripts/test_execution_plane_claims.py` 从代码重算）。

<!-- anchor-table:begin -->

| 位置 | 必须出现的 token | 为什么 |
| --- | --- | --- |
| `backend/api/routes/_runner.py:426` | `_execution_lease` | 取租约的唯一实现；三个执行者共用它 |
| `backend/api/routes/_runner.py:484` | `_run_graph_and_persist` | 统一执行入口，12 个调用点 |
| `backend/api/routes/_runner.py:355` | `_fence_on_lost_lease` | 栅栏：读心跳**怎么结束的**，以及它带回来的那一个 |
| `backend/db/execution_leases.py:138` | `RenewOutcome` | renew 的两个非答案在这里分开 |
| `backend/db/execution_leases.py:459` | `renew_outcome` | 决定只做一次，`renew` 是它的投影 |
| `backend/db/execution_leases.py:496` | `_renew_in_memory` | 内存后端的答案集合：没有 `UNKNOWN` |
| `backend/db/execution_leases.py:640` | `_heartbeat_until_cancelled` | 两档都停的那一处，也是原因出仓的那一处 |
| `backend/db/execution_leases.py:527` | `async def release(` | 家族表的负例：答案塌成一个 `bool` 的那一处（§2 不保证 1） |
| `backend/db/execution_leases.py:742` | `release(thread_id)` | 全仓唯一的调用点，**丢掉**答案 —— 「零决定者」这条裁定的落点 |
| `backend/db/execution_leases.py:83` | `HEARTBEAT_MISSES_BEFORE_EXPIRY = 3` | §2 那条 TTL 脚注引的常量 —— 这行是**锚点行**，不是「解得到就行」：`:78` 也解得到，而它上面是注释 |
| `backend/db/execution_leases.py:96` | `HEARTBEAT_TRANSIENT_FAILURES_TOLERATED` | 拥有者的容忍预算 —— 从上面那个常量**推导**（`M - 2`），所以两个数不会各自漂移 |
| `backend/api/routes/_runner.py:458` | `start_lease` | 全仓唯一的 `start_lease(` 调用点（在 `_execution_lease` 里） |
| `backend/api/routes/_wf_actions.py:154` | `_run_retry` | ripple-retry |
| `backend/api/routes/_wf_actions.py:393` | `_run_publish_retry` | publish-retry |
| `backend/api/routes/_wf_actions.py:162` | `_execution_lease` | ripple-retry 取租约处 —— 同一实现、同一条规则 |
| `backend/api/routes/_wf_actions.py:395` | `_execution_lease` | publish-retry 取租约处 |
| `backend/api/routes/_wf_actions.py:252` | `asyncio.create_task` | ripple-retry 起任务处 → 它刻意不写登记表 |
| `backend/api/routes/_wf_actions.py:449` | `_background_tasks` | publish-retry 有；ripple-retry **刻意不写**（见 §7.1 对两问的裁定） |
| `backend/api/routes/_runner.py:51` | `process_has_active_task` | 串行化谓词（与状态谓词是两个问题） |
| `backend/api/routes/_wf_actions.py:302` | `process_has_active_task` | 消费者 1：publish-retry 守卫 |
| `backend/api/routes/_wf_actions.py:101` | `process_has_active_task` | ripple-retry 的守卫：与上一行同一个谓词 |
| `backend/api/routes/_wf_application.py:1675` | `process_has_active_task` | 消费者 2：brief 上传自动 resume |
| `backend/api/routes/_runner.py:94` | `process_has_active_task` | OR 进 `has_active_execution` 的那一处 |
| `backend/api/routes/_wf_actions.py:206` | `asyncio.gather` | 两个 submit 的并发消费点 ⇒ 窗口是 1 个 timeout |
| `backend/api/routes/_wf_actions.py:152` | `ripple_timeout` | 窗口的那个 1800.0 |
| `backend/api/routes/_wf_actions.py:296` | `含正在重试` | 兄弟路径的守卫注释 —— 意图的出处 |
| `backend/api/routes/_wf_actions.py:448` | `add_done_callback` | publish-retry 有；ripple-retry 刻意没有（回调写的是工作流的列） |
| `backend/api/routes/_wf_actions.py:445` | `_background_tasks.pop` | 自身清理，只在未被替换时执行 |
| `backend/api/routes/_wf_runtime.py:99` | `stale` | done 回调把仍 `running` 的库标成 stale —— 即使有了守卫也不照抄 |

<!-- anchor-table:end -->

<!-- claim-table:begin -->

| 主张 | 值 | 怎么重算 |
| --- | --- | --- |
| `process_has_active_task_consumers_outside_the_runner` | `3` | `backend/**` 里该谓词的调用点，排除它自己的定义模块 |
| `status_consumers_of_has_active_execution` | `7` | 同上，换成 `has_active_execution` |
| `run_graph_and_persist_call_sites` | `12` | 该函数的调用点数 |
| `start_lease_call_sites_under_backend` | `1` | 全仓 `start_lease(` 的调用点数 |
| `ripple_retry_max_wait_seconds` | `1800.0` | `ripple_timeout` 的字面值 |
| `ripple_retry_task_registrations` | `0` | 起该任务的那个函数里有没有把 task 存进 `_background_tasks` |
| `publish_retry_task_registrations` | `1` | 同上 |
| `ripple_retry_submits_are_concurrent` | `true` | 两个 submit 的结果是否被**同一个** `asyncio.gather` 消费 |
| `ripple_retry_serialization_guards` | `1` | 该处理器里 `process_has_active_task` 的调用点数 |
| `publish_retry_serialization_guards` | `1` | 同上 |
| `ripple_retry_done_callbacks` | `0` | 该处理器里 `add_done_callback` 的调用点数 |
| `publish_retry_done_callbacks` | `1` | 同上 |
| `ripple_retry_self_cleanups` | `0` | 它起的协程里有没有「`finally` 中移除注册表条目」 |
| `publish_retry_self_cleanups` | `1` | 同上 |
| `registry_task_write_sites_under_backend` | `3` | `_background_tasks[...] = ...` 的赋值点数（AST Store） |
| `registry_declared_value_type` | `asyncio.Task[Any]` | 登记表声明的槽形状：**每个 thread 一个任务** —— 「写入会顶掉」的前提 |
| `registry_readers_that_cancel_the_occupant` | `3` | 既读 `_background_tasks.get(` 又调 `.cancel()` 的函数数 |
| `repair_paths_using_the_shared_serialization_sentence` | `2` | 两条修复路径里含同一句拒绝文案的函数数 |
| `start_lease_call_sites_in_wf_actions` | `0` | `_wf_actions.py` 内 `start_lease` 的调用点数 —— 两条修复路径取的是共享的 `_execution_lease`，所以「0 处」现在说的是「这里没有第二个实现」，而**不是**「没有租约」 |
| `direct_aupdate_state_call_sites_in_wf_actions` | `3` | 同一文件内直接写 checkpoint 的处数 —— 「执行撞重试」那一侧今天没有任何闸门 |
| `repair_paths_taking_the_lease` | `2` | `_wf_actions.py` 内 `_execution_lease` 的调用点数 —— 两条修复路径各一处 |
| `lease_helper_definitions_in_the_runner` | `1` | `_runner.py` 内 `_execution_lease` 的定义数 —— 「取租约只有一处实现」的那个「一处」 |
| `end_lease_call_sites_under_backend` | `1` | 全仓 `end_lease(` 的调用点数（在同一个 helper 里） |
| `aupdate_state_call_sites_outside_the_unified_entry` | `20` | 宿主函数不是 `_run_graph_and_persist` 的 `aupdate_state` 调用点数 —— §7 的判据必须圈得住的两端 |
| `checkpoint_writer_files_outside_the_unified_entry` | `7` | 上一行涉及的**文件**数 |
| `repair_paths_that_own_their_own_task` | `2` | 「处理器 `create_task` 起的嵌套协程**自己**写 checkpoint」的处数 —— §7 用来圈集合的那条判据 |
| `expire_scan_call_sites_under_backend` | `1` | 全仓 `expire_scan(` 的调用点数（在 `takeover_scan` 里，由启动扫描与周期调度到达） |
| `takeover_scheduler_start_sites` | `1` | `app.py` 里把 `takeover_scheduler` 交给 `create_task` 的处数 —— 「租约真的会被翻成 expired」的那半句 |
| `derive_status_mentions_of_has_active_task` | `1` | `derive_status` 里 `if` 测试含 `has_active_task` 的分支数 —— 优先级 9/10 两格只由**一处**提及决定（10 是靠 9 落空到达的） |
| `acquire_outcome_members` | `3` | `AcquireOutcome` 的成员数 —— 拒绝不再是一个 `False` 的三种拼法 |
| `acquire_outcome_definitions_in_the_lease_module` | `1` | 该模块内 `acquire_outcome` 的定义数 —— 决定只做一次，`acquire` 是它的投影 |
| `execution_lease_call_sites_under_backend` | `3` | 全仓 `_execution_lease(` 的调用点数 —— 一个实现、三个执行者 |
| `repair_paths_that_stand_down_on_a_live_owner` | `2` | `_wf_actions.py` 内 `HELD_BY_LIVE_OWNER` 的出现次数 —— 两条修复路径各一处 |
| `lease_refusal_reasons_in_the_action_vocabulary` | `3` | `state/events.py` 里拒绝名的个数（`ACTION_` 前缀、字符串值、名字不含 `KIND`）—— policy / publish / lease 是三个不同的「不」 |
| `renew_outcome_members` | `3` | `RenewOutcome` 的成员数 —— 「不是你的」「问不到」不再是一个 `False` 的两种拼法 |
| `renew_outcome_definitions_in_the_lease_module` | `1` | 该模块内 `renew_outcome` 的定义数 —— 决定只做一次，`renew` 是它的投影 |
| `renew_call_sites_under_backend` | `0` | 全仓 `renew(` 的调用点数 —— 心跳问的是**具名**的那个问题；这个 `0` 说的是「没有第二个消费者」，不是「没有续租」 |
| `renew_outcome_call_sites_under_backend` | `2` | 全仓 `renew_outcome(` 的调用点数 —— 投影一处（`renew` 自己）+ 真正读它的那一处（`_heartbeat_until_cancelled`） |
| `transient_failures_the_owner_tolerates` | `1` | `HEARTBEAT_MISSES_BEFORE_EXPIRY - 2`，**从推导重算**而不是读字面量 —— 拥有者容忍几次连续失败就停；扫描侧是 `M - 1`，差的这一个 interval 就是「检测一次失败」本身要花的时间 |
| `the_budget_never_covers_the_evidenced_answer` | `true` | 读**顺序**：循环在咨询预算**之前**就决定了 `LOST` —— 把预算写在前面（或让它覆盖那一档）就是把「关于行的事实」也拿去容忍，也就是把裁定翻过来 |
| `misses_the_scanner_tolerates` | `2` | `HEARTBEAT_MISSES_BEFORE_EXPIRY - 1` —— 连丢几次才被判过期；§2 不保证 4 那条不对称的一半 —— 另一半是上面那两条（拥有者 `M - 2`） |
| `readers_of_the_release_answer` | `0` | `backend/**` 下**读**这个答案的处数：模块外的调用点，加上模块内「值被消费」的调用点 —— 唯一的那个模块内调用点把答案丢掉了，所以是 `0` 而不是 `1`。三个外来 `release()`（`asyncio.Lock`、PG advisory hold、网关 gate）按**接收者是否绑定到租约模块**排除，不按属性名。测试读它，但测试不是决定者 —— 口径因此是 `backend/` |
| `release_collapses_the_two_non_answers` | `true` | `release` 的 `except` 返回的表达式，与「不是我们的」那一档返回的是不是**同一个值**。**加一个读者**会让上面那条红，**把它分开**会让这条红 —— 两个方向各有一个见证 |

<!-- claim-table:end -->

## 8. 这份文档怎么防止腐烂

§6、§6.1、§7 与 §8 末尾的表都由成对的 HTML 注释标记括起来（一类叫 `anchor-table`，一类叫 `anchor-absence`；标记本身只以名字在这里出现，不逐字复述，否则它会被自己的解析器数一遍）。`tests/unit/scripts/test_docs_anchors.py` 会：

1. 抽出所有被括起来的表，逐行取 `file:line` 与 token，断言 **token 逐字出现在那一行**；
2. 断言标记成对、且表里有足够的行（防静默截断 —— 丢一个结束标记，被它包住的整段会静默退出检查）；
3. 对另一类表反过来断言某 token **不出现**在某个文件或某一行 —— 用来钉住「声明 ≠ 执行」这类否定事实。

<!-- anchor-absence:begin -->

| 位置 | 不该出现的 token | 为什么 |
| --- | --- | --- |
| `Dockerfile` | `--workers` | `docs/deployment.md:421` 声明了 `--workers 4`，镜像里没有 ⇒ 声明 ≠ 执行（§3） |
| `backend/api/routes/_wf_actions.py:252` | `_background_tasks` | ripple-retry 起了任务却没进注册表（对比 `:449`）⇒ §7 第一条后果的一半 |
| `backend/api/routes/workflow.py` | `start_lease` | 分层后 api 层仍无取租约处 ⇒ §7 的前提本身 |
| `backend/api/routes/_wf_application.py` | `start_lease` | 16 个端点实现都走 `_runner._run_graph_and_persist`，租约在那里取 |
| `backend/api/routes/_wf_runtime.py` | `start_lease` | resume / takeover 起的任务借的是 `_run_graph_and_persist` 的租约，本层不自己取 |
| `backend/api/routes/_wf_artifacts.py` | `start_lease` | 只读历史文件与 checkpoint 快照，不起任务 |
| `backend/api/routes/_wf_actions.py` | `start_lease` | 两条 retry 正在这里 —— 它们通过 `_runner._execution_lease` 取租约，所以这一行断言的是「这里没有**第二个实现**」，不是「这里没有租约」（§7） |
| `backend/api/routes/_wf_models.py` | `start_lease` | 纯 pydantic 模型，没有执行面 |
| `backend/services/cdp_session_lock.py` | `execution_leases` | 这里的 `release()`（`:310` 的 PG advisory hold、`:317` 的 `asyncio.Lock`）**不是**租约的 —— §7 那条读者判据必须按 import 解析接收者；按属性名匹配会把它们算成租约的读者，报出一个本模块没有的 `3` |
| `backend/tools/runtime/gateway.py` | `execution_leases` | 同上（`:198` 的 `gate.release()`）—— 三个外来 `release()` 里最容易被误收的一个 |

<!-- anchor-absence:end -->

这样处理的原因很直白：**文档里的行号会腐烂，而腐烂是静默的。** 把行号变成门禁之后，行号漂移会让 CI 红，而不是让下一个读文档的人照着错的行号去找代码。

同一条纪律在租约侧的先例是 `takeover_safety.py` 的穷举注册表（未知名抛错，而不是回落到一个安全默认值）；在接管侧的先例是 `test_the_only_way_into_the_publisher_is_a_gate`（从 `build_graph()` 的边钉住「前提本身」）。

**散文里的行号是第二档，它的上界要说清。** 上面三张表只覆盖被括起来的部分；散文里还有一批
`file:line`，它们没有 token 可比，只保证**解析得到、且在范围内**。这一档的实现在
`tests/unit/scripts/docs_citation_rule.py`，扫描范围（语料）与下界断言在
`tests/unit/scripts/test_docs_citations.py`：**全部自有 md**，口径是形状而不是目录清单 —— 路径分量里
没有点开头的那一份，所以 `docs/`、仓根与 `frontend/` 在内，票面与 vendored 的 skill 文档在外。
带路径的按仓根解析（含 `:A-B` 区间 —— **两端都查**），裸 `:N` 归属到
**同一节内最近一次出现的完整路径** —— 这是**推断**，不是保证（换个文件之后它会静默指错），
所以**新写的引用一律写全路径**。

**但「全都解析得到」还差一半：得先知道哪些 token 根本不是在引用。** 语料里有四个形状完全相同的
token —— 一个裸基名（`_wf_actions.py` 那一类，报错时给出它的完整路径）与三个主机加端口
（`localhost:8000`、`host.containers.internal:9223`、`postgres:15`）。例外表能把它们分开，代价是
下一个端口要再登记一次；所以判别式**从树里推**：一个不带斜杠的 token 算引用，当且仅当树里有文件
**叫这个名字**，或者树里有文件**是这个类型**（后缀）。两侧都有夹具：同一段文字放进一个「有这些文件名」
的合成树里，判决必须翻转。残差写在这里：既无斜杠、名字不在树里、后缀也不在树里出现的 token 会被跳过 ——
本仓的规范是引用一律写全路径，所以这条残差只覆盖**本来就违反**那段规范的文字。
（本节不复述语料的份数与引用处数：它们是那个测试文件里的下界断言，而复述一个**本表算不出来**的数，
正是本节开头批评过的那件事。上面三行之所以敢写，是因为有 `_CLAIMS` 替它们算。）

覆盖多少，以及第三档的欠账有多少，本身也是被重算的：

<!-- claim-table:begin -->

| 主张 | 值 | 怎么重算 |
| --- | --- | --- |
| `line_number_references_in_this_document` | `143` | 全文带路径的 `路径:行号` 与裸 `:行号` 的处数之和 |
| `line_numbers_pinned_by_marked_tables` | `73` | 标记表里第一格本身就是 `路径:行号` 的行数 |
| `bare_line_number_references_in_this_document` | `21` | 其中不带路径的处数 —— 只能被「节内归属」推断，是这一档已知的欠账 |

<!-- claim-table:end -->

★ 这三行是本文件**关于自己**的主张，而它们在这里才第一次被写出来，正因为**它们曾经是错的**：
上一版的开头写着「本文件里的每条 `file:line` 都由 `test_docs_anchors.py` 钉住」，而当时的真实覆盖
是 51/84；同一个 §7 里还引用着一个**不可能存在**的行号（3008，而那个文件只有 371 行），它的真实
位置是 §7 锚点表里的那一行。**机制的自述不会因为机制存在就变准** —— 自述也是承袭来的文字。

**这三个数会随每一片新增引用而变，这不是缺陷，而是它的用法。** S4 这一片往 §7 加了 13 处引用，
三个数当场就动了。本片重写 §7 的裁定段、又改了 §7 与 `docs/tool-runtime.md` 里的引用，它们**又**动了一次——每一次判据都在同一次运行里把这三行判红。**这里不复述它们今天的值**：上面那张表是唯一的出处，而复述一个已经被人算过的数，正是本节开头批评的那件事：
自述数字只有在**有人替它算**的时候才是自述，否则它和上一版开头那句话是同一种东西。
