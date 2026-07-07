# 节点级指标 PR2：LLM 成本 entry + Ripple 计时 entry

## Goal

接 PR1（节点级 + human_wait），补 LLM 调用成本 entry 与 Ripple 调用耗时 entry，让 analytics 成本 reader 真正读出非 0 成本，Ripple 调用耗时可观测。

## What I already know

- PR1 已建 `performance_log` 的 `kind` 体系（node/llm/ripple/human_wait），reader 已按 kind 过滤
- `BaseAgent.model` property（`backend/agents/base.py:34`）懒加载 `get_model(task_type)`，所有 agent 经 `self.model.ainvoke(messages)` 调 LLM
- LLM 响应有 `response.usage_metadata`（LangChain BaseChatModel 标准属性，含 input/output tokens）
- `CostTracker`（`backend/models/cost_tracker.py`）dead code，有 `COST_PER_1K` 表可复用算成本
- RippleService 三方法需包装：`predict_spread`/`validate_pmf`/`get_simulation_status`（`backend/services/ripple_service.py:572,660,754`）
- analytics 成本 reader 读 `kind in (llm,ripple,None)` 的 `cost_usd` + `model`

## Requirements

- **LLM entry**：每次 `self.model.ainvoke(...)` 后写一条 `{kind:"llm", model, task, cost_usd, input_tokens, output_tokens, timestamp}`
  - 包装方式：`BaseAgent.model` property 返回一个代理对象，拦截 `ainvoke`/`batch` 等调用，调原 model、读 `response.usage_metadata`、算成本、追加 entry 到 agent 的 perf buffer
  - 成本计算复用 `COST_PER_1K` 表（未知 model fallback 默认价）
  - entry 经 `__call__` 返回 dict 的 `performance_log` 一并合入 state（accumulate 进 `__call__` 现有 node entry 旁）
- **Ripple entry**：`predict_spread`/`validate_pmf`/`get_simulation_status` 调用写 `{kind:"ripple", operation, duration_seconds, status, cost_usd?, timestamp}`
  - 包装在 RippleService 内部（每方法 try/finally 计时），best-effort 不影响主调用
  - cost_usd 暂空（Ripple 无 token 成本模型），后续可填
- **agent 累积**：BaseAgent 实例持一个 `_perf_buffer: list[dict]`，LLM 包装往里追加 entry，`__call__` 成功时把 buffer 里本次调用的 entry 连同 node entry 一起放 `performance_log`

## Acceptance Criteria

- [ ] agent 调 LLM 后 performance_log 出现 `kind:"llm"` entry，含 model + cost_usd > 0 + token 数
- [ ] analytics 成本 reader 读出非 0 总成本
- [ ] RippleService.predict_spread/validate_pmf 调后出 `kind:"ripple"` entry，duration_seconds > 0
- [ ] 包装失败 best-effort 不影响 LLM/Ripple 主调用
- [ ] 全量 pytest 绿，ruff + mypy 不新增错误（pre-exist 3 个 browser 服务错误不算）

## Out of Scope

- Ripple cost_usd 真实定价（暂空）
- LLM 调用的 streaming 计时细分
- cost 预算熔断（CostTracker circuit 逻辑不本 PR 接活）

## Technical Approach

**LLM 包装**：`BaseAgent._model` 改存代理。代理类 `_InstrumentedModel` 持原 model + agent 引用，`__getattr__` 透传，`ainvoke` 包一层：调原 ainvoke、`response.usage_metadata` 取 tokens、`_calc_cost` 算钱、`self._agent._perf_buffer.append(entry)`、返回原 response。`model` property 返回代理。

**Ripple 包装**：RippleService 三方法各加 `_time_ripple("predict_spread")` 上下文管理器或 try/finally，结束后追加 entry 到实例 `_ripple_buffer`，caller（agent）取用。或更简：方法内直接 `state` 不可得，改为返回值带 perf hint —— 不行，Ripple 不持 state。

折中：Ripple entry 写进 RippleService 实例 `_last_perf` list，agent（content_strategist/analyst）调完后读 `RippleService.get_instance()._last_perf` 取 entry 放进自己 perf_buffer。最简且不改 Ripple 返回签名。

## Implementation Plan

- 改 `backend/agents/base.py`：加 `_perf_buffer`、`_InstrumentedModel` 代理、`model` property 包装
- 改 `backend/models/cost_tracker.py`：导出 `calc_cost(model, input_tokens, output_tokens)` helper（复用 COST_PER_1K）
- 改 `backend/services/ripple_service.py`：三方法加计时写 `_last_perf`
- 改调用 Ripple 的 agent（content_strategist/analyst）：调后读 `_last_perf` 追加 perf_buffer
- 改 `__call__`：成功时 `performance_log = [node_entry, *self._perf_buffer]`，清空 buffer
- 单测：LLM entry token/cost、Ripple entry duration、包装失败不影响主调用
