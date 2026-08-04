# 修复 LLM 成本追踪 — cost_usd 从未写入 performance_log

## Goal

Analytics 成本看板（`/api/analytics/costs` + omp `xhs_costs` 工具）当前永远显示 $0.00。
根因：reader 从 `performance_log` 条目读 `cost_usd` 字段，但**没有任何代码写入它**。
`node_perf_entry` 只写节点级 timing（kind:"node"），无 token/cost；`CostTracker.record`
（唯一会算 cost_usd 的地方）从未被调用 → 死代码。修复后看板按模型/日聚合真实 LLM 成本。

## What I already know

- `backend/api/routes/analytics.py:997,1128` reader: `cost = entry.get("cost_usd", 0.0)`，
  按 `entry["model"]` 聚合 `by_model`，按时间戳过滤 today/period。
- `backend/agents/nodes/_base.py:53` `node_perf_entry` 写 `kind:"node"` 条目，无 cost_usd。
- `backend/agents/nodes/_base.py:99` `record_human_wait` 写 `kind:"human_wait"`。
- reader 注释（analytics.py:993）期望 `kind:"llm"` / `kind:"ripple"` 条目带 cost_usd ——
  但无 `llm_perf_entry` helper，无人写这类条目。
- `backend/models/cost_tracker.py` `CostTracker` + `COST_PER_1K`（缺 astron/mimo）= 死代码，
  无 caller（唯一 `.record(` 是 `ContentHistory.record`，不同物）。
- `backend/config/models.py:134` `MODEL_COST_PER_1K` 是规范成本表（含 astron-code-latest、
  mimo-v2.5-pro），但也无 importer —— 同样孤立。
- LLM 调用点 ~10 个 `await self.model.ainvoke(...)`：copywriter(×3)、evaluator、analyst、
  visual_designer、blogger_scout(×2)、viral_matcher、shooting_planner、content_analyzer、
  llm_enrichment。每个 response 带 `usage_metadata`/`response_metadata`（input/output tokens）
  但只读 `response.content`，token 丢弃。
- 全部 task 路由到 `astron-code-latest`（`resolve_model_id`），成本 $0.0002/$0.0006 per 1K。

## Assumptions (temporary)

- LangChain `response.usage_metadata` 形如 `{input_tokens, output_tokens, total_tokens}`
  （各 provider 透传 OpenAI 兼容格式；astron 走 DashScope 兼容模式）。
- `self.model` 是 `BaseChatModel`，`response.response_metadata` 含 `model_name`（实际计费模型）。
- cost_usd 应在 LLM 调用点算并 append 进 `performance_log`（kind:"llm"），与 node 条目并列。
- 日预算熔断（`CostTracker.circuit_open`）当前硬编码 False —— 本任务不实现真熔断（out of scope）。

## Open Questions

- ~~Q1：捕获点~~ → 选定方案 A（agent 内显式记）。

## Decision (ADR-lite)

**Context**: cost_usd 从未写入 perf_log，看板恒 $0。token 数据在 ~10 个 ainvoke 调用点的 response 上，被丢弃。
**Decision**: 方案 A —— 新增 `llm_perf_entry` helper（`_base.py`，与 `node_perf_entry` 并列），
在各 agent ainvoke 后显式调用，传 response + agent_name + model + started/completed。
调用点自己 append 进返回 dict 的 `performance_log`（与 node 条目同 list，reducer 合并）。
删除死代码 `CostTracker` + `COST_PER_1K`，`MODEL_COST_PER_1K` 成唯一成本源。
**Consequences**: 改 ~10 文件每处 +几行样板，无抽象无魔法；evaluator 超时分支无 response 不记；
重试循环可选只记最终 response。reader 无需改（已按 model+cost_usd 聚合）。

## Requirements (evolving)

- 每个 LLM ainvoke 调用后，按真实 token 用量 + `MODEL_COST_PER_1K` 算 cost_usd，
  append 一条 `kind:"llm"` perf_log 条目（含 model、input/output_tokens、cost_usd、duration）。
- Analytics cost reader 读到非零 cost_usd；`by_model` / `today_cost_usd` / `total_cost_usd` 反映真实开销。
- 删除死代码 `CostTracker` + 过期 `COST_PER_1K`（保留 `MODEL_COST_PER_1K` 作唯一成本源）。
- 失败/超时/降级路径不计 cost（无 response）或只记 input_tokens（若 provider 返回部分 usage）——best-effort。

## Acceptance Criteria (evolving)

- [ ] 跑一次含 LLM 调用的 workflow 后，`/api/analytics/costs` 返回 total_cost_usd > 0。
- [ ] `by_model` 含 `astron-code-latest` 且金额 > 0。
- [ ] 单测：mock ainvoke 返回固定 usage_metadata → perf_log 出现 kind:"llm" 条目 + 正确 cost_usd。
- [ ] 单测：analytics reader 聚合多条 llm 条目 → by_model/today_total 正确。
- [ ] 死代码 CostTracker 删除后全量 pytest 绿（无残留 import）。
- [ ] mypy strict + ruff 绿。

## Definition of Done

- Tests added/updated（usage 捕获 + reader 聚合 + 死代码移除回归）
- Lint / typecheck / CI 绿
- 行为变更：成本看板从恒 $0 变真实值 —— deploy 后验证非零
- Rollout：纯后端，无 schema 变更（perf_log 是 state list），无迁移风险

## Out of Scope

- 日预算真熔断（circuit_open 恒 False 保持，或移除字段）—— 单独任务
- Ripple CAS 调用成本（kind:"ripple"）—— Ripple 不返回 token，无法计
- 历史回填（已有 perf_log 条目无 cost，不补）
- 前端成本看板 UI 改动（数据对了 UI 自然对）
- **LLMEnrichmentService.enrich_with_llm 成本**（image_prompt/de_ai_taste/
  title_generator/calendar 工具路径）—— service 非 BaseAgent，无 perf_log sink，
  需把 sink 穿过 tool 层；plumbing 成本 > 收益。主 agent ainvoke（7 类 + copywriter）
  覆盖主要成本，enrichment 留待单独任务。

## Technical Notes

- 捕获点候选：`BaseAgent.execute` wrapper（无 LLM 可见性）/ 各 agent ainvoke 后 / ainvoke 包装器。
- `MODEL_COST_PER_1K` 已含全部在用模型，直接复用。
- `performance_log` 经 `_append_list` reducer 跨 super-step 合并 —— llm 条目同 node 条目机制。
- evaluator 有 `asyncio.wait_for` 超时包裹；超时分支无 response，不记 cost。
