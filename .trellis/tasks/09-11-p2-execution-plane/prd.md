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
| **S1** | **执行租约的数据面**：owner identity（实例 id + 启动时刻）+ 租约记录（thread_id → owner / acquired_at / heartbeat_at / expires_at / state）+ `acquire` / `renew` / `release` / `expire_scan`。**只写不读** —— 今天的 `_background_tasks` 照旧决定一切，对外零行为变更 | 低-中 |
| **S2** | **状态推导改读租约**：`has_active_task` 由租约回答；`/status` `/list` 的 `orphan` 语义从"本进程没有任务"变成"**租约已过期**"。事实 15 的绊线按设计改形 | 中（改可观测语义） |
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

（待各切片追加：每片的改动表、实测推翻的假设、门禁数字、突变表、残留登记。）
