# 为开发模式添加 SQLite 持久化 checkpoint

## Goal

当前 `compile_graph_dev()` 使用 `MemorySaver()` 作为 checkpoint，导致进程重启后所有工作流状态丢失。需要将开发模式也改为使用持久化存储（SQLite），避免开发调试时丢失工作流状态。

## What I already know

- `backend/graph/builder.py` 中 `compile_graph_dev()` 使用 `MemorySaver()`
- `compile_graph_prod()` 已使用 `AsyncPostgresSaver` 实现持久化
- `langgraph-checkpoint-sqlite` 已安装（版本 3.1.0），提供 `AsyncSqliteSaver` 和 `SqliteSaver`
- 项目使用 `pyproject.toml` 管理依赖
- 后端 API (`backend/api/routes/workflow.py`) 和 CLI (`backend/cli/main.py`) 都通过 `compile_graph_dev()` 获取 graph

## Assumptions (temporary)

- SQLite 文件可以放在项目根目录或 `data/` 目录下
- 开发模式不需要考虑多进程并发写入 SQLite
- 需要支持 `AsyncSqliteSaver` 以兼容现有的 async API

## Open Questions

1. SQLite 文件存放位置偏好？（项目根目录 vs `data/` 目录 vs 其他）
2. 是否需要支持同步 API 也使用 SQLite？（CLI 使用同步接口）
3. 是否需要迁移现有 MemorySaver 中的数据？（不可能，因为内存数据已丢失）

## Requirements

* `compile_graph_dev()` 改用 `AsyncSqliteSaver` 替代 `MemorySaver`
* SQLite 数据库文件自动创建，路径可配置（环境变量或默认值）
* 保持 `compile_graph_dev()` 的 API 签名不变（仍返回 `CompiledStateGraph`）
* CLI 和 API 启动时自动初始化 SQLite 表结构

## Acceptance Criteria

* [ ] 进程重启后，通过 `xhs-growth status <thread_id>` 仍能查询到之前的工作流状态
* [ ] 前端页面刷新后，工作流状态不丢失
* [ ] SQLite 文件在预期位置生成
* [ ] 开发模式启动时自动创建表结构（如果尚未创建）

## Definition of Done

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes

## Out of Scope

* 生产模式（Postgres）的改动
* 数据迁移（MemorySaver 到 SQLite）
* 多进程并发写入优化

## Technical Notes

- `AsyncSqliteSaver` 可以通过 `AsyncSqliteSaver.from_conn_string("sqlite:///path/to/db.sqlite")` 创建
- 需要在 `compile_graph_dev()` 中调用 `await checkpointer.setup()` 初始化表结构
- 由于 `compile_graph_dev()` 目前是纯同步函数，需要改为 async（或保持同步但使用 `asyncio.run()`）
- 参考 `compile_graph_prod()` 的 async 模式
