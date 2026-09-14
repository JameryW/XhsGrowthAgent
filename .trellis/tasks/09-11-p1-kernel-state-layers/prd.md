# P1a 实施 prd — Kernel 最小骨架 + State 三层拆分

设计权威来源：本任务 `info.md`（含 2026-09-13 拍板记录）+ `research/state-consumer-map.md` + `research/persistence-inventory.md`。此处只列验收导向的实施要求；字段归置全表、决策代价、选项分析不在本文件重复。

## 已定决策（不再开放）

D1 一刀切新 schema + 旧线程 hydration 透传（不重写存量 checkpoint；部署排空窗 + 回滚前停新 schema 在途线程）· D2 Artifact=LangGraph BaseStore（ns `("artifacts", thread_id, kind)`）+ ArtifactStore façade · D3 Event=新 workflow_events 表（PG，`is_pool_ready()` 内存回退，creator_agent 双后端模式）· D4 /status 保全文响应（hydration 收口）· D5 范围=ArtifactRef/ArtifactStore/EventStore/RuntimeState 矩阵/hydration 层五件。

## 实施要求（按切片）

**S1 减法与收口**
- 从 `XHSGrowthState` 删除 `messages`、`content_history` 声明及全部 init/读面残留（workflow.py:697/706、cli/main.py:87/96 等）。
- 新建 hydration 模块（建议 `backend/state/hydration.py`）：唯一入口聚合 /status(:980-1004)、`_snapshot_to_checkpoint`(:1131-1154)、recover、showcase、realtime 事件载荷（_runner.py:130-158）、history 文件六处读面；对 legacy 全量 blob 线程原样透传，对新线程按 refs 水合。前端 payload 形状不变（回归：既有 test_status/history 断言不改期望值）。

**S2 Event 外置**
- `workflow_events(thread_id, seq, ts, kind, payload)` + db/ 访问层（双后端）；kind：llm|tool|cost|error|human_wait|action。
- P0 的 ContextVar perf drain 落点（base.py performance_log 写入）改写到 EventStore；checkpoint 删除 `performance_log` 声明（新 run）；`agent_timeline` 与质量趋势读路径换源（经 hydration）；blogger_gate/_base.py 聚合点同步。

**S3 Artifact 主体**
- ArtifactStore façade + ArtifactRef（`artifact://kind/id` + content_hash + size + updated_at）。
- refs 化（一跳/终末）：viral_posts、user_viral_links、shooting_plan、optimization_analysis、ripple_comparison、analytics、copy_content、visual_plan、draft_content（正文；meta/摘要留驻）。
- 摘要化：content_versions→`versions_meta`（**保全序与 id 稳定，路由 routers.py:291/324/423 只读长度**；吸取 free-draft 排序教训）、blogger_notes→count+ids。
- 架构测试：每个路由函数对「ref'd state」与「全量水合 state」返回值恒等；hydration 往返等价（写→水合→与原正文逐字段等）。

**S4 硬骨头与等价性**
- brief_content.raw_text 外置（5 agent 消费点改经 store 水合）、trend_summary、ripple 大向量外置。
- **P0 契约等价测试**：publish_id 内容哈希自 artifact 计算与旧口径一致（或哈希定义随迁，双跑断言同值）；pause_reason/human_decision、dry-run 双检、质量门谓词行为不回归。
- legacy 线程 fixture：以旧 schema 键构造 checkpoint → /status、/history、recover、showcase 透传渲染不劣化。

## 红线与约束

- 只加/移 checkpoint 字段声明，不动 reducer 语义；不引入 RunContext/Task/ActionIntent（D5）。
- 不改前端；不改 /status 契约（D4）。
- 全量 `uv run pytest tests/unit tests/integration` 零新增失败；mypy strict 零错（本地核验加 `--python-version 3.12`，见项目记忆）；ruff 干净。
- uv.lock churn 永不入库；push 用免代理直连兜底。
- 先红后绿：每个行为迁移配回归测试；并发/顺序相关测试禁用时间戳判据。
- 体积基准：S 前后各跑一次母婴长任务模拟（可脚本化 ainvoke 序列），报告单 superstep 序列化字节数对比，写入任务 research/。

## 完成定义

S1–S4 全部合入 main（独立 PR），checkpoint 体积基准显著下降，旧线程四读面回归绿，spec 更新（workflow-state.md 记录三层模型与 hydration 契约）。
