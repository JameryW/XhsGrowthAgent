# Hy Memory 集成（hy-memory 长期记忆引擎）

hy-memory 是腾讯混元的双系统认知记忆框架（PyPI `hy-memory==2.0.1`）。本仓库把它
作为**可选增强层**接入：启用后，账号偏好/画像与运营经验可以跨会话连续沉淀，供
Analyst 与 Content Strategist 召回进 prompt；不启用时整个集成是零成本 no-op。

## 1. 设计契约

| 契约 | 行为 |
|------|------|
| **默认关闭** | `HYMEMORY_ENABLED=false`（默认）。禁用时 bridge 是 no-op：不建 client、不发请求、不 import SDK |
| **永不炸调用方** | SDK 未安装（可选依赖）、client 构建失败、端点超时、返回结构异常 —— 全部降级为 warning + 空结果。记忆是增强，不是主链路 |
| **SDK 懒加载** | `hy_memory` 只在真正启用时才 import；`pip install -e .`（无 extra）的部署导入本模块零成本 |
| **账号隔离** | `account_id` → SDK `user_id`；`workspace_id` → `xhs/<account_id>`；`source="xhs_growth"` 做调用方隔离，与既有 LangGraph 记忆互不串味 |

## 2. 三层结构

```text
backend/memory/hy/
├── settings.py   HyMemorySettings（pydantic-settings，env 前缀 HYMEMORY_，默认全关）
├── bridge.py     HyMemoryBridge —— SDK 异步门面（懒加载 client、降级、错误归属）
└── recall.py     recall_hy_memory / format_hy_section —— P1b RetrievalResult 适配器
```

### 2.1 `HyMemoryBridge`

- **client 按事件循环分桶**（`_clients` / `_locks` / `_last_errors` 均以
  `id(asyncio.get_running_loop())` 为键）：SDK client 内部持 httpx/openai 连接池、
  `asyncio.Lock` 绑定构建时的 loop。生产只有一个 loop（uvicorn）；测试里
  pytest-asyncio 每测试一个 loop，跨 loop 复用会抛
  `bound to a different event loop`。
- **client 懒构建**在 `asyncio.to_thread` 里执行（Chroma 连接 + SQLite 初始化是
  阻塞 IO），并用每 loop 一把 `asyncio.Lock` 防并发首调用重复构建。构建失败按 loop
  缓存，同 loop 内不重试；换 loop（新进程/新测试）自动失效，允许重试一次。
- **错误归属**：`last_error()` 返回当前 loop 最近一次错误摘要（成功即清除）。
  `recall` 返回 `[]` 时，调用方靠它区分「没命中」与「刚发生了故障」——
  没有这个区分，外部记忆挂了会被误判成「记忆说没有」。
- **写入归一化**：`remember()` 对 SDK 返回值做 `isinstance` 守卫，结构异常时返回
  `None` 而不是把 `Any` 泄漏给调用方。

公开方法（全部 `async`、全部永不抛）：

| 方法 | 语义 |
|------|------|
| `recall(query, *, account_id, scene, limit)` | 归一化 dict 列表；chat 取 `memories.{profile,normal,proactive}`，working/coding 取 `facts`/`experiences` |
| `remember(data, *, account_id, scene, metadata, workspace_id, branch)` | 写入一条记忆，返回 SDK dict 或 `None` |
| `list_memories(*, account_id, limit, offset)` | 管理/调试面，取 `{"vdb": [...]}` |
| `forget(memory_id)` | 删除一条记忆 |
| `metrics(*, minutes)` | SDK 运行指标（请求量/时延/存储 ops） |
| `health()` | 可观测性快照（enabled/mode/client_ready/client_error/last_error/sdk_error），永远不抛 |
| `close()` | 关闭当前 loop 的 client |

进程级单例：`get_hy_memory_bridge(settings=None)` / `reset_hy_memory_bridge()`
（后者供测试隔离）。

### 2.2 `recall_hy_memory` —— P1b 适配器

把 bridge 结果包成 Context Compiler 管线的 `RetrievalResult`，使命中/降级信号
（D6'）在这条召回路径上同样可见：

| mode | 触发 | `error` 字段 |
|------|------|--------------|
| `EMPTY` | 功能关闭或确实没命中 | 空 |
| `HIT` | 拿到 ≥1 条记忆 | 空 |
| `DEGRADED` | SDK/client 层故障（端点超时、结构异常） | 错误摘要 |

`format_hy_section(results)` 渲染 L4 prompt 段。**降级不静默**：以一行
`【hy-memory 降级】hy_chat: <error>` 注明，让模型与运维都能看见外部记忆不在线。

与 `backend.context.retrieval.recall_namespaces` 的关系：**不混用**。既有管线只认
四个注册命名空间（`content_history` / `audience_preferences` /
`performance_insights` / `strategy_notes`，未知命名空间抛
`UnknownMemoryNamespaceError`）；hy-memory 是外部记忆引擎，有自己的开关与端点，
走独立适配器，两者在 agent 里以 `asyncio.gather` 并发。hy 使用的
`hy_chat`/`hy_working` 只是事件面标识，不进 `NAMESPACE_KEYS`。

## 3. Agent 接线

### Analyst（`backend/agents/analyst.py`）

- **召回**：chat（账号偏好与受众画像）+ working（内容运营经验/数据复盘）双场景，
  以 `asyncio.ensure_future` 包成并发 task，与主 gather（history + Ripple）
  并发执行。既有测试以「主 gather 恰好 2 个 awaitable」钉并发契约，故 hy 召回走
  task 而不是直接进 gather —— 主链路形状不变。
- **渲染**：`hy_context = format_hy_section([hy_chat, hy_working])` 注入 user_msg。
- **写入**：insights / recommendations 的 gather 里各带一次
  `_safe_remember_hy`（best-effort、永不抛），metadata 带 `kind=insight` /
  `kind=strategy_note`、`post_id`、`niche`，scene=`working`。

### Content Strategist（`backend/agents/content_strategist.py`）

- **召回**：chat 单场景（受众偏好/内容策略/历史经验），同样 `ensure_future`
  并发 task，主 gather 保持 4-awaitable 形状。
- **渲染**：hy 段拼在既有 `memory_context`（insights）之后、creative memory 之前。

## 4. 配置

安装可选 extra：

```bash
pip install -e ".[memory-hy]"   # 即 hy-memory==2.0.1
```

环境变量（前缀 `HYMEMORY_`，完整示例见 `.env.example`）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `HYMEMORY_ENABLED` | `false` | 总开关。false 时零 SDK 调用 |
| `HYMEMORY_MODE` | `lite` | `lite`（纯原始记忆+向量检索，零 LLM 调用）/ `pro`（LLM 抽取+冲突调和）/ `ultra`（+System 2 图式归纳，需图存储） |
| `HYMEMORY_LLM_API_KEY` / `HYMEMORY_LLM_BASE_URL` / `HYMEMORY_LLM_MODEL` | 空 | LLM 端点（pro/ultra 必需；任何 OpenAI 兼容服务）。lite 可留空 |
| `HYMEMORY_EMBEDDER_API_KEY` / `HYMEMORY_EMBEDDER_BASE_URL` / `HYMEMORY_EMBEDDER_MODEL` | 空 | Embedder 端点（向量检索必需，所有模式都要） |
| `HYMEMORY_EMBEDDING_DIMS` | `0` | 向量维度，`0` = 模型默认 |
| `HYMEMORY_DATA_DIR` | 空 | 数据目录（Chroma 持久化 + SQLite 元数据 + SDK 日志）；空 = SDK 默认 `~/.hy_memory`。容器部署应指向持久卷 |
| `HYMEMORY_DEFAULT_SCENE` | `chat` | 未显式指定 scene 时的落点 |
| `HYMEMORY_DEFAULT_LIMIT` | `5` | 单次 recall 默认条数（1–50） |
| `HYMEMORY_SOURCE` | `xhs_growth` | source 隔离标签（recall 时 `include_sources`） |

最小可用配置（lite 模式，只需 embedder）：

```bash
HYMEMORY_ENABLED=true
HYMEMORY_MODE=lite
HYMEMORY_EMBEDDER_BASE_URL=https://api.deepseek.com/v1
HYMEMORY_EMBEDDER_API_KEY=sk-...
HYMEMORY_EMBEDDER_MODEL=text-embedding-3-small
HYMEMORY_DATA_DIR=/data/hy_memory
```

## 5. 可观测性

- `bridge.health()` 返回快照 dict：`enabled` / `mode` / `default_scene` /
  `source` / `client_ready`；故障时带 `client_error`（构建失败原因）/
  `last_error`（运行时错误）/ `sdk_error`（SDK import 失败原因）。
- DEGRADED 会以 `【hy-memory 降级】` 行出现在 prompt 里，并打
  `xhs_growth.memory.hy` logger warning。
- `bridge.metrics()` 透传 SDK 指标（请求量/时延/存储 ops）。

## 6. 测试

| 文件 | 数量 | 覆盖 |
|------|------|------|
| `tests/unit/memory/test_hy_bridge.py` | 32 | FakeHyClient 假 SDK + `sys.modules` 注入：禁用 no-op、读写归一化、config 构建与 `MEMORY_DATA_DIR`、降级（SDK 缺失/异常/怪结构）、错误归属清除、跨事件循环、recall 适配器 HIT/EMPTY/DEGRADED、`format_hy_section`、settings env 前缀、单例 |
| `tests/unit/agents/test_hy_memory_wiring.py` | 7 | analyst 双场景召回注入 prompt、洞察/建议双写 metadata、禁用零 SDK 调用、SDK 故障不炸节点；strategist hy 段注入、禁用无段 |

全量套件对照基线（main 分支 14 个预先存在失败，与 hy 集成无关）零新增。

## 7. 已知限制

- **per-loop 分桶**：client/lock/错误缓存按事件循环键控。同一进程多 loop（如
  asyncio.run 嵌套）会各自建一个 client；生产单 loop 部署无感知。
- **ultra 模式**需要图存储，当前未在本仓库验证；建议先用 lite/pro。
- **`async_search` 无 `source` 参数**：SDK 2.0.1 的过滤参数是 `include_sources`，
  本集成只传 `include_sources=[settings.source]`。
- **数据目录迁移**：`HYMEMORY_DATA_DIR` 改变等于换一套记忆库，需整体迁移。
