# 节点级指标：扩展 performance_log

## Goal

为工作流链路每一步记录节点级指标：节点耗时、失败率、重试次数、人工等待时长。让优化决策看数据不看感觉，并为后续 Gate 自动通过、Ripple 解耦等优化提供量化基线。LLM 调用成本与 Ripple 计时拆 PR2，本 PR 只做节点级。

## What I already know

- `backend/state/schema.py:131` `performance_log: Annotated[list[dict], _append_list]` — 状态字段已存在，list of dict，无任何 writer
- reader 期望两种 schema（互不兼容）：
  - `backend/api/routes/workflow.py:649` agent_timeline 读 `{agent, started_at, completed_at, duration_seconds, status, error}`（节点级）
  - `backend/api/routes/analytics.py:245,370` 成本读 `{cost_usd, model, timestamp}`（LLM 调用级）
- 当前 `agent_timeline` 在状态响应里**恒空**（无 writer），analytics 成本也恒空
- `backend/agents/base.py` `BaseAgent.__call__` 是所有 Agent 的统一入口（execute 的 wrapper）—— 单一计时 hook 点
- 节点函数 `backend/agents/nodes/*.py` 模式：`_check_cancelled; emit STARTED; result = await _agent(state, store); emit COMPLETED; return NodeResult(...)`
- 多个执行入口（CLI `_run`/`_resume`、workflow.py `_resume_async`/`_run_async`/`_run_retry`）—— 无单一拦截点，故计时落在 `__call__` 而非 runner
- `should_plan` router 失败重试时递增 `state.retry_count`，节点重入
- `compile_graph_dev` interrupt_before 在 review_gate/choice_gate/draft_gate —— gate 进入到 resume 即人工等待
- `backend/models/cost_tracker.py` `CostTracker` dead code（未本 PR 范围）

## Requirements

- **节点级 entry**：每次 Agent `__call__` 写一条 `{kind:"node", agent, started_at, completed_at, duration_seconds, status, error, retries}`
  - `started_at`/`completed_at` ISO8601 UTC
  - `duration_seconds` 浮点
  - `status` ∈ {success, failed}
  - `retries` = 进入时的 `state.retry_count`（router 已递增的尝试号）
  - `error` = 失败时异常 str，success 时 null
- **human_wait entry**：gate resume 时写 `{kind:"human_wait", gate, entered_at, resumed_at, wait_seconds}`
  - `entered_at` = 该 gate 上一次节点完成时间（取 performance_log 里该 agent 最后一条 node entry 的 completed_at）
  - `resumed_at` = 当前 resume 时刻
- **写入失败 best-effort**：指标记录抛异常不影响节点执行（节点本身不能因观测挂掉）
- **reader 向后兼容**：
  - agent_timeline reader 读 `kind=="node"` 或无 kind 字段（旧 entry 视为 node）
  - analytics 成本 reader 读 `kind in ("llm","ripple")` 或无 kind（旧 entry 视为 llm）—— 本 PR 无 llm entry 写入，成本仍恒空，但不崩
- **不动拓扑/不改节点行为**：只在 `__call__` 加计时 + resume 路径加 human_wait

## Acceptance Criteria

- [ ] 跑一个完整 dry_run workflow，performance_log 出现每节点一条 `kind:"node"` entry
- [ ] agent_timeline 不再恒空，返回真实 agent + duration_seconds
- [ ] 节点失败时 entry status="failed"，error 非空
- [ ] 重试时 retries 字段反映 retry_count
- [ ] gate interrupt→resume 写一条 `kind:"human_wait"` entry，wait_seconds > 0
- [ ] 现有 reader（agent_timeline / analytics 成本）向后兼容不崩，全量 pytest 绿
- [ ] 节点计时单测：success/failed/异常时不影响主流程

## Definition of Done

- 单测覆盖：节点计时 wrapper（success/failed/异常）、entry schema、agent_timeline reader 兼容、human_wait 计算
- ruff check + ruff format + 全量 mypy backend 绿
- 全量 pytest 绿（不只改的文件，遵守 [[pre-push-run-full-pytest-not-just-changed]]）
- 不改 LangGraph 拓扑，不改现有 node 行为（仅加观测）

## Technical Approach

**计时 hook**：`BaseAgent.__call__` 现状已 try/except 包 execute。改造为：
```python
async def __call__(self, state, *, store):
    started = now_utc_iso()
    retries = state.get("retry_count", 0)
    try:
        result = await self.execute(state, store)
        result["current_agent"] = self.agent_name
        result["error"] = None
        _append_perf(state, {"kind":"node","agent":self.agent_name,"started_at":started,"completed_at":now_utc_iso(),"duration_seconds":...,"status":"success","error":None,"retries":retries})
        return result
    except Exception as e:
        _append_perf(state, {...,"status":"failed","error":str(e),...})
        raise AgentError(self.agent_name, e) from e
```
`_append_perf` 写入 `result["performance_log"] = [...]`（LangGraph reducer `_append_list` 合并进 state）—— 节点返回 dict 携带新 entry，由 reducer 追加。

**human_wait**：在 resume 路径（workflow.py resume endpoint + CLI `_resume`）调 `ainvoke` 前，查 performance_log 该 gate 上次 node entry 的 completed_at 作为 entered_at，resume 后写 human_wait entry。封装一个 `_record_human_wait(state, gate)` helper。

**reader 兼容**：agent_timeline reader 过滤 `kind in ("node", None)`；analytics 成本 reader 过滤 `kind in ("llm","ripple", None)`。

## Decision (ADR-lite)

**Context**: performance_log 有 schema 无 writer，agent_timeline 恒空；多执行入口无单一拦截点；需最小侵入加节点级观测。

**Decision**:
1. 单 performance_log + `kind` 字段区分四类 entry（node/llm/ripple/human_wait），向后兼容无 kind 视为对应旧 schema
2. 计时落在 `BaseAgent.__call__`（所有 Agent 统一入口），而非每个 node 函数或 runner
3. 节点 entry 随返回 dict 的 `performance_log` key 经 `_append_list` reducer 合入 state
4. PR1 只做节点级 + human_wait；LLM 成本（包装 self.model 读 usage_metadata）+ Ripple 计时（包装 RippleService）拆 PR2 独立 task

**Consequences**:
- ✅ 单一 hook 点覆盖所有 Agent，改动集中
- ✅ 向后兼容，旧 reader 不崩
- ⚠️ human_wait 需在多处 resume 路径插入 helper，易漏点（需列举所有 resume 入口）
- ⚠️ LLM 成本拆 PR2 意味本 PR analytics 成本仍恒空（已知，可接受）

## Out of Scope

- LLM 调用成本 entry（包装 self.model 读 usage_metadata）—— PR2 独立 task
- Ripple 调用耗时/成本 entry（包装 RippleService）—— PR2 独立 task
- 节点指标可视化 UI（Dashboard 展示）—— 后续 task
- 指标持久化到独立表（仍走 LangGraph checkpoint 的 performance_log 字段）
- 告警/阈值/熔断
- 历史回填（只对新跑的 workflow 生效）

## Implementation Plan (small PRs)

- **PR1（本 task）**：节点级计时 + human_wait + reader 兼容 + 单测
  - 改 `backend/agents/base.py` `__call__` 加计时
  - 加 `_append_perf` helper（或放 `_base.py`）
  - resume 路径加 `_record_human_wait`（workflow.py + CLI main.py）
  - 改 reader 兼容 kind 过滤（workflow.py agent_timeline、analytics.py 两处）
  - 单测：节点计时 success/failed/异常不影响主流程、entry schema、reader 兼容、human_wait
- **PR2（独立 task）**：LLM 成本 + Ripple 计时
  - 包装 `BaseAgent.model` 代理拦截 ainvoke 读 usage_metadata → llm entry
  - 包装 RippleService → ripple entry
  - analytics 成本 reader 真正读出非 0 成本

## Technical Notes

- 文件：`backend/agents/base.py`、`backend/agents/nodes/_base.py`、`backend/api/routes/workflow.py`、`backend/api/routes/analytics.py`、`backend/cli/main.py`、`backend/state/schema.py`（仅注释/kind 约定）
- 约束：不改 LangGraph 拓扑、不阻塞节点执行（指标写入失败 best-effort）、向后兼容无 kind 旧 entry
- 风险点：resume 路径多处（workflow resume、retry、CLI resume），human_wait helper 易漏插 —— 实现时需 grep 全部 ainvoke resume 点
