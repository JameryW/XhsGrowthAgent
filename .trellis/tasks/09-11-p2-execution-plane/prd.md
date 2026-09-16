# P2b Execution Plane 独立 + durable scheduler — 侦察与切片计划

**状态**：规划中。本文件是本任务的 prd；实现按切片逐片交付，**每片独立 PR**。

依据：父任务 roadmap（`09-11-runtime-upgrade/prd.md` §P2b）；前置 P0 的 retry 收口**已交付**（见事实 14）。

## Background（票面原话）

> P2b `09-11-p2-execution-plane` — Execution Plane 独立 + durable scheduler（依赖 P0 的 retry 收口）
> `_background_tasks` process-local → lease-based durable task scheduler（acquire/heartbeat/commit/lease-expiry）；XHS Browser/CDP、Ripple、重型图片任务移到 worker；API 进程不持有真实执行生命周期。

## 现状侦察（2026-09-16，逐条对代码核实）

| # | 事实 | 位置 | 含义 |
|---|---|---|---|
| 1 | 执行注册表是**进程内字典**，而它的 docstring 自己承认重启孤儿**只被懒检测、没有启动扫描** | `api/routes/_runner.py:42` `_background_tasks: dict[str, asyncio.Task[Any]] = {}`；注释在 `:38-41`："In-process runtime cache only … Cleared on process restart — DB 'running' rows with no matching task here are restart orphans, **detected lazily in /list and /status (no startup scan)**" | 这不是"忘了做"，是**已被写下来的设计边界**。本片要动的是这个边界本身 |
| 2 | 决定可观测结果的进程内状态**有 4 份**，不止注册表 | `_runner.py:33` `_LAST_HISTORY_WRITE`、`:36` `_active_sync_executions`、`:42` `_background_tasks`、`:45` `_last_status` | 只换注册表不够；"进程内答案"是**一组**，要一起收口 |
| 3 | 状态推导把"**本进程**有没有活任务"当成判据 | `state/machine.py:34` `derive_status(snapshot, *, has_active_task: bool = True)`；`:129-135` priority 9 `next_nodes and not has_active_task` → `STALE`，priority 10 → `RUNNING` | **同一份 checkpoint，换一个进程读就是另一个状态。** 默认值是 `True`（调用方忘了传 = 声称在跑） |
| 4 | 孤儿检测已经是一个"进程内问答" | `api/routes/workflow.py:389-399` `_is_orphan_running`：`task = _background_tasks.get(thread_id); return task is None or task.done()`；消费者 `/status`（`:1101`）与 `/list`（`:2034`），对外字段 `orphan: true` | `orphan` 今天的定义是"**这个进程**没有它的任务"，不是"没人跑它" |
| 5 | **恢复通道已经存在，但是人工触发的** | `POST /recover/{thread_id}`（`workflow.py:1623`）；`retry_from_last_success` 用 `Command(goto=)`（`:475-491`）；`prev_phase` 等标量由 `state/hydration.py:213-214` 读出 | **检测有、自动接管没有。** 本片的缺口精确地在这里，而不是"恢复机制不存在" |
| 6 | ★ **生产其实是单进程**：`Dockerfile:81` 是 `CMD ["uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8889"]`（**无 `--workers`**），P0 的核实文档已写明 | `Dockerfile:81`；`research/p0-claims-verification.md:24`（"服务端为单进程 async uvicorn（Dockerfile:81 无 --workers；cli/main.py:183）"） | 见下方「★ 要重写的定性」 |
| 7 | 而 `docs/deployment.md` 写的是 **LB + API#1..#3 + `--workers 4` / gunicorn `-w 4`** 的多进程拓扑 | `docs/deployment.md:5-27`、`:415-432` | **声明 ≠ 执行**（本仓的老朋友）。多进程是**文档里的终态**，不是今天的事实 |
| 8 | 全仓**没有任何 lease / heartbeat / worker / job-queue 设施** | grep `lease\|heartbeat\|scheduler\|durable` 在 `backend/` 只命中 docstring 用词与 creator_stats 的循环（`tools/xhs/post_scheduler.py` 是"定时发帖"工具，语义无关） | `durable scheduler` 是**从零新建**，不是改造既有；本片没有"照着抄"的对象，所以 S1 必须先把形状做对 |
| 9 | 长任务里 **Chrome 本来就在 host，不在 API 进程内** | `docs/deployment.md:284-407`：`scripts/chrome-profiles.sh` 在 host 保活 Chrome（pidfile + flock + reap），容器经 `host.containers.internal:<port>` 连 CDP；`get_account_cdp_endpoint` 负责解析 host | "把 XHS Browser 移到 worker"**不是**移 Chrome —— 要移的是 **API 进程里的 CDP 客户端会话**（`services/xhs_*` 的调用侧）。这条会改变 S4 的论证 |
| 10 | 存储层是 **Postgres-only**，回退模式**不统一** | `db/pool.py:55` `is_pool_ready()`；`db/workflow_events.py:62-71` 有 `_mem_events` + `_reset_memory_store()` 的**模块内回退**先例；而 **`db/workflows.py` 全文 0 处 `is_pool_ready`** —— 守卫被推到调用方（`_runner._db_upsert:71-74`） | 租约表放哪、无 DB 时语义是什么，**必须显式决定**（见待决 2）。"忘了守卫就 raise"这个形状不能再复制一次 |
| 11 | SQLite **只是 checkpointer 的 dev 回退**，不是 app 表 | `graph/builder.py:432,612`（"Postgres 不可用时回退到 SQLite"）、`system.py:343` 报告 `mode: sqlite` | 不要把 SQLite 当成租约的第二存储 |
| 12 | 已有"durable 状态 + 进程内循环"的先例，但它**本身也是进程内的** | `api/app.py:1403` `creator_stats_scheduler = asyncio.create_task(...)`；持久化在 `db/creator_stats.py:215`（"Scheduler durable state … across restarts"）；关停 `:1424-1427` | 形状可以复用（**状态耐久 ≠ 执行唯一**）；多进程下它会各跑一份 —— 这正是本片要消灭的那类性质 |
| 13 | 其余 fire-and-forget 执行点（同在 API 进程内，但**不持有生命周期**） | `agents/analyst.py:287`（`noqa: RUF006`）· `api/routes/agent.py:89` `_prewarm_tasks` · `public_showcase.py:755,841` · `free.py:915` · `content_strategist.py:597` · `memory/calibrator.py:73` · `services/ripple_service.py:264`（健康检查循环）· `services/creator_stats/client.py:738` · FastAPI `BackgroundTasks`（`accounts.py:357`） | "API 进程不持有执行生命周期"要**逐点分类**（真任务 / 进程内循环 / 纯 cache 预热 / HTTP 响应后收尾），不是一刀切 |
| 14 | 本任务的前置（P0 retry 收口）**已交付** | `backend/graph/error_handling.py`：`RETRY_POLICIES` **穷举注册表** + `get_retry_policy()` 对未知节点 `raise KeyError`；注释明写「统一 retry 引擎属 P1/P2」 | 依赖满足；**且那句注释把"统一 retry 引擎"划给了 P1/P2** —— 本片要小心不要顺手把它做成第四件事 |
| 15 | 既有绊线（改语义会红的测试） | `tests/unit/api/test_orphan_detection.py`(4) · `test_workflow_stale.py`(7) · `test_recover.py`(11) · `test_publish_retry.py`(8) · `test_runner_phase_sync.py`(4)；集成 `test_api_routes.py` / `test_sse_eventbus.py` / `test_workflow_bug_fixes.py` | S2 会按设计改这些断言（**改形不删**，S4a orphan 绊线同一纪律） |

### ★ 要重写的定性：票面第 3 条的真实动机不是"多进程"

票面写"API 进程不持有真实执行生命周期"。按实测（事实 6、7），这句话的**理由需要重写**：

- **今天不跑多进程**（`Dockerfile:81` 无 `--workers`），所以这**不是**一个当前正在发生的正确性缺陷；
- 它真实、当下就在发生的问题是：**重启/部署会杀死在飞的工作，而孤儿只被检测、不被接管**（事实 1、4、5）。一次 `deploy.sh` 之后，DB 里 `status="running"` 的 workflow 会以 `stale` + `orphan:true` 挂在列表里等人去点 `/recover`；
- 剩下的价值是**为多进程铺路**（让状态判定与执行所有权不再依赖"哪个进程碰巧接住了它"）。

**所以本片的表述应该是**：把"谁在跑这件事"从**进程内的事实**变成**可陈述、可过期、可交接的事实**（lease），并让**重启可恢复**成为默认行为；多进程的可扩展性是它的后果，不是它的前提。
这样切还有一个实际好处：**判据可测** —— `kill -9` 后重启能否接管，比"多开一个 worker 还能不能跑对"好验得多。

## 切片计划（每片独立 PR）

判据（按**依赖强度**排序，而不是按票面的书写顺序）：先让"谁在跑"成为**可陈述的事实**（数据面，零行为变更），再改**读者**（状态推导），最后才动**行为**（自动接管）与**进程边界**。

| 切片 | 内容 | 风险 |
|---|---|---|
| **S1** ✅ [#614] | **执行租约的数据面**：owner identity（实例 id + 启动时刻）+ 租约记录（thread_id → owner / acquired_at / heartbeat_at / expires_at / state）+ `acquire` / `renew` / `release` / `expire_scan`。**只写不读** —— 今天的 `_background_tasks` 照旧决定一切，对外零行为变更 | 低-中 |
| **S2** ✅ [#615] | **状态推导改读租约**：`has_active_task` 由租约回答；`/status` `/list` 的 `orphan` 语义从"本进程没有任务"变成"**租约已过期**"。事实 15 的绊线按设计改形 | 中（改可观测语义） |
| **S3** | **过期租约的接管**：启动扫描 + 周期扫描，从 checkpoint 续跑。**接管只能恢复执行循环、不能替人做决定**（见待决 3） | 高（会重跑工作） |
| **S4** | **长任务移出 API 进程**：按事实 9、13 逐点分类，把 CDP 会话与重型任务挪出编排进程。**凭证据开闸**（裁定 1）—— 无证据则降级为文档 + 分类清单 | 高 |
| **S5** | **契约的表述**：`docs/execution-plane.md` —— 租约的**保证与非保证**、单进程现实 vs 文档拓扑、无 DB 时的语义、接管的安全边界、逐点分类清单 | 小 |

**本任务明确不做**（父任务克制原则 + 各自归属）：

- 不新增 PlannerAgent / MemoryAgent / RetryAgent 之类的 LLM Agent（父任务 §克制原则）。
- **不重写 retry 引擎** —— P0 已收口，重试归 Gateway；事实 14 的注释把"统一 retry 引擎"划给 P1/P2，本片只做执行所有权，不顺手做第四件事。
- 不动 LangGraph checkpoint 语义（P1a 的红线：新 run 新 schema、存量不重写）。
- **不改 `WorkflowStatus` 枚举**（前端只认已知状态，P0-W5 已立此规）。

## 裁定（2026-09-16 用户拍板；下面保留选项与理由，作为决策记录）

**待决 1 —— 本轮是否引入独立 worker 进程？（决定 S4 的形状）**

| 选项 | 收益 | 代价 |
|---|---|---|
| A 只做租约 + 接管，执行仍在同进程 | 重启可恢复；状态不再依赖进程内答案；为将来铺路 | 不解决"长任务占住 API 进程" |
| B 本任务内引入独立 worker 进程/容器（同镜像不同入口） | 完全对齐票面第 3 条 | 新增执行通道 + 部署形态变更；而 Chrome 本来就在 host（事实 9），收益需重新论证 |
| C 分阶段：S1–S3 走 A，S4 凭证据再定 | 先拿"重启可恢复"这个**可测**收益；进程边界的决定推迟到有证据时 | S4 可能降级为文档 + 分类清单 |

**裁定 1：选 C（分阶段）—— 用户 2026-09-16 拍板。** 理由与 P1a 的裁定同源（"避免无消费方的提前抽象"）：进程外执行要等服务恢复的证据，不是先建通道。这条也顺带把票面第 3 条从"必须建 worker"改成**"必须消灭进程内所有权"** —— 后者才是根因。

**因此 S4 是"凭证据开闸"的切片**：S1–S3 交付后，若仍拿不到"长任务占住编排进程"的可观测证据，S4 降级为**文档 + 逐点分类清单**（事实 9、13 的产出），进程外执行移交下一任务。S1–S3 的收益不依赖 S4 —— "重启可自动接管"本身就可独立验收。

**待决 2 —— 没有 DB（`is_pool_ready()` 为假）时，租约的语义是什么？**

| 选项 | 后果 |
|---|---|
| A **降级为今天的进程内行为，但显式声明**（单一读者回答 `durability: none`） | 本地 dev / 测试不受影响；"无法承诺耐久"可观测 |
| B fail-closed，拒绝 acquire | 本机无 PG 的开发与全部测试直接不可用 |

**裁定 2：选 A（显式降级 + 可观测）—— 用户 2026-09-16 拍板。** 并且必须是**单一读者**（不是散落各处的 `try/except`）。理由：租约是**耐久性**承诺，没有存储时确实无法承诺 —— 但"无法承诺"不等于"不许跑"，而**静默降级**才是本仓最忌讳的（P1c `auth_scope` 的教训）。
附带子决定（本片自行落定，登记于此）：租约**新建** `backend/db/execution_leases.py`，照 `workflow_events.py` 的**模块内回退**先例，而**不是**放进 `db/workflows.py`（事实 10：那里 0 处守卫、把守卫推给调用方；不能再复制一次「忘了守卫就 raise」）。

**待决 3 —— 自动接管的安全边界怎么划？（我不建议把这条交给"默认值"，但要写进票面）**

现状：`/recover` 的 `retry_from_last_success` 会**重跑一个节点及其全部下游**。人工触发时这可以接受（人看着）；**自动触发时不可以** —— 一个在发布路径上死掉的 workflow 被自动续跑，可能**重复发布**。

**裁定 3（本片自行裁定，未占用拍板 —— 与 P2a-S4b 的「默认拒绝」、P0-W4 的 `unknown` 对账是同一条纪律，故按纪律落定并在此登记）**：自动接管**只能恢复执行循环，不能替人做决定**。具体：仅当断点之后待跑的都是无副作用节点时自动续跑；若断点落在发布/授权路径上 → 置为需要人决策的状态并**发事件**，绝不自动重跑副作用节点。与 P2a-S4b 的"默认拒绝"、P0-W4 的 `unknown` 对账是同一条纪律。

## 红线

- **不得让 `/status` `/list` 对同一份 checkpoint 在不同进程给出不同答案** —— 这是本片要消灭的性质，不能反向引入。
- **不得自动重跑任何已产生副作用的节点**（发布、登录、上传）。
- **不得改动既有 `WorkflowStatus` 枚举**（前端只认已知状态）。
- **租约失效不得导致两份执行同时写同一 thread 的 checkpoint**（P0-W1 的 async 串扰是本片最不能重演的事故）。
- 租约的 `heartbeat` 不得成为"又一个没人读的键"（P1c `auth_scope` / P2a S5a 的同一条教训）：**写的键必须有读者，读者必须可测**。

## 验收

- 每个切片独立 PR、四道门禁全绿（pytest / ruff / mypy / P1b 基线 / tool gate）＋ 突变自检，与 P2a 同一口径。
- 本任务的最终验收（三条，都可测）：
  1. `kill -9` API 进程后重启，在飞的 workflow 能被**自动接管**并从安全边界继续；
  2. `/status` 的 `running` / `stale` 判定与"哪个进程"无关；
  3. 无 PG 环境下行为与今天**一致**，且降级状态**可观测**。

## 执行记录

### S1 —— 执行租约的数据面（分支 `feat/p2b-s1-execution-lease`，commit `761c2865`，PR [#614](https://github.com/JameryW/XhsGrowthAgent/pull/614)）

**定性**：把「谁在跑这个 thread」从**进程内的事实**变成**可陈述、可过期、可交接的事实**。S1 只建数据面并接上生产的**写入点**，**不接任何读者** —— 今天 `_background_tasks` 照旧决定一切，对外零行为变更。

**改动表**

| 文件 | 变更 | 内容 |
|---|---|---|
| `backend/db/execution_leases.py` | **+530（新）** | owner identity（`host:pid:rand` + 启动时刻）、租约记录、`acquire` / `renew` / `release` / `expire_scan` / `get_lease` / `list_leases` / `start_lease` / `end_lease` / `ensure_tables` / `durability`、`_reset_memory_store`。Postgres 优先、模块内回退（照 `db/workflow_events.py:62-71` 先例，**不进** `db/workflows.py` —— 事实 10：那里 0 处 `is_pool_ready`，守卫被推给调用方） |
| `backend/api/routes/_runner.py` | +17 | `:327-336` 在 `is_sync` 分叉后、`try` 之前 `await start_lease(thread_id)`；`:486-492` 在 `finally` 的 `_background_tasks.pop` 之后 `await end_lease(...)`。两处都在 `contextlib.suppress(Exception)` 内 —— 观测性租约不得成为新的失败点 |
| `backend/api/app.py` | +4 | `ensure_tables` 进 lifespan 的 `ensure_coros`（与 `ensure_evaluator_config()` 并列） |
| `tests/unit/db/test_execution_leases.py` | **+284（新，29 用例）** | 用 monkeypatch `_utcnow` 的**假时钟**，不睡真时间；`_reset_memory_store()` 由本文件 autouse fixture 负责（`tests/conftest.py` 没有全局钩子，也不该加） |
| `tests/unit/api/test_runner_lease_wiring.py` | **+104（新，2 用例）** | 证明接线真实且**只观测** |

**为什么 `cli/main.py` 不动**：`_run_graph_and_persist` **只被 `api/routes/*` 调用**（workflow 6 / review 2 / optimization 2 / blogger 1），CLI 不经过它（它是同步 CLI，走 `sync creator-stats`）。S1 的接线点因此天然只覆盖 API 进程。

**S1 把三条红线落成的可判定形状**（红线的解释权在本片，登记于此）

1. **「不得让同一份 checkpoint 在不同进程给出不同答案」** → **每一行租约自带 `ttl_seconds` 列，所有过期判定读行自身的预算**，而不是读取方的。否则同一行会对长 TTL 的读者「活着」、对短 TTL 的读者「死了」 —— 那正是本片要消灭的性质。
2. **「租约失效不得导致两份执行同时写同一 thread」** → 唯一实现处是 `_ACQUIRE_SQL` 的 `WHERE`：**只有「现任者心跳新鲜」时才拒绝 acquire**。S1 **忽略** `acquire` 的返回值（纯观测），S3 才拿它当门。
3. **「`heartbeat` 不得是没人读的键」** → `heartbeat_at` 的读者是 `expire_scan → is_stale`，两者在 S1 就都有真实调用者（`_acquire_in_memory` 调 `is_stale`；`expire_scan` 进 `__all__` 并被测试调用）；写入点是生产路径，由接线测试钉住。**红线 5 与「只写不读」的张力就是这样解的**：读者的**定义**在 S1 落地并可测，读者的**接线**在 S2/S3。

**被测试逼出来的两个真缺陷**（都是「测试抓出代码」，不是「测试写错了」）

| 症状 | 根因 | 修法 |
|---|---|---|
| `test_takes_over_a_silent_lease` 红 | `acquire` 用**新来者的 TTL** 判断现任是否已过期 | `ttl_seconds` 存进租约行；`_ACQUIRE_SQL` / `_EXPIRE_SQL` 只引用 `execution_leases.ttl_seconds`；补 `test_the_lease_carries_its_own_budget`、`test_renew_adopts_the_current_budget` |
| 接线测试读到 `RELEASED`（应为 `HELD`） | 内存回退的 `get_lease` **交出内部可变对象**，`end_lease` 随后把它改成 `RELEASED`；PG 路径每行新建对象 → **两后端语义不一致** | `_snapshot()`（`dataclasses.replace`）；`get_lease` / `list_leases` 一律返回快照；补 `test_reads_hand_back_a_snapshot` |

另有一处**自己发现**的过度设计：`expire_scan` 原用「先探测再标记」的绕法防重复上报，而「只上报一次」已由**状态迁移**（`held`→`expired`）＋ `is_stale` 只看 `HELD` 保证 → 改成直白的「先算名单、再统一置 `EXPIRED`」，补 `test_reports_an_expiry_once` 钉住。

**门禁（全部在本片最终代码上跑）**

| 门禁 | 结果 |
|---|---|
| `pytest -q`（全量） | **3314 passed, 3 skipped**（基线 3283 **+31** = 29 + 2 新用例，**逐条对上**） |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 509 files already formatted |
| `mypy backend --python-version 3.12` | Success: no issues found in **205** source files（+1） |
| `scripts/gates/tool_runtime_gate.py` | P1c-S5 tool runtime: OK |
| `context_compiler_baseline.py --compare --drift-pct 5` | drift within threshold: OK |

**突变自检：21 条，`killed=21 survived=0 timeouts=0 anchor_failures=0`，`restore=OK`**

harness 规矩沿用 S4b/S5b：**step 0** 在未改动树上跑全部具名击杀者（必须 0；本片 step 0 = **31 passed, exit=0**）；每条突变**从原文重新开始**且锚点必须唯一（不唯一记 `ANCHOR-FAIL`，**不得**记成 survived）；`run_killers` **原样回 pytest 退出码**（0 = 用例通过 = **存活**）；`TimeoutExpired` 映射成 99 单列，免得「超时」被读成「存活」。

| # | 突变 | 具名击杀者 | 判定证据 |
|---|---|---|---|
| M1 | `is_stale` 不看 state（已释放的租约也能过期） | `TestExpireScan`（`test_ignores_a_released_lease`） | `expire_scan() == ['t1'] != []` |
| M2 | 读交出存储对象而非快照 | `TestReads::test_reads_hand_back_a_snapshot` | 读到 `RELEASED`（应为 `HELD`） |
| M3 | `expire_scan` 只报告不置态 | `TestExpireScan`（`test_flips_only_the_silent_held_lease`） | state 仍 `HELD` |
| M4 | `end_lease` 从不停心跳 | `TestHeartbeatTask::test_end_stops_the_heartbeat_and_releases` | `wait_for(..., 5.0)` 的 `TimeoutError` |
| M5 | `release` 不看 owner | `TestRenewAndRelease::test_release_leaves_another_owners_lease_alone` | `release() is True`（应 `False`） |
| M6 | `renew` 不看 owner | `TestRenewAndRelease::test_renew_reports_false_once_the_lease_moved_on` | `renew() is True`（应 `False`） |
| M7 | `renew` 能复活已释放的租约 | `TestRenewAndRelease::test_a_released_lease_cannot_be_renewed_back_to_life` | `renew() is True`（应 `False`） |
| M8 | `acquire` 用**调用方**预算判现任 | `TestAcquire::test_takes_over_a_silent_lease` | `acquire() is False`（应 `True`） |
| M9 | `acquire` 无条件授予 | `TestAcquire::test_refuses_a_live_lease_from_another_owner` | `acquire() is True`（应 `False`） |
| M10 | `durability` 永远声称 durable | `TestDurabilityIsAReadableFact::test_none_without_postgres` | 得 `DURABLE`（应 `NONE`） |
| M11 | `renew` 不采纳当前预算 | `TestRenewAndRelease::test_renew_adopts_the_current_budget` | `ttl_seconds == 1.0`（应 `30.0`） |
| M12 | TTL 掉出策略包络 | `TestLeaseBudget::test_the_lease_budget_stays_inside_its_policy_envelope` | `30.0` 不在 `[60, 300]` |
| M12b | 心跳间隔不再由另两者推导 | `TestLeaseBudget::test_ttl_and_heartbeat_are_one_decision` | `assert 135.0 == 90.0` |
| M13 | `acquire` 接受空 thread_id | `TestAcquire::test_empty_thread_id_is_never_leased` | `acquire("") is True`（应 `False`） |
| M14 | `list_leases` 忽略 state 过滤 | `TestReads::test_list_orders_by_heartbeat_and_filters_by_state` | `['early','late'] != ['late']` |
| M15 | 租约被拒仍起心跳 | `TestHeartbeatTask::test_start_returns_none_when_refused` | 返回了 pending `Task`（应 `None`） |
| M16 | 实例 id 丢掉 pid | `TestLeaseBudget::test_instance_identity_names_the_process` | `'38960' not in 'JameryW:ac4c792c'` |
| M17 | 心跳不察觉租约已丢 | `TestHeartbeatTask::test_heartbeat_stops_when_the_lease_is_lost` | `wait_for(heartbeat, 5.0)` 的 `TimeoutError` |
| M18 | `renew` 不动 `heartbeat_at` | `TestRenewAndRelease::test_renew_moves_the_anchor_it_owns` | 锚点未 +5s |
| M19 | runner 从不上租约 | `test_runner_holds_the_lease_while_the_graph_runs` | "the runner never acquired a lease" |
| M20 | runner 不再容忍租约存储损坏 | `test_runner_still_runs_when_the_lease_store_fails` | `RuntimeError` 未被 `suppress` 吸收 |

**残留与诚实登记**

- **S1 是只写不读**：`acquire` 的返回值在生产被丢弃；`expire_scan` / `is_stale` / `list_leases` 在生产**暂无读者**（按计划 S2/S3 才接）。这不是缺口，是切片边界 —— 登记在此以免被读成「做了一半」。
- **★ 「pytest 下 `end_lease` 挂起」的确定性根因（已定根；推翻早前「环境 Heisenbug」的猜想）**：盘上的 `backend/db/execution_leases.py` 曾把 `end_lease` 里的 **`heartbeat.cancel()` 变成了 `pass`** —— 也就是**突变自检 harness 的一个突变体**。机制：单进程 harness 里 `pytest.main` 一旦挂住，逐条突变的 `finally` **永不执行**，突变体就留在盘上；下一次运行**又把它当成「原始版本」读进来**（自我污染）。`end_lease` 不 cancel → `gather` 等一个无限循环的 task → 永久挂起（在飞 **4m29s** 仍被 kill；`faulthandler` 显示 event loop 在 `windows_events._poll` 空转、**无 pending timer** = 在等一个永不被 set 的 Future）。判定依据：把 `cancel()` 改回后，同一文件 **27 passed / 0.91s**。⇒ 不是环境、不是时序 Heisenbug，是**树被污染**。
  harness 已补三条硬化（此后 21/21 的那一次即为其产物）：① **锚点前置检查** —— 脏树下**毫秒级**报 `PREFLIGHT-FAIL` 并 `return 3`，而不是花 20 分钟等超时；② **看门狗** —— 超时**先恢复源码**再 `os._exit(99)`，消息写独立日志文件（pytest 会占用 fd 1，`print` 会随硬退出一起丢失）；③ **收尾哈希核验** —— 打印 `restore=OK/FAIL`。
- **测试侧的独立改进**：测试里 `end_lease` 的 teardown **一律有界**（`wait_for(..., 5.0)`）。理由不止于杀突变：原来直接 `await end_lease(...)`，实现一旦忘记 `cancel`，**失败形态是永久挂死**而不是断言失败 —— 未来任何重构把 `end_lease` 弄坏，整套测试会挂死而非报错。M4/M17 的击杀形态即为此。
- `EVENT_KINDS` 仍无读者、`account_credentials` 仍无写入者 —— P2a 的既有残留，与本片无关。

### S2 —— 状态推导改读租约（分支 `feat/p2b-s2-status-reads-the-lease`，commit `b88897d3`，PR [#615](https://github.com/JameryW/XhsGrowthAgent/pull/615)）

**定性**：S1 让「谁在跑这个 thread」成为**可陈述的事实**；S2 让**第一个读者上线** —— 同一个问题不再取决于"是哪个进程在读"。`has_active_execution` = **租约 OR 本进程注册表**，喂给 `derive_status` 的站点改用它；孤儿判定从"**本进程**没有它的任务"变成"**没有人持有它**"。

**改动表**（实测：7 改 3 新，tracked +275/−61，新文件 433 行）

| 文件 | +/− | 内容 |
|---|---|---|
| `backend/db/execution_leases.py` | +32/−6 | 新读者 `thread_is_held(thread_id)`。**staleness 在这里自己算，不读 `state`** —— `expired` 的唯一写者是 `expire_scan`，而它在生产**没有调用者**，所以行能长期停在 `held`；"还能不能续"才是调用方真正的问题。模块 docstring 从"S1 只写不读"改写为"S2 起有读者"，并补第四条模块级不变量 |
| `backend/api/routes/_runner.py` | +50/−7 | 三个新函数：`process_has_active_task`（本进程注册表，**与 S2 前的内联表达式逐字等价**）、`_lease_is_held`（best-effort：**存储坏掉答"没被持有"**）、`has_active_execution`（租约 OR 本进程）。`:386` 的 `has_active` 改用它；S1 那句 "Nothing reads it yet … changes no answer" 已不成立，改写 |
| `backend/api/routes/workflow.py` | +33/−39 | 7 处喂 `derive_status` 的点与 `_is_orphan_running` 改读租约；**2 处并发守卫保持读本进程**（理由见下）。`_is_orphan_running` 由同步改 `async`，两个调用点补 `await` |
| `tests/conftest.py` | +15/−0 | 新增与 `_reset_workflow_event_store` 同型的 autouse fixture 重置租约内存回退。**S1 加不上**：只写不读时残留行不可见；S2 起一行残留会让下一个用例读到"在跑" |
| `tests/unit/db/test_execution_leases_reader.py` | **新 89 行 / 7 用例** | `thread_is_held` 的读者面（含"问它不会改变它下一次的答案"） |
| `tests/unit/api/test_status_reads_the_lease.py` | **新 199 行 / 13 用例** | 租约决定判定 / 本进程仍为自己作答 / 坏存储的退化方向 / 本进程第二份注册表 / 孤儿判定 |
| `tests/unit/api/test_serialization_guards_stay_local.py` | **新 145 行 / 2 用例** | 两个"要不要起任务"的守卫（**S2 自己造出的缺口**，见下） |
| `tests/unit/api/test_orphan_detection.py` | +84/−5 | 模块 docstring 改写；一条既有用例**加强**（补 `checkpoint_lost` 断言，不改断言值）；新增 live `/status` 的租约 A/B |
| `tests/unit/api/test_recover.py` | +39/−0 | 新增：外部租约使 thread 不可 recover |
| `tests/unit/api/test_runner_phase_sync.py` | +22/−4 | 一条绊线按设计改形（见下） |

**判据分类：为什么 7 处改、2 处不改**

侦察发现"本进程有没有活任务"这个判据在仓库里**被复制了 9 份**，而同模块内 `:1079`/`:1653` 两份**漏了 `_active_sync_executions`** —— 同一个问题两个答案，是既有缺陷。（下表行号一律是**交付后**的 `workflow.py`，即 merge 后 checkout 到的那些行。）

| # | 站点 | 它问的问题 | S2 之后 |
|---|---|---|---|
| 1 | `workflow.py:900` `/status` 活图分支 | 这个 thread 在跑吗 | **租约** |
| 2 | `workflow.py:1079` `/status` DB 兜底 `checkpoint_lost` | 同上 | **租约**（并修掉漏 sync 项） |
| 3 | `workflow.py:1353` `/resume` | 同上 | **租约** |
| 4 | `workflow.py:1653` `/resume` `checkpoint_lost` | 同上 | **租约**（并修掉漏 sync 项） |
| 5 | `workflow.py:1684` `/recover` 闸门 | 同上 | **租约** |
| 6 | `workflow.py:1902` `/stream` | 同上 | **租约** |
| 7 | `workflow.py:389` `_is_orphan_running` | 有没有人在跑它 | **租约**（定义从"本进程没有任务"→"没有人持有"） |
| 8 | `workflow.py:2456` brief-upload 守卫 | **本进程要不要再起一份任务** | 保持**本进程** |
| 9 | `workflow.py:2856` publish-retry 守卫 | 同上 | 保持**本进程** |

**为什么 8/9 不改**（两个方向都会错，于是选范围更窄的那个）

- 改成**纯租约读**：`start_lease` 是 best-effort，存储故障时会有"活任务却查不到租约" → 据此放行就**起第二份执行**（红线 4）。
- 改成**租约 OR 本进程**（即 `has_active_execution`）：能防上面那条，但会**在重启后误拦** —— 死进程的租约在 TTL 内仍算"可续"，于是用户刚点的"上传 brief 后续跑"会**静默失效**（返回 200，什么都没跑）。**"同一处境失败模式更差"也是不做的理由。**
- 两个方向都钉了测试（`test_serialization_guards_stay_local.py` 的两条）。这两条是**突变自检逼出来的**：M18/M19 首轮存活，说明注释里声明的性质当时一条断言都没有。

**★ 必须登记的代价：崩溃重启后的 TTL 窗口内 `/recover` 会拒绝恢复**

所有权判定是"还能不能续"，所以进程崩溃后租约**不会立刻**变成"没人持有"：`heartbeat_at` 停更，但 `state` 仍是 `HELD`，直到 `heartbeat_at + LEASE_TTL_SECONDS`（**90s**；心跳 30s 一拍 ⇒ 实际窗口落在 **60–90s**）。

- 这个代价是**故意**的：窗口内 `/recover` 认为"还有人在跑"而拒绝，正确处置是等窗口过去（或等 S3 的自动接管按证据收口）。
- 换来的是**红线 4**：不会因为读不到租约就在一份正在跑的 thread 上起第二份执行。
- 它是**可判定的**，不是"可能有点影响"：`/recover` 闸门读 `has_active_execution`，后者在 `is_stale` 为假时为真；静态形态由 `test_a_foreign_lease_makes_the_thread_non_recoverable` 钉住（外部租约存在时确实拒绝）。

**被 S2 照出来的既有缺陷（顺手修）**

| 症状 | 根因 | 修法 |
|---|---|---|
| `/status` 与 `/resume` 的 `checkpoint_lost` 在"同步执行体在跑"时会误报 | 两份内联表达式**漏了 `_active_sync_executions`** —— `:900`/`:1353` 有，`:1079`/`:1653` 没有 | 四处统一到 `has_active_execution`，并把 sync 项写进 `process_has_active_task`，由 `test_a_sync_execution_counts_without_any_lease` 钉住 |

**绊线改形（改形不删）**

`test_runner_phase_sync.py::test_phase_falls_back_to_result_when_snapshot_has_no_phase` 断言 `row.status == STALE`，S2 后变 `running`。判为**旧实现痕迹**而非"行为变差"，三条证据：

1. 该用例注释自述前提是 `"next=['trend_scout'], no active task -> derive_status returns STALE"` —— 断言建立在"没有活任务"上，而 S2 之后 runner **在运行期间自己持有租约**，前提不再成立。
2. 它真正要钉的性质是"snapshot 没有 phase 时回退到 `result.phase`"与"非终态不写 history 文件"。后者改成 `assert row.status not in ("completed","error","cancelled")` —— **断言意图而不是字面值**。
3. 反过来看，`STALE` 那个值编码的正是**缺陷**：`_run_graph_and_persist` 正在跑这个 thread，但只有 `/start` 的 `async_mode` 分支会注册 `_background_tasks`，`async_mode=False` 的前台分支（同一个 `source="start"`）对 `has_active_task` **完全不可见** → 它给一份**自己正在执行的** thread 写 `stale`。

新断言另加一条更强的：`assert not runner_module.process_has_active_task(thread_id)` —— 证明这个 `RUNNING` **只可能来自租约**（本进程两个注册表都空），而不是巧合。

**门禁（全部在本片最终代码上跑）**

| 门禁 | 结果 |
|---|---|
| `pytest -q`（全量） | **3338 passed, 3 skipped**（基线 3314 **+24** = 7+13+2 新文件 + `orphan_detection` +1 + `recover` +1，**逐条对上**） |
| `ruff check .` | All checks passed |
| `ruff format --check .` | **512 files** already formatted（+3 新文件） |
| `mypy backend --python-version 3.12` | Success: no issues found in **205** source files |
| `scripts/gates/tool_runtime_gate.py` | P1c-S5 tool runtime: OK |
| `context_compiler_baseline.py --compare --drift-pct 5` | drift within threshold: OK |

**突变自检：20 条，`killed=20 survived=0 timeouts=0 anchor_failures=0`，`restore=OK`**

harness 沿用 S1 三条硬化（锚点前置检查 / 看门狗先恢复源码 / 收尾哈希核验）。**首轮不是全绿**：`M06 / M09 / M15 / M16 / M17` 五条存活 —— 逐条判为**真覆盖缺口**（都改变可观测行为，不是等价突变），于是补读者后重跑至 20/20。

| # | 突变 | 具名击杀者 | 判定证据（实测） |
|---|---|---|---|
| M01 | 空 thread_id 也算被持有 | `TestThreadIsHeld::test_an_empty_thread_id_is_not_held` | `assert True is False` |
| M02 | 查不到租约时答"被持有" | `…::test_no_lease_is_not_held` | `assert True is False` |
| M03 | `HELD` ↔ `RELEASED` 取反 | `…::test_a_held_lease_is_held` | `assert False is True` |
| M04 | 去掉 staleness 项 | `…::test_a_silent_lease_is_not_held` | state 仍 `HELD`，但 reader 得 `True` |
| M05 | staleness 拿行自己的心跳当"现在" | 同上 | 同上（永远新鲜） |
| M06 | 存储坏掉时答"被持有" | `test_a_broken_lease_read_answers_not_held` | `assert True is False` ＋ 日志留下 `lease store down` |
| M07 | 租约答复**取代**本进程 OR | `…::test_a_local_task_is_active_even_with_no_lease` | `assert False is True` |
| M08 | `done()` 取反 | 同上 | `assert False is True` |
| M09 | 去掉 sync 注册表项 | `TestLocalRegistriesStillCount::…` | `process_has_active_task('t1')` 为 `False` |
| M10 | `_runner` 状态接线退回本进程 | `test_phase_falls_back_to_result_when_snapshot_has_no_phase` | `- running / + stale` |
| M11 | 孤儿判定恒真 | `TestOrphanDetection::test_a_foreign_live_lease_is_not_an_orphan` | `assert True is False` |
| M12 | 孤儿判定不看 DB status | `…::test_a_row_that_is_not_running_is_never_an_orphan` | `assert True is False` |
| M13 | `/list` 丢弃 orphan 结论 | `test_list_running_row_no_task_marks_orphan` | `FAILED … AssertionError` |
| M14 | `/status` 兜底丢弃 orphan 结论 | `test_status_running_no_task_orphan_stale` | 同上 |
| M15 | `/status` 兜底假定"有人在跑" | 同上 | 同上（由本片新增的 `checkpoint_lost` 断言击杀） |
| M16 | `/status` 活图分支退回本进程 | `TestStatusLiveBranchReadsTheLease::test_a_foreign_lease_flips_stale_to_running` | `FAILED … AssertionError` |
| M17 | `/recover` 闸门退回本进程 | `test_recover.py::test_a_foreign_lease_makes_the_thread_non_recoverable` | 同上 |
| M18 | brief-upload 守卫改读**纯租约** | `…::test_brief_upload_does_not_resume_on_a_local_task_without_a_lease` | 同上 |
| M19 | brief-upload 守卫改读**所有权答案** | `…::test_brief_upload_still_resumes_past_a_foreign_lease` | 同上 |
| M20 | publish-retry 守卫改读纯租约 | `test_publish_retry.py::test_rejects_when_active` | 同上 |

harness 自身的一处观察：M13–M20 的 `tail` 最后 8 行被 `StarletteDeprecationWarning` 占满，证据行只剩最后那行 `FAILED …`；下次让 killer 带 `--tb=line -p no:warnings` 更省事。

**残留与诚实登记**

- **★ 3 处站点只有结构证据，没有行为区分测试**：`workflow.py:1353`（`/resume` 的 `derived`）、`:1653`（`/resume` 的 `checkpoint_lost`）、`:1902`（`/stream` 的 `derived`）。它们与已钉住的站点是**同一行表达式**（`grep -n "has_active_execution" backend/api/routes/workflow.py` 可一次性列出）。性质：
  - `:1653` / `:1902` 是**只读字段**（写进响应体，不决定任何执行）；
  - `:1353` 只决定 `/resume` 采用**哪种恢复形态**（`can_retry_error or can_resume_stale` 的两条分支**都会**起 resume），不是执行闸门。
  结论：这是**声明的**缺口，不是测出来的缺口（有意的取舍：`/resume` 与 `/stream` 的路由测试成本高于其风险）。若要补，一条 `/resume` 路由测试可同时覆盖 `:1353` 与 `:1653`。
- **单进程部署假设**：事实 6（`Dockerfile:81` 无 `--workers`）。上面"8/9 守卫不改"的取舍、以及"存储坏掉答 not held"的方向，都建立在这个前提上。多进程拓扑（`docs/deployment.md` 里的终态）下需要重新论证 —— 那时 8/9 应当改读**租约 OR 本进程**，而 `_lease_is_held` 的失败方向要再讨论。
- **`owner_id` 目前不参与读取判定**：`thread_is_held` 只问"有没有一个活着的主人"，不问"是不是我"。这是有意的 —— 读取方要的正是"不管是谁"；`owner_id` 的消费者是 `acquire` / `renew` / `release` 的互斥。将来若需要"是不是**我**在跑"（例如 S3 的接管要避免抢自己的租约），需要新读者，不要改这个的语义。
- **`expire_scan` 仍无生产调用者**：S2 不引入它 —— 读者自己算 staleness 正是为了不依赖它。它仍然是 S3（接管）的组件。
