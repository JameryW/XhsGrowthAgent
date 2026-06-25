# Fix: retry/resume 循环卡死 + phase fallback scouting

## 现象
thread `783d907e` visual_designer 报讯飞 NotEnoughCvError 后，retry/resume 陷入循环：每次 resume 把 phase 设成 scouting（progress 倒回 10%），图从 content_strategist 重跑，又触发讯飞 500 + 30 分钟 Ripple 仿真，永远卡在这个循环。status 在 running/stale 间抖动，"重试后进度不对"。

## 根因链（已定位）

### 1. retry phase fallback 错误（workflow.py:949-957）
```python
if (can_retry_error or can_resume_stale) and next_nodes:
    prev_phase = _resume_phase_for_next_nodes(next_nodes, ...)  # 正确：按 next 推断
else:
    prev_phase = state.values.get("prev_phase") or WorkflowPhase.SCOUTING  # fallback
```
visual_designer 失败后图处于 error 终态、`next_nodes` 为空 → 走 else → `prev_phase` 为 None → fallback `SCOUTING`。但图 checkpoint 实际恢复点是 content_strategist，retry 后图从那继续，phase(scouting) 与实际执行点(content_strategist)不一致 → progress 显示 10% 但实际在跑 content_strategist。

### 2. resume 盲目重跑已失败节点
`_start_resume_task` 用 `None` 输入 resume 图（workflow.py:177），图从 checkpoint 的 pending task（content_strategist）继续。但 content_strategist 内含完整 Ripple 仿真（max_wait=1800s），每次 resume 重跑都要等 30 分钟，且若讯飞仍 500 则再次失败 → 循环。

### 3. 讯飞对特定 prompt 持续 NotEnoughCvError（外部因素，本次不改路由）
astron-code-latest 是讯飞代码模型，对部分营销/策略 prompt 返回 500。手动简单复现成功，但生产中 content_strategist/visual_designer 的实际 prompt 持续失败。用户选择保持讯飞路由，故此条不改，但它是循环的触发源。

### 4. 状态抖动机制
- 后台 task 跑 content_strategist → 500 → retry 耗尽 → AgentError → task 结束 → `_on_task_done` 把 DB 改 stale
- `_run_graph_and_persist` finally pop `_background_tasks[thread_id]`
- 但前端/用户看到非终态又调 resume → 创建新 task → 又跑 content_strategist → 又 500 → 循环
- 每次 resume 间，has_active 时真时假 → status 在 running/stale 抖动

## 修法（待 brainstorm 确认范围）

### 修法 A：retry phase fallback 用图实际恢复点（最小，必做）
error/stale 重试且 next 为空时，不应盲目 fallback scouting。应从 checkpoint 的 pending task 或 _last_node 推断真实 phase。例如查 `snapshot.tasks` 或最后执行节点，映射到对应 phase。

### 修法 B：resume 不重跑已成功的耗时节点（范围较大）
content_strategist 已产出 content_plan 后，因下游 visual_designer 失败而 resume 时，不应从头重跑 content_strategist（含 Ripple）。理想：图应从 visual_designer 重试，而非回退 content_strategist。这涉及 checkpoint 恢复点语义——需要确认 LangGraph 在 error 后 resume 的实际行为，可能需要显式重置 error 并从失败节点继续。

### 修法 C：LLM 瞬时错误的应用层降级（可选）
讯飞 500 时，对非关键节点返回降级结果而非让整个节点失败。但这与"保持讯飞"决策冲突面较大，列为可选。

## 倾向
先做修法 A（phase fallback，确定性 bug，低风险）+ 调研修法 B 的可行性（resume 恢复点）。修法 C 暂不做。

## 验收
- error/stale 重试后 phase 反映图实际恢复点，不再 fallback scouting
- visual_designer 失败后 resume，图从 visual_designer 重试而非回退 content_strategist（若修法 B 可行）
- 不再有 running/stale 抖动循环
- 现有 retry/resume 测试全绿，新增 phase fallback 回归测试
