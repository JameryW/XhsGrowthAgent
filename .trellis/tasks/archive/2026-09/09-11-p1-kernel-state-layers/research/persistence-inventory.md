# P1a 勘察 B：持久化基建盘点（checkpointer / store / db / 迁移面）

（2026-09-13 Explore 子代理产出。所有 file:line 基于合并 P0 后的 main。）

## 1. Checkpointer

- `backend/graph/builder.py`：`compile_graph_dev()` / `compile_graph_prod()` 共用同一 `build_graph()`。
  - Dev（builder.py:394-475）：`AsyncSqliteSaver`（aiosqlite，`XHS_SQLITE_PATH`，默认 `.xhs/checkpoints.sqlite`，builder.py:391），ImportError 回落 `MemorySaver`（:453-459）。
  - Prod（builder.py:505-579）：`AsyncPostgresSaver` + 独立 `AsyncConnectionPool(min=2,max=10,autocommit)`（:540-546），由 `POSTGRES_URI` 选择（app.py:1207,1268），任何异常回落 dev/SQLite（app.py:1282-1296）。
- 序列化：compile 从不传 `serde=`（:461-470,563-567）→ LangGraph 默认 msgpack + `JsonPlusSerializer`。**无 checkpoint 迁移/修剪/TTL**——checkpoints 无界累积（仅 creator_agent 的 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 增量迁移 db/workflows.py:119-137 与风险门时间戳清理 app.py:153-217）。

## 2. LangGraph Store（BaseStore）

- 与 checkpointer 对称：dev `InMemoryStore(index=...)`，设 `XHS_POSTGRES_URI` 时 `AsyncPostgresStore`（pool 1-5）（builder.py:408-438）；prod `AsyncPostgresStore`（pool 2-10）（:548-559）。
- **以关键字参数 `*, store: BaseStore` 注入节点**（LangGraph runtime injection）——nodes/publisher.py:15、base.py:318 等。**Artifact 读写的天然入口。**
- 在用命名空间：
  - `("publish","idempotency")`——P0-W4 幂等记录（publisher.py:49,95-118,137,152）。
  - `("ripple", thread_id)` key=`"result"`——后台预测结果（content_strategist.py:446,457；读 ripple_finalize:56）。
  - Memory ns（memory/store.py:43-60）：`("accounts",acct)` + content_history/audience_preferences/performance_insights/strategy_notes。
  - `("accounts",acct,"free_drafts")`——free 模式草稿含 image_paths（free.py:128-130）。

## 3. DB 层（backend/db/）

- 共享池 db/pool.py（2-10，`POSTGRES_URI`），**独立于** checkpointer 池。
- `workflows` 元数据表：thread_id PK + status/phase/account/showcase（全 TEXT 标量，无 blob）（workflows.py:72-97）。
- `creator_agent` 7 表：每表 `payload_json TEXT`（**非原生 JSONB**），pydantic 校验；内存/PG 双后端（`is_pool_ready()` 分支 creator_agent.py:508-515、`_mem_*` :51-60）；`payload_json::jsonb->>` 过滤（:814）。**现成的"类型化对象表 + 双后端"先例**——Event/Artifact 表可复制此模式。
- 其余表：creative_memory / quality_evaluations / evaluator_config / accounts / console_users / public_telemetry / creator_stats / system_config。**除 creator_agent payload 外无通用 artifact/blob 表。**
- PG parity harness（test_creator_agent_backend_parity.py）：`XHS_PG_PARITY_URI` 单独变量（:42），建/删随机 scratch DB、掩码 uuid/时间戳、双后端比 trace；conftest 弹掉 POSTGRES_URI/REDIS_URI（:25-26）→ 默认套件内存后端。

## 4. 文件/Artifact 先例

- PDF brief（workflow.py:2287-2416）：**只提文字**（pdfplumber + LLM 兜底）注入 brief，文件字节不持久。
- 图片：`visual_plan.image_paths`/`generated_images` 为**文件系统路径字符串**入 state（publisher.py:107, free.py:221）；text_cover 写盘 output_dir（text_cover.py:69-72）。无 services/artifacts/ 模块。
- 完成态转储（_runner.py:271-291）：`XHS_REGISTRY_PATH/history/{thread_id}.json` **整份 state_values JSON**（问题同构：全量落盘）。

## 5. 图构造变体（typed state 改动波及面）

- 一个 `build_graph()`/`XHSGrowthState`；两入口 compile_dev/compile_prod。prod app.py:1268；dev CLI 短生命周期（cli/main.py:267,359）。
- **free.py 不编译图**：以 `cast` 手搓最小 XHSGrowthState 直调 agent（`_build_eval_state:178`、`_build_publish_state:200`）。→ RuntimeState 改动波及：schema.py + builder.build_graph + free.py 两个合成器；**无第二套 schema 需平行维护**。

## 6. 旧 checkpoint 兼容面（迁移风险清单）

- `_get_as_node` 读 `values.get("_last_node","orchestrator")`（_runner.py:244-256）；`_get_state_update_node_without_advancing` 扫 ("current_agent","_last_node")（workflow.py:121-133）。
- engagement 残留：routers 容忍 legacy ENGAGING→terminal（routers.py:46,59）；`engagement_actions/engagement_error` 因 checkpoint/API 兼容保留（schema.py:72,135）；removed "engagement"→COMPLETED 映射（workflow.py:216）。
- 通用键枚举：`aupdate_state` 局部 dict 遍布（workflow.py:330,759,1283）；reducer `merge_dict={**l,**r}/append_list/replace`（reducers.py:6-18）；**/status 与 `_snapshot_to_checkpoint` 硬编码 ~30 个 `values.get(...)`**（workflow.py:1040-1066,1124-1154）——每个被移字段都要在这里 + _runner.py:130-158 事件载荷构造处同步改。

## 7. 无 checkpoint 的恢复路径（受移动影响者）

- `derive_status` 只依赖标量 status/phase（state/machine.py；workflow.py:857-873）——**移动大字段安全**。
- `checkpoint_lost` 回退：无活跃 checkpoint 时用 `workflows` DB 行派生 status（workflow.py:1069-1119），`checkpoint_lost=True/orphan=True` 标记——安全。
- 但 history 文件路径（workflow.py:1040-1066 `_load_history_file`）与 `_snapshot_to_checkpoint` **从全量 blob 重建大字段**；recover（:1593-1754）、Showcase（public_showcase.py checkpoint 缓存）同理。→ Artifact/Event 外置后，这些点必须按 thread_id **rejoin 新存储**，否则老线程详情断供。

## 关键结论（对方案的约束）

1. Store 注入通路与 `is_pool_ready()` 双后端模式是现成地基：Artifact 走 BaseStore、Event 走 creator_agent 式类型化表（含内存回退），都不引入新基建。
2. 真正工作量不在"写出去"而在"读回来"：/status、/history、recover、showcase、history 文件、realtime 事件共 6 个消费面各自硬编码全量键，必须集中成一个 **state hydration 层**再切引用，否则每处各改各的必漏。
3. 无 checkpoint GC 是存量债务：三层拆分后 RuntimeState 变小，但**旧线程 blob 仍全量存在**——迁移策略必须显式回答"旧线程怎么办"。
4. msgpack 默认序列化 + TypedDict total=False：**加字段安全、删字段（读方容忍缺失）也基本安全**；删的是 reducer 声明而非历史数据。
5. free.py 双合成器与 _status 的 30 键硬编码意味着"一个 hydration/aggregation 模块收口所有读面"是本任务最重要的结构性抓手。
