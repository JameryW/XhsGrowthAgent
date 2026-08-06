# Instrument request + LLM call chain latency (prod bottleneck discovery)

## Goal

PRD 08-05 方向 1-4 剩余：请求延迟、LLM 成本/速度、可靠性。所有都需**经验数据**才能下刀，不能猜。本任务给关键路径加轻量耗时插桩，部署后收集 prod 数据，找真瓶颈，驱动后续优化 PR。

## 现状（已知）

- 冷启动 import 已达框架地板 0.44s（#451-#463），**非瓶颈**
- /status DB 写 skip-unchanged 已做（#464），history 文件写 skip 已做（#481）
- /status 前端 5s 轮询但**完成后停**（isRunning gate）—— 完成态非持续轮询
- **LLM 调用耗时已记录**：`llm_perf_entry`（nodes/_base.py:83）每次 _llm_ainvoke 记 duration_seconds/started_at/completed_at/input+output_tokens/cost_usd/billed_model，append 到 state.performance_log
- **node 耗时已记录**：`node_perf_entry`（nodes/_base.py:53）记 per-node duration
- cost_tracker / cost dashboard 已通（#417/#472）
- Ripple 后台化已做（#466），content_strategist 352s→后台非阻塞

## 真实 gap（需补）

1. **HTTP 请求级耗时分解** — /status、/list 等 GET 端点 wall-clock 拆分（aget_state vs DB upsert vs response 序列化含 perf_log→agent_timeline vs _get_ripple_progress）。performance_log 只记工作流内部 agent/node，**不含 HTTP 请求层**
2. **perf_log 可查询性** — 数据在 checkpoint state.performance_log，非独立 queryable sink；分析需 aget_state 逐 thread 读，难聚合
3. **ainvoke 子分解** — llm_perf_entry 只记总调用时长，无 prompt 构建 vs ainvoke vs JSON 解析拆分（可能 prompt 构建或解析占大头，未知）

## 设计原则（ponytail）

- **轻量**：用现有 logger 结构化 JSON 行，不引 metrics 框架（prometheus/otel 太重）
- **可关**：env var `XHS_LATENCY_LOG=1` 默认关，prod 按需开，避免常态开销
- **采样**：高频端点（/status）采样 1/10，低频全记
- **结构化**：JSON 行（thread_id, endpoint, phase, duration_ms, breakdown），便于 grep/jq
- **不破坏**：插桩失败必静默（latency log 不该影响请求）
- **复用**：LLM/node 已有 perf_log，PR-B 只补 ainvoke 子分解 + 可查询读取端点，不重造

## 范围（多 PR）

- **PR-A**：4 个高频 GET 端点 HTTP 请求级耗时分解：/status、/list、/account-totals、/evaluation/result。env-gated `XHS_LATENCY_LOG=1`，logger.info 结构化 JSON 行（thread_id, endpoint, phase, total_ms, aget_state_ms, db_ms, serialize_ms, ripple_progress_ms）。采样：/status 1/10，其余全记。插桩失败静默 try/except。thread_id 显式传参，不用 contextvar（避免 asyncio task 复用泄漏）。
- **PR-B**：_llm_ainvoke 子分解。llm_perf_entry 已记总 duration；补 prompt_build_ms / ainvoke_ms / parse_ms 三段（contextvar 或 _llm_ainvoke 内分段计时），append 到现有 perf_log entry。复用 perf_log，不新建 sink。
- **PR-C**：prod 收集脚本 `scripts/collect_latency.sh`（podman logs 抓 + jq 聚合 p50/p95 per endpoint/phase）+ README 记使用。无新端点。

## AC（evolving）

- [x] PR-A: env-gated `/status`+`/list`+`/account-totals`+`/evaluation/result` 耗时分解 JSON 行，默认关，/status 采样 1/10 — PR #483 opened
- [x] PR-B: _llm_ainvoke ainvoke_ms + parse_ms 进 perf_log（prompt_build_ms 已记于 node 级，未单独补） — PR #484 opened
- [x] PR-C: collect_latency.py（pure stdlib，无 jq）p50/p95 + README — PR #485 opened
- [ ] prod 部署后收集 ≥ 1 天数据（需用户部署，XHS_LATENCY_LOG=1）
- [ ] 数据驱动识别 ≥ 1 个真瓶颈，开后续优化 PR

## Decision (ADR-lite)

**Context**: HTTP 请求层耗时（aget_state/db/serialize）无观测，performance_log 只记工作流内部。需选 metrics sink。
**Decision**: 结构化 logger JSON 行（env-gated `XHS_LATENCY_LOG=1`）。零新表零依赖，ponytail 最简，podman logs + jq 聚合。LLM/node 复用现有 perf_log 不重造。
**Consequences**: 跨容器难聚合、容器重启丢历史日志 —— 可接受（本任务是发现瓶颈非长期监控，找到瓶颈后优化 PR 落地即可）。如需长期监控再上 DB/otel。

## Out of Scope

- 重复已优化层（冷启动 / DB skip / 文件 skip / Ripple 后台）
- 引入 prometheus/opentelemetry（太重，ponytail 用 logger）

## 风险

- 插桩本身增延迟 —— 用 env gate + 采样控制
- prod 数据收集需部署配合 —— PR 合并后需用户部署验证
