# 修法 B 可行性深入调研：resume 不重跑已成功的耗时节点

> 本文取代初版（`fix-b-resume-point-feasibility.md`）的静态猜测。初版假设
> `_last_node == content_strategist`，经核实 **错误**——`_last_node` 在整个 backend
> 从未被写入。以下结论基于 LangGraph 源码核实 + 本仓库代码核实。

## 问题回顾
visual_designer 失败后 resume，图重跑 content_strategist（含 30 分钟 Ripple 仿真），
而非从 visual_designer 重试。要回答：能否让 resume 只重跑失败节点。

## 关键代码（已核实）

### A. `BaseAgent.__call__` 吞掉所有异常 — `backend/core/base_agent.py:144-161`
```python
except Exception as e:
    return {"error": f"{self.agent_name}: ...", "retry_count": +1,
            "current_agent": self.agent_name, "performance_log": [...]}
```
- **agent 节点失败时异常不会传播到 LangGraph**，节点"正常完成"返回 error dict。
- 因此 `RetryPolicy(max_attempts=2)`（`error_handling.py`）对 agent 节点**形同虚设**——
  LangGraph 的 retry wrapper 永远收不到异常。
- `current_agent` 在成功/失败两条路径都被设为 `self.agent_name`（失败路径 line 150）。
  ⇒ `state.values["current_agent"]` 可靠地等于失败节点名。

### B. visual_designer 失败后的实际图推进 — `visual_designer.py` + `routers.py:253`
- `visual_designer_node` 拿到 error dict 后**强制** `result["phase"] = "reviewing"`。
- `visual_designer_router` → `_check_terminal`：phase=reviewing **不在** 终态集合
  (cancelled/paused/error/completed) → 返回 `"review_gate"`。
- ⇒ **agent 节点单独失败不会产生 `phase=ERROR` 终态**，图会推进到 review_gate 中断。

### C. `phase=ERROR` 终态从哪来 — `backend/api/routes/_runner.py:285-300`
```python
except Exception as exc:
    await graph.aupdate_state(config, {"phase": "error", "error": str(exc)},
                              as_node=_get_as_node(snapshot))
    await _db_upsert(thread_id, status="error", phase="error", ...)
    raise
```
- 仅当 `graph.ainvoke()` **真正抛异常**时触发。BaseAgent 吞异常 ⇒ agent 节点不会触发。
- PRD 描述的 `phase=ERROR` 终态必然来自**非 agent 节点**（gate 节点未 try、reducer 抛错、
  或 Ripple httpx 调用在 execute 外抛出等）。**此点无法静态确认，需真机抓取**（见末尾）。

### D. 罪魁机制：`as_node=X` 推进到 X 的后继 — 已由 LangGraph 源码核实
`aupdate_state(values, as_node=X)` 的语义是"视 values 为 X 的 writes，X 刚完成"。
⇒ 下一次 `ainvoke` 运行 **X 的后继**，而非 X 本身。
- `workflow.py:973`（resume 路径）和 `_runner.py:289`（error 路径）都这么做。
- 源码依据：`Pregel.update_state` 文档 "as if they came from node as_node"；
  `pregel/_loop.py` 中 `as_node` 提交 writes 并 bump `versions_seen`，`prepare_next_tasks`
  据此算出后继为下一批 pending task。

## 修法 A（已实现）与修法 B 的意外交互 ⚠️ 重要发现

修法 A 改了 error/stale 重试的 `prev_phase` 推断，但**没动** `aupdate_state(as_node=...)`。
当前 error/stale + next 为空时：
1. `_get_as_node(state)`：`state.tasks` 为空 → `_last_node` 为 None → 返回 **`"orchestrator"`**。
2. `aupdate_state({"phase": prev_phase, "error": None}, as_node="orchestrator")`。
3. `ainvoke(None)`：as_node=orchestrator 已提交 → 下一 superstep = `orchestrator_router(state)`。
4. 修法 A 把 `prev_phase` 设成 `creating`（visual_designer 失败）→
   `orchestrator_router(creating, trend)` = **`"copywriter"`**。

**结论**：修法 A 实际上让 resume 从 **copywriter** 重入，而非 content_strategist。
- ✅ **副作用缓解了 PRD 最痛的症状**：不再重跑 content_strategist → 不再触发 30 分钟 Ripple。
- ⚠️ **但引入新隐患**：从 copywriter 重入会走 copywriter→draft_gate→viral_matcher→
  blogger_scout→**blogger_gate（中断）**，可能重新弹出版主选择中断；且重跑了 copywriter
  等本已成功的节点。这不是"重试 visual_designer"，而是"从更上游重来"。

⇒ **修法 A 不能算修法 B 的替代**，它只是把"重跑 Ripple"降级成"重跑 copywriter+gates"。
真正的修法 B 仍需让 resume 精确命中失败节点。

## 修法 B 方案排序（针对本仓库 BaseAgent 吞异常的现实）

### 方案 2（推荐）：`Command(goto=<失败节点>)` 作为 resume 输入
- 不写 `as_node`、不 `aupdate_state` 推进后继，直接
  `ainvoke(Command(goto=state.values["current_agent"]), config)`。
- `Command(goto=...)` 直接跳转到目标节点，**只重跑该节点**，不碰上游 content_strategist/Ripple。
- 适用本仓库现实：即使没有 LangGraph 级 error checkpoint（BaseAgent 吞了），goto 也能跳。
- 失败节点名可靠来自 `state.values["current_agent"]`（见 A）。
- 需先清 error / 设非终态 phase：可 `aupdate_state({"error": None, "phase": <非终态>})`
  —— 但**无 as_node 时若多 task pending 会抛 InvalidUpdateError**；error 终态 next 通常为空
  （单 task），应不歧义。**需一行运行时验证**（见待办）。
- `Command` 已在本仓库使用（`cli/main.py:301` 用 `Command(resume=...)` 作 ainvoke 输入），
  `goto` 作外部输入未找到文档确认 —— 待验证。

### 方案 1：直接 `ainvoke(None)`，去掉 `aupdate_state(as_node=...)`
- LangGraph 原生 error-resume **只重跑失败节点**（源码核实：失败 task 的 writes 为空、
  versions_seen 不 bump、resume 时重执行）。
- 但**前提是存在 LangGraph 级 error checkpoint**（异常传到 ainvoke）。本仓库 BaseAgent 吞异常，
  agent 节点不形成该 checkpoint ⇒ **方案 1 单独不可行**，需配合方案 3。

### 方案 3（治本，范围大）：agent 节点在重试耗尽后 re-raise
- 改 `BaseAgent`/节点 wrapper：retry 真正耗尽时让异常传播到 LangGraph（而非返回 error dict），
  至少对"彻底不可恢复"的情况。
- 之后 LangGraph 记录失败 task checkpoint，`ainvoke(None)` 原生只重跑该节点（方案 1 生效）。
- 影响：改动所有 agent 的错误契约 + 依赖 `error` 字段的 routers（`should_plan` 用 error+retry_count
  重试 trend_scout）。**范围较大，PRD 已标"暂不做"边界外**。

### 方案 4（不推荐）：`aupdate_state` 仅清 error 不带 as_node
- 多 task pending 时抛 InvalidUpdateError；清 error 不触发 task（触发基于 version）。脆弱。

### 不要做
- `as_node=visual_designer`：标记其完成 → 跑 review_gate，**跳过**重试（错方向）。
- `as_node=content_strategist`/`as_node=orchestrator`：重跑后继链（当前 bug 机制）。

## 验收影响（对 PRD 验收条目的重新评估）
- "visual_designer 失败后 resume，图从 visual_designer 重试而非回退 content_strategist"：
  修法 A 已消除"回退 content_strategist"（改为回退 copywriter），但未做到"从 visual_designer 重试"。
  要满足此条验收，需实施方案 2。
- "不再有 running/stale 抖动循环"：抖动来自 `_on_task_done` + 反复 resume 创建新 task
  （`_runner.py:305` finally pop），与 resume 恢复点无直接关系，需另查。

## 待办（移交实施任务，需真机）
- [ ] **一行运行时验证** `Command(goto="visual_designer")` 能否作外部 ainvoke 输入
      （构造一个停在 review_gate/error 的 thread，ainvoke(Command(goto=...)) 看是否只重跑目标节点）
- [ ] 真机抓取 error 终态实际 `state.tasks` / `state.next` / `current_agent` / `phase`
      （确认 `phase=ERROR` 终态的真实成因——哪个非 agent 节点抛的）
- [ ] 验证 `aupdate_state({"error": None, "phase": ...})` 无 as_node 在该状态下是否抛
      InvalidUpdateError
- [ ] 若方案 2 验证通过，分离 paused/error/terminal 三条 resume 路径：
      error/stale 路径用 `Command(goto=current_agent)`，paused/terminal 保留现有逻辑

## 源码引用（LangGraph，main/1.x）
- `pregel/_loop.py`：失败 task writes 为空、不 bump、resume 重执行
  https://raw.githubusercontent.com/langchain-ai/langgraph/main/libs/langgraph/langgraph/pregel/_loop.py
- `pregel/main.py`：ERROR pending write、`state.next` 含失败节点
  https://raw.githubusercontent.com/langchain-ai/langgraph/main/libs/langgraph/langgraph/pregel/main.py
- `pregel/_retry.py`：retry 耗尽 re-raise
  https://raw.githubusercontent.com/langchain-ai/langgraph/main/libs/langgraph/langgraph/pregel/_retry.py
- `Pregel.update_state` 文档："as if they came from node as_node"
  https://reference.langchain.com/python/langgraph/pregel/main/Pregel/update_state

## 本仓库关键文件
- `backend/core/base_agent.py:144-161` — 吞所有异常返回 error dict
- `backend/agents/nodes/visual_designer.py` — 失败时强制 phase="reviewing"
- `backend/graph/routers.py:11-22,253-262` — `_check_terminal` 仅认 phase=ERROR；visual_designer→review_gate
- `backend/graph/error_handling.py` — 仅 RetryPolicy，无 error_handler
- `backend/api/routes/_runner.py:172-183`(`_get_as_node`→默认 orchestrator)、`:285-300`(error 路径 aupdate_state)
- `backend/api/routes/workflow.py:948-975`(resume 路径 aupdate_state)、`:114-142`(`_resume_phase_for_next_nodes`)
- `backend/state/machine.py:29-128`(`derive_status`)
