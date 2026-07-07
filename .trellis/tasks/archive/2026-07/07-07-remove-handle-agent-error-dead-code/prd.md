# 接入 handle_agent_error — 激活 stateful retry

## Goal

`handle_agent_error()` 定义于 `backend/core/error_handling.py:36` 但执行路径零调用（仅 tests/ 引用）。它本应递增 `state.retry_count` 供 `should_plan`/`orchestrator` 的 retry 路由用，但当前 `BaseAgent.__call__` except 块抛 `AgentError`，LangGraph 节点抛错时不 merge state → retry_count 永不递增 → should_plan（retry_count<2）+ orchestrator（retry_count>=3）retry 分支死代码。

接入方式：`__call__` except 块改 `return handle_agent_error(e, state)`（不抛），返回 `{error, retry_count+1, phase:ERROR}` state update。state merge 后 should_plan/orchestrator 读 retry_count 决定 retry vs 终止。激活原设计意图的 stateful 跨 super-step retry，放弃 LangGraph RetryPolicy 框架级瞬时重试（节点不抛就不触发）。

## What I already know

- `handle_agent_error`（error_handling.py:36）：返回 `{"error": str, "phase": ERROR, "retry_count": old+1, "current_agent": ...}`，零调用。
- `BaseAgent.__call__`（base.py:194-221）：except 块 `raise AgentError`，不写 state。
- LangGraph 节点抛错 = super-step 失败，返回 dict 不 merge，conditional edge router 不跑。
- `should_plan`（routers.py:64-93）：读 `retry_count < 2` → 重试 trend_scout；当前死（retry_count 恒 0 + error 不被设）。
- `orchestrator`（orchestrator.py:32-37）：读 `retry_count >= 3` → ERROR；当前死。
- `retry_count`：schema.py:44 字段；workflow.py:485 + cli/main.py:85 初始化 0。
- LangGraph `RetryPolicy`（graph/error_handling.py）：trend_scout/publisher/engagement max_attempts=3，copywriter 等 2，orchestrator/review_gate 1。节点抛错时框架级瞬时重试。
- trend_scout 等节点工具调用已自己 try/except 吞错继续（不抛），真正会抛的是 `self.model.ainvoke`（LLM）失败。
- `base.py:213` `retries = state.get("retry_count", 0)` 写进 performance_log retries 字段——接入后变活（真反映重试次数）。

## Research References

* [`research/langgraph-node-error-state.md`](research/langgraph-node-error-state.md) — 方案 A 前提成立：节点返回 dict（不抛）= 正常 super-step + state merge + conditional edge 路由，RetryPolicy 完全不触发。

## Research Notes

### LangGraph 节点返回 dict vs 抛异常
- 返回 dict：super-step 成功，state merge，conditional edge router 跑。
- 抛异常：super-step 失败，RetryPolicy 重试（max_attempts），最终失败 graph 进 ERROR，conditional edge 不跑。
- RetryPolicy 仅 exception 触发；节点返回 dict（不抛）= RetryPolicy 完全不触发。A 方案放弃 RetryPolicy 零代价（节点不抛就不触发）。

### _check_terminal 行为（关键）
- `_check_terminal`（routers.py:11-26）只看 `phase`（CANCELLED/PAUSED/ERROR/COMPLETED），**不看 `error` 字段**（注释明确：「state.get("error") alone is NOT terminal」）。
- `handle_agent_error` 返回 `phase:ERROR` → `_check_terminal` 拦 → `__end__` 终止。**这是期望行为**：非 trend_scout 下游节点失败即终止（fail fast，不用错误数据继续）。
- `should_plan`（routers.py:64-93）对 `phase=ERROR + retry_count<2` 开了重试后门（行 86-88，retryable 检查在 _check_terminal 之前）——trend_scout 失败可重试，这是原设计意图。
- 其他节点（copywriter/visual_designer 等）失败 → phase=ERROR → 终止，无 retry。符合「失败可见 + fail fast」。
- `orchestrator`（orchestrator.py:32-37）读 retry_count>=3 → 设 ERROR phase 终止：trend_scout 重试 3 次仍失败 → orchestrator 标 ERROR。

### repo 先例
- publisher 失败用 `status:failed` + 保留 phase（PUBLISHING），不设 phase=ERROR——因 publisher→END 无下游 router，靠 status=failed 表达 + /publish-retry 端点。这与 handle_agent_error 的 phase=ERROR 模式不同，因 publisher 路径特殊（无下游、有 retry 端点）。
- 本任务沿用 handle_agent_error 的 phase=ERROR 模式（通用节点 fail fast），不照搬 publisher 模式。

## Decision (ADR-lite)

**Context**: handle_agent_error 死代码，retry_count 永不递增，should_plan/orchestrator retry 分支死。节点抛错时 LangGraph 不 merge state，无法在 except 里改 state。

**Decision**: 方案 A — `BaseAgent.__call__` except 改 `return handle_agent_error(e, state)`，不抛 AgentError。节点失败返回 error state（含 phase=ERROR + retry_count+1），state merge 激活 should_plan/orchestrator stateful retry。放弃 LangGraph RetryPolicy（节点不抛就不触发，零代价）。

**Consequences**:
- ✅ 激活原设计 stateful retry，should_plan（trend_scout 重试）+ orchestrator（retry_count>=3 终止）retry 分支变活。
- ✅ 一处接入（BaseAgent.__call__），所有继承 agent 自动获 retry。
- ✅ error + retry_count 写进 state，SSE/前端可观测重试次数。
- ✅ performance_log retries 字段变活（真反映重试次数）。
- ✅ fail fast：非 trend_scout 节点失败 → phase=ERROR → _check_terminal 终止，不用错误数据继续。
- ⚠️ trend_scout 重试重跑整个节点（含已成功工具调用），非增量。工具幂等可接受。
- ⚠️ 其他节点（copywriter 等）失败无 retry，直接终止——符合 fail fast，但若需这些节点 retry 要另开 router 后门（out of scope）。

## Requirements

- `BaseAgent.__call__` except 块：`raise AgentError` → `return handle_agent_error(e, state)`。
- handle_agent_error 返回值需含 `current_agent`（供 should_plan/orchestrator 读）+ `error` + `retry_count+1` + `phase: ERROR`。
- 确认 should_plan/orchestrator retry 分支激活后行为正确：
  - should_plan：error + retry_count<2 → trend_scout；retry_count>=2 或无 error → __end__（或 terminal）。
  - orchestrator：error + retry_count>=3 → ERROR phase 终止。
- 取消 LangGraph RetryPolicy？或保留（节点不抛就不触发，无害）？倾向保留（万一某节点仍抛非 AgentError 异常，RetryPolicy 兜底）。
- performance_log：`__call__` 不抛后，failed entry 怎么记？原 raise 路径不写 performance_log（mid-exception）。改 return 后可写 failed entry（best-effort）。

## Acceptance Criteria

- [ ] BaseAgent.__call__ except 返 handle_agent_error(e, state)，不抛。
- [ ] 节点失败时 state 含 error + retry_count 递增 + phase ERROR。
- [ ] should_plan retry 分支激活：error + retry_count<2 → 重试 trend_scout；>=2 → __end__。
- [ ] orchestrator retry 分支激活：error + retry_count>=3 → ERROR 终止。
- [ ] performance_log retries 字段真反映重试次数（非恒 0）。
- [ ] 既有测试不退化（test_core_error_handling 仍过 + 新增 retry 集成测试）。
- [ ] pytest/mypy/ruff 绿。

## Definition of Done

- Tests: 新增 stateful retry 集成测试（节点失败 → retry_count 递增 → should_plan 重试 → 达上限终止）。
- Lint/typecheck/CI 绿。
- 无回归：trend_scout/publisher 正常路径不受影响。

## Out of Scope

- LangGraph RetryPolicy 调整（保留兜底）。
- model 层 LLM 限速重试（langchain client 自带，另任务）。
- should_plan/orchestrator retry 阈值调整（保持 2/3）。

## Technical Notes

- 文件：`backend/agents/base.py`（__call__ except）、`backend/core/error_handling.py`（确认 handle_agent_error 返回值完整）、`tests/`（新增 retry 集成测试 + 更新 test_core_error_handling）。
- 风险：节点不抛后 LangGraph graph 行为变化——需确认 graph 仍正常推进（节点返回 dict → super-step 完成 → conditional edge router 跑）。
- 参考：should_plan 行 64-93、orchestrator 行 32-37、__call__ 行 194-221。
