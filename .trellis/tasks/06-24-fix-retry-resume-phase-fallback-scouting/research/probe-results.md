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

## 修法 B 定论（待用户确认后实施）

**核心修法**：error/stale 重试路径不再用 `aupdate_state(as_node=_get_as_node(state))`
推进后继。改为：
- 识别失败节点 = `state.tasks` 中带 `.error` 的 task 名（回退 `current_agent`）。
- resume 用 `ainvoke(Command(goto=<失败节点>))`（方案2，已验证只重跑该节点）。
- 清 error：可在 goto 前 `aupdate_state({error:None}, as_node=<失败节点>)` 或依赖节点
  成功后 `__call__` 自清 `error=None`（live base.py:201）。

**次要修法**：`_get_as_node` 取 `tasks[0]` 的逻辑本身有缺陷（应优先取带 error 的 task），
但若 resume 路径改用 goto 则 _get_as_node 在该路径不再被调用；其 paused 路径用途需另查。

## 推翻的前提
- PRD"next_nodes 为空" → **错**：error 终态 next 含失败节点。
- PRD"BaseAgent 吞异常" → **错**：基于死重复 `core/base_agent.py`；live `agents/base.py` 已 re-raise。
- 初版调研"`_last_node==content_strategist`" → **错**：`_last_node` 从未写入，回退到 tasks[0]=orchestrator。
- 修法 A 的副作用分析（"回退到 copywriter"）→ 部分修正：实际 _get_as_node 返回 orchestrator，
  resume 推进到 trend_scout（不是 copywriter）。修法 A 改的是 prev_phase 显示，没动 as_node，
  所以真实 resume 仍走 trend_scout 重跑链。
