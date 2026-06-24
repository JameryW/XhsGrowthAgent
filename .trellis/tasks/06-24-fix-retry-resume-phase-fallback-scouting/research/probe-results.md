# 探针结果：error 终态 resume 行为（真机验证）

探针：`tests/integration/test_resume_error_probe.py`。本地确定性复现——
`compile_graph_dev`（真实图）+ monkeypatch `visual_designer.execute` 抛错（live `__call__`
包成 `AgentError`）+ `Command(goto="visual_designer")` 驱动。conftest 已 mock get_model/Ripple。

## ERROR CHECKPOINT（goto visual_designer + raise 后）
```
vd_call_count = 2          ← RetryPolicy(max_attempts=2) 重试 2 次后抛 AgentError ✓ 方案3生效
next          = ['visual_designer']   ← 非空！失败节点在 next 里（推翻 PRD"next 为空"前提）
tasks         = [orchestrator(no err), visual_designer(has_error)]
phase         = scouting
current_agent = orchestrator
_last_node    = None       ← 确认从未写入
```

## 三组 resume 对照

| 策略 | as_node / 输入 | vd 重跑? | 落点 | caught |
|---|---|---|---|---|
| **A 原生** `ainvoke(None)` | 无 as_node | ✅ 是（+2 次） | 仍 `next=['visual_designer']` | AgentError（再次失败） |
| **B 当前路径** `aupdate_state(as_node=_get_as_node)+ainvoke(None)` | **orchestrator** | ❌ 否（0 次） | `next=[]`, current_agent=**trend_scout** | None（跑去 trend_scout 了） |
| **C 方案2** `ainvoke(Command(goto=visual_designer))` | goto | ✅ 是（+2 次） | 仍 `next=['visual_designer']` | AgentError |

## 结论（真因确认）

### 1. 方案 3 已上线且工作正常
vd 重试 2 次后抛 `AgentError` 传到 ainvoke —— re-raise + RetryPolicy 链路通。

### 2. 真因 = resume 路径 `_get_as_node` 取错 task
- error checkpoint 的 `state.tasks = [orchestrator, visual_designer]`。
- `_get_as_node` 取 `state.tasks[0].name` = **orchestrator**（第一个，不是出错的那个）。
- `aupdate_state(as_node=orchestrator)` → 视 orchestrator 刚完成 → `ainvoke` 推进到
  orchestrator 的后继 = **trend_scout** → **重启 scouting→content_strategist→Ripple 链**。
- 这正是 PRD 症状"每次 resume 把 phase 设成 scouting，图从 content_strategist 重跑 + 30min Ripple"。
- visual_designer **完全不重跑**（vd_ran=0）—— 不是"重试失败节点"，而是"从头重来"。

### 3. 方案 1（原生 ainvoke None）可行
A 组：`ainvoke(None)` 不写 as_node → **只重跑 visual_designer**。但 raw checkpoint 有
2 个 task（orchestrator+visual_designer），若要先 `aupdate_state` 清 error 不带 as_node
会抛 InvalidUpdateError（多 task 歧义）。故方案1 需"完全不动 aupdate_state，直接 ainvoke(None)"。

### 4. 方案 2（Command goto）可行
C 组：`ainvoke(Command(goto="visual_designer"))` → **只重跑 visual_designer**。需先识别
失败节点名 = `state.tasks` 中 `.error` 非空的 task 名（或 `current_agent`）。

### 5. _last_node 永远 None（确认）
`_get_as_node` 的 `_last_node` 回退分支永不命中；实际回退到 `tasks[0]`。

## 修法 B 定论（最终实施）

**核心修法**：error/stale 重试路径不再用 `aupdate_state(as_node=_get_as_node(state))`
推进后继。改为 **原生 `ainvoke(None)`**（探针 resume-A 已验证只重跑失败节点），且
**完全不调 `aupdate_state`**——多 task checkpoint 上即使不带 as_node 也会抛 InvalidUpdateError。

为何选 `ainvoke(None)` 而非 `Command(goto=失败节点)`（初版方案2）：
- 探针 resume-A（`ainvoke(None)`，不写 as_node）**已证明只重跑 visual_designer**（vd_ran +2）。
  LangGraph 原生 error-resume：失败 task 的 writes 为空、versions_seen 不 bump，resume 重执行。
- `Command(goto)` 需 `_failed_node` 识别失败节点，但探针显示该信号在本地 goto-seed
  复现中不可靠（tasks[].error / next 都可能空），且有 `else` 回退到 buggy as_node 路径的隐患。
- workflow-state spec 明确：stale/error resume 用 `ainvoke(None)`（line 664）。
- 故最终实施：error/stale 路径**跳过 `aupdate_state`**，直接 `_start_resume_task`（内部
  `ainvoke(None)`）。paused/terminal-restart 路径保留原 `as_node=_get_as_node` 逻辑。

**关键**：bug 的根因不是 resume 输入，而是 `aupdate_state(as_node=_get_as_node(state))`
这一步——`_get_as_node` 取 `tasks[0]=orchestrator`，`as_node=orchestrator` 推进到 trend_scout。
去掉 aupdate_state 调用即可让原生 ainvoke(None) 重跑失败节点。

## 推翻的前提
- PRD"next_nodes 为空" → **错**：error 终态 next 含失败节点。
- PRD"BaseAgent 吞异常" → **错**：基于死重复 `core/base_agent.py`；live `agents/base.py` 已 re-raise。
- 初版调研"`_last_node==content_strategist`" → **错**：`_last_node` 从未写入，回退到 tasks[0]=orchestrator。
- 修法 A 的副作用分析（"回退到 copywriter"）→ 部分修正：实际 _get_as_node 返回 orchestrator，
  resume 推进到 trend_scout（不是 copywriter）。修法 A 改的是 prev_phase 显示，没动 as_node，
  所以真实 resume 仍走 trend_scout 重跑链。
