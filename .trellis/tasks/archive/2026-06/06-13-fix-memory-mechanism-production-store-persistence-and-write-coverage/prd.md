# fix: memory mechanism production store persistence and write coverage

## Goal

修复项目 memory 机制的三个问题，使长期记忆在生产环境真正可用：(1) 生产模式 store 不持久化；(2) MemoryManager 写入端只有 analyst 覆盖；(3) store_audience_preference 无真实调用者。

## What I already know

* `compile_graph_prod()` 第 321 行用 `InMemoryStore()` 作为 store，进程重启后记忆全部丢失
* `MemoryManager` 的写入方法只有 `analyst.py` 在调用（store_insight, store_strategy_note）
* `store_audience_preference` 只有测试调用，无生产调用者
* `CreativeMemory` 的 deposit 端有覆盖：brief_analyzer（deposit_style）、visual_designer（deposit_style）、content_strategist（deposit_play）、copywriter（deposit_material）、calibrator（calibrate）
* LangGraph 提供 `langgraph.store.postgres.PostgresStore`，用法：`PostgresStore.from_conn_string(DB_URI)` + `store.setup()`
* 已安装 `langgraph-checkpoint-postgres==3.1.0`、`psycopg-pool==3.3.1`
* `langgraph.store.postgres.PostgresStore` 已随 langgraph 1.2.1 安装可用（已验证 `from langgraph.store.postgres import PostgresStore` 成功）

## Assumptions (temporary)

* `langgraph.store.postgres.PostgresStore` 已随 langgraph 1.2.1 安装可用（基于 Context7 文档确认）
* 生产环境已有 PostgreSQL 实例（与 checkpoint 共用或独立）
* 不需要 SQLite store 方案（项目已有 Postgres 基础设施）

## Open Questions

(none — all resolved)

## Requirements

### P0: 生产模式 store 持久化

* `compile_graph_prod()` 中将 `InMemoryStore()` 替换为 `PostgresStore`
* 复用已有的 `db_uri` 参数，与 checkpoint 共用同一个 PostgreSQL 数据库
* 首次启动调用 `store.setup()` 初始化 schema
* 连接池与 checkpointer 共用或独立（取决于 API 兼容性）
* 如果 `PostgresStore` 不可用（ImportError），降级为 `InMemoryStore` + 日志警告

### P1: 补全 MemoryManager 写入覆盖（精简写入）

* `publisher.py` 已调用 `content_history.record()`，无需额外操作（已确认）
* `trend_scout.py`：侦察完成后写 1 条洞察（趋势信号摘要，不遍历逐条写入）
* `engagement.py`：互动完成后写 1 条受众偏好（互动模式摘要，不遍历逐条写入）

### P2: store_audience_preference 补充调用者

* 在 `engagement.py` 的 execute 中调用 `MemoryManager.store_audience_preference`
* 写入 1 条受众偏好摘要（评论关键词、情感倾向、常见问题）

## Acceptance Criteria

* [ ] `compile_graph_prod()` 使用 PostgresStore，非 InMemoryStore
* [ ] PostgresStore 不可用时降级为 InMemoryStore 并输出警告日志
* [ ] trend_scout 完成后写入洞察到 MemoryManager
* [ ] engagement 完成后写入受众偏好到 MemoryManager
* [ ] 现有 memory 单元测试全部通过
* [ ] 新增写入逻辑有对应单元测试
* [ ] `mypy backend` 无新增类型错误

## Definition of Done

* Tests added/updated
* Lint / typecheck green
* 行为变更在 CLAUDE.md 或相关 doc 中有记录（如适用）
* 降级路径有日志覆盖

## Out of Scope

* 将 InMemoryStore 的 asearch 语义搜索能力迁移到 PostgresStore（PostgresStore 的 search 实现可能不同，单独处理）
* SQLite store 方案
* 修改 CreativeMemory 的调用覆盖（已覆盖，无需修改）
* 前端 memory 展示 UI

## Technical Notes

* `langgraph.store.postgres.PostgresStore` 文档：`PostgresStore.from_conn_string(DB_URI)` + `store.setup()`
* `compile_graph_prod()` 位于 `backend/graph/builder.py:297`
* `MemoryManager` 位于 `backend/memory/store.py`
* `trend_scout` agent 位于 `backend/agents/trend_scout.py`
* `engagement` agent 位于 `backend/agents/engagement.py`
* Context7 文档确认 PostgresStore 用法：https://docs.langchain.com/oss/python/langgraph/add-memory
