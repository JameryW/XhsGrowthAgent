# Research: LangGraph 节点返回 error dict（不抛异常）时的 graph 行为

- **Query**: 方案 A（BaseAgent.__call__ except 块改 `return handle_agent_error(e, state)` 不抛）前提下，确认 LangGraph 节点返回 dict（含 error 字段）时 graph 是否正常 super-step + state merge + conditional edge 路由，且 RetryPolicy 不触发。
- **Scope**: mixed（external LangGraph 官方文档 + internal repo graph/router/agent 代码）
- **Date**: 2026-07-07

## Findings

### 结论速览（方案 A 前提是否成立）

| 子问题 | 结论 | 依据 |
|---|---|---|
| 节点返回 dict → state 正常 merge？ | **是** | LangGraph graph-api 文档：node "responds with updates"，reducer 合并 |
| 节点返回 dict → conditional edge 正常跑？ | **是** | 文档：routing function "called **after** that node is executed" |
| 节点返回 dict → super-step 完成？ | **是** | 文档：Pregel 模型，node 返回 updates 即完成本轮 super-step |
| 节点抛异常 vs 返回 dict 行为差异？ | **是，显著差异** | 抛异常 → retry/error-handler 链；返回 dict → 正常推进 |
| RetryPolicy 在返回 dict 时是否触发？ | **否，完全不触发** | 文档：retry 仅在 "node attempt **raises any exception**" 时触发 |
| 节点返回 phase=ERROR 是否自动终止？ | **否（LangGraph 层面无自动终止）** | LangGraph 不读业务 phase 字段；终止逻辑全在本 repo routers.py 的 `_check_terminal` |
| 方案 A 前提成立？ | **成立** | 返回 error dict = 正常 super-step，router 可读 error/retry_count 决定重试/终止 |

**方案 A 前提成立**：节点返回 `{phase:ERROR, error:str, retry_count:N}` dict 时，graph 正常完成 super-step、state merge、conditional edge 路由。router（如 `should_plan`）可读 `state.error` + `state.retry_count` 决定重试 `trend_scout` 或终止 `__end__`。这是 stateful retry 的可行路径。

### 关键风险：phase=ERROR 会被 `_check_terminal` 拦截

**这是方案 A 必须处理的边界条件。** `handle_agent_error` 返回 `phase: WorkflowPhase.ERROR`，而本 repo 几乎所有 router 都先调 `_check_terminal(state)`，`phase=ERROR` 直接返回 `__end__` —— 即 graph 会立即终止，**不会**走到重试分支。

文件 `backend/graph/routers.py:11-26`：
```python
def _check_terminal(state: XHSGrowthState) -> Literal["__end__"] | None:
    """Terminal states: cancelled, paused, error, completed.
    Note: state.get("error") alone is NOT terminal — the workflow may retry
    or have next nodes that can recover. Only phase=ERROR is terminal.
    """
    phase = state.get("phase")
    if phase in (WorkflowPhase.CANCELLED, WorkflowPhase.PAUSED,
                 WorkflowPhase.ERROR, WorkflowPhase.COMPLETED):
        return "__end__"
    return None
```

**例外**：`should_plan`（trend_scout 后的路由器）专门为重试改写，**error 重试优先于 `_check_terminal`**。文件 `backend/graph/routers.py:64-93`：
```python
def should_plan(state) -> Literal["content_strategist","trend_scout","__end__"]:
    # ... trend_data 优先 ...
    # Error retry takes priority over terminal check — phase=ERROR with
    # retry_count < 2 should retry, not terminate immediately
    has_error = state.get("error")
    retry_count = state.get("retry_count", 0)
    phase = state.get("phase")
    retryable = has_error and retry_count < 2
    if retryable and phase not in (WorkflowPhase.CANCELLED, WorkflowPhase.PAUSED):
        return "trend_scout"
    if terminal := _check_terminal(state):
        return terminal
    return "__end__"
```

即：`should_plan` 是当前**唯一**对 `phase=ERROR + retry_count<2` 开重试后门的 router。其他 router（`orchestrator_router`/`review_outcome`/`should_continue`/`engagement_router`/`should_optimize`/`visual_designer_router`/`ripple_gate_router` 等）都会因 `phase=ERROR` 直接 `__end__`。

**含义**：方案 A 若让 BaseAgent 统一返回 `phase=ERROR`，则只有 trend_scout 节点（经 `should_plan`）能 stateful 重试；其他节点（copywriter/visual_designer/publisher 等）一旦失败返回 `phase=ERROR`，graph 立即终止，不会重试。若要对所有节点做 stateful retry，要么 (a) 不设 `phase=ERROR` 而保留当前 phase + 设 `error` 字段，要么 (b) 为每个下游 router 加类似 `should_plan` 的重试优先逻辑。**方案 A 若只针对 trend_scout 重试场景则无障碍；若想通用化需配套改 router。**

### External References（LangGraph 官方文档，docs.langchain.com）

#### 1. 节点返回 dict → state merge + super-step 完成

**Graph API overview**（https://docs.langchain.com/oss/python/langgraph/graph-api）：

> "Nodes: Functions that encode the logic of your agents. They receive the current state as input, perform some computation or side-effect, and **return an updated state**."

> Pregel 模型："The active node then runs its function and **responds with updates**. At the end of each super-step, nodes with no incoming messages vote to halt by marking themselves as inactive. The graph execution terminates when all nodes are inactive and no messages are in transit."

→ 节点返回 dict 即"responds with updates"，reducer 合并到 state，super-step 完成。**返回 dict 不区分内容是否含 error 字段**——LangGraph 只把它当 state update。

#### 2. Conditional edge 在节点返回后正常跑

**Graph API — Conditional edges**：

> "add_conditional_edges... accepts the name of a node and a 'routing function' to call **after that node is executed**."

> "the routing_function accepts the current state of the graph and returns a value... used as the name of the node (or list of nodes) to send the state to next."

→ 节点返回 dict（无论含不含 error）后，conditional edge router 正常被调用，读到 merge 后的 state（含 error/retry_count 字段），正常决定下一节点。**router 是否读 error 是业务代码的自由**，LangGraph 不干预。

#### 3. 抛异常 vs 返回 dict 的行为差异（核心）

**Fault tolerance**（https://docs.langchain.com/oss/python/langgraph/fault-tolerance）：

> "When a node fails—from a slow external API, a transient network error, or an unhandled exception—LangGraph gives you three composable mechanisms: Retries / Timeouts / Error handling."

> "These compose in a fixed order: **when a node attempt raises any exception** (including NodeTimeoutError from a timeout), the retry policy decides whether to retry. **Only after retries are exhausted does the error handler run.**"

→ **抛异常**才进入 retry → error_handler 链。返回 dict（不抛）= 节点成功完成，不进这条链。

#### 4. RetryPolicy 仅在抛异常时触发

**Fault tolerance — Retries**：

> "A retry policy automatically re-runs a failed node attempt based on **exception type** and backoff settings."

> `retry_on` 参数："**Exceptions** to retry on, or a callable returning True for retryable exceptions."

> 默认 `default_retry_on`："retries on any exception except [ValueError/TypeError/ArithmeticError/...]"

→ RetryPolicy 的输入是 **exception**，不是 state。节点返回 dict（不抛）时，**RetryPolicy 完全不触发**。方案 A 改为返回 dict = **主动放弃 LangGraph RetryPolicy**（max_attempts 重试），改由业务 router 用 `retry_count` 字段做 stateful 重试。

#### 5. error_handler 也是返回值（Command），不抛

**Fault tolerance — Error handling**：

> "Pass `error_handler=` to add_node... rather than abort the entire graph."

> 示例：`def payment_error_handler(state, error: NodeError) -> Command: return Command(update={...}, goto="finalize")`

> "The handler fires only after the retry policy is exhausted, or immediately if no retry policy is configured."

→ 即便 LangGraph 自带的 error_handler 恢复路径，也是**返回 Command(update, goto)** 让 graph 继续，而非抛异常。这与方案 A "返回 dict 让 graph 推进" 的思路一致——LangGraph 的设计哲学就是"用返回值表达恢复，不靠抛异常终止"。

### Files Found（internal repo）

| File Path | Description |
|---|---|
| `backend/agents/base.py:194-239` | `BaseAgent.__call__` — 当前 except 块 `raise AgentError`（方案 A 改造目标） |
| `backend/core/error_handling.py:9-27,36-42` | `AgentError` 异常类 + `handle_agent_error()` 返回 `{phase:ERROR, error, retry_count+1}`（方案 A 的返回值来源，目前是 dead code） |
| `backend/graph/error_handling.py:13-31` | `RETRY_POLICIES` dict + `get_retry_policy()` — 各节点 RetryPolicy(max_attempts) 配置 |
| `backend/graph/builder.py:66-127` | `build_graph()` — 每个节点 `add_node(..., retry_policy=get_retry_policy(...))` |
| `backend/graph/routers.py:11-26` | `_check_terminal()` — `phase=ERROR` 视为 terminal 返回 `__end__`（方案 A 关键拦截点） |
| `backend/graph/routers.py:64-93` | `should_plan()` — 唯一对 `phase=ERROR + retry_count<2` 开重试后门的 router |
| `backend/agents/orchestrator.py:30-37` | `OrchestratorAgent.execute` — 已有 "返回 error state 不抛" 先例：`return {"phase": SCOUTING, "error": None, "retry_count": 0}` |
| `backend/agents/publisher.py:151-198,265-280` | `PublisherAgent.execute` — 已有 "返回失败 dict 不抛" 先例：账号停用/CDP 缺失/发布异常都 `return {publish_result:{status:"failed",...}, phase:PUBLISHING}`，不 raise |
| `backend/agents/nodes/_base.py:35-39` | `_check_cancelled()` — cancelled/paused 才抛 `WorkflowCancelledError`，error 不抛 |

### Code Patterns

#### 先例 1：orchestrator 返回 error state 不抛（已存在）

`backend/agents/orchestrator.py:30-37`：
```python
# 有错误 → 检查是否可恢复
error = state.get("error")
retry_count = state.get("retry_count", 0)
if error and retry_count >= 3:
    return {"phase": WorkflowPhase.ERROR}
if error:
    # 清除错误，重新开始侦察周期
    return {"phase": WorkflowPhase.SCOUTING, "error": None, "retry_count": 0}
```
→ orchestrator 读 `state.error` + `retry_count` 做 stateful 决策，**不抛异常**。这正是方案 A 想要的模式，且已在线上运行。

#### 先例 2：publisher 返回失败 dict 不抛（已存在）

`backend/agents/publisher.py:151-169`（账号停用）：
```python
if account is None or not account.is_active:
    publish_result = {"post_id":"","post_url":"","status":"failed",
                      "error": f"账号 {publish_account_id} 已停用", ...}
    return {"publish_result": publish_result, "phase": WorkflowPhase.PUBLISHING}
```
`backend/agents/publisher.py:265-280`（发布异常 catch 后仍 return，不 raise）：
```python
except Exception as e:
    error_type, recovery = classify_publish_error(str(e))
    publish_result = {"status":"failed","error":str(e),...}
finally:
    await client.close()
# ... 继续走完，return publish_result（含 status:failed）
```
→ publisher 是"节点返回失败 dict（status:failed）但不抛"的活先例。注意它返回 `phase: PUBLISHING`（**不是 ERROR**），所以下游 router 不会因 `_check_terminal` 立即终止——失败信息靠 `publish_result.status=="failed"` 表达，由 API 层/前端读取。**这与 `handle_agent_error` 返回 `phase:ERROR` 的设计不同**，是更安全的"失败不终止"模式。

#### 当前 __call__ 的 raise 逻辑（方案 A 改造点）

`backend/agents/base.py:214-221`：
```python
try:
    result = await self.execute(state, store)
except Exception as e:
    logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
    # Propagate to LangGraph retry mechanism. State can't be updated
    # on a raised exception — the retry's next successful call records
    # the attempt count via its `retries` field.
    raise AgentError(self.agent_name, e) from e
```
注释明确："State can't be updated on a raised exception"——这正是方案 A 要解决的问题：改返回 dict 即可把 error 写进 state，让 router 读到。

#### handle_agent_error 当前是 dead code

`grep handle_agent_error backend/ tests/` 结果：仅在 `core/__init__.py` 导出 + `core/error_handling.py` 定义 + `tests/test_core_error_handling.py` 测试，**无任何生产调用点**。方案 A 是给这个 dead code 接上调用方。

### Related Specs

- `.trellis/tasks/07-07-remove-handle-agent-error-dead-code/` — 本任务根目录（PRD/方案在任务文件中）

## Caveats / 风险与边界

1. **`phase=ERROR` + 通用 router = 立即终止**：`handle_agent_error` 返回 `phase=ERROR`，除 `should_plan` 外所有 router 的 `_check_terminal` 会直接 `__end__`。方案 A 若只想让 trend_scout 重试则 OK；若想让 copywriter/visual_designer/publisher 等也 stateful 重试，**必须**配套改对应下游 router（加类似 `should_plan` 的 error-retry-priority 逻辑），或让 `handle_agent_error` 不设 `phase=ERROR`（保留当前 phase + 只设 `error`/`retry_count`，参照 publisher 的 `phase:PUBLISHING + status:failed` 模式）。

2. **放弃 LangGraph RetryPolicy 的代价**：方案 A 返回 dict = RetryPolicy(max_attempts) 完全不触发。原本 `trend_scout` max_attempts=3 的自动重试（带 backoff）会失效，改由 `should_plan` 的 `retry_count<2` 做 stateful 重试（无 backoff、无 exception-type 过滤）。需确认这是预期代价——RetryPolicy 的 backoff/jitter/exception 过滤是 stateful retry 没有的能力。

3. **performance_log 失败条目丢失**：当前 `__call__` 在 raise 时无法写 `performance_log`（注释明说"can't be written to state mid-exception"）。方案 A 改返回 dict 后，**可以**在 except 块里构造 `status:"failed"` 的 perf entry 并塞进返回 dict——这是方案 A 的额外收益，但需 `handle_agent_error` 或 except 块主动加 `performance_log` 字段（当前 `handle_agent_error` 不写 perf log）。

4. **`AgentError` 异常类是否仍需保留**：方案 A 后 `__call__` 不再 raise `AgentError`，但 `AgentError` 类本身可能被其他地方（如 omp 扩展、API 错误映射）引用——需 grep 确认无外部依赖后再决定是否删除。当前 codegraph 显示 `AgentError` 仅 1 caller（`base.py` 的 raise 点）。

5. **interrupt() 不走 error handler**：LangGraph 文档明确 `interrupt()`（人审 gate 用的）bypass retry/error-handler，走 GraphBubbleUp 机制暂停。方案 A 不影响人审 gate（review_gate/choice_gate/draft_gate 用的是 interrupt 不是 raise）。

6. **未实测验证**：以上结论基于 LangGraph 官方文档文本 + repo 代码静态分析，未跑实际 graph 验证"返回 error dict → should_plan 路由 trend_scout 重试"的端到端行为。建议方案 A 落地后补一个集成测试（mock trend_scout execute 抛异常 → 断言 graph 路由到 trend_scout 而非 __end__）。
