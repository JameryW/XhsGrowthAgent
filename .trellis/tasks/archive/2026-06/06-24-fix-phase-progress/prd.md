# Fix: 工作流 status/phase/progress 不同步

## 现象
工作流停在 interrupt gate（如 blogger_gate / draft_gate）时，不同读取路径返回不一致的 phase/progress：
- 列表/缓存读 DB（由 `_run_graph_and_persist` 写入）：phase=`planning`, progress=20
- 详情 `/status` 现算（`derive_status` + `state.values.get("phase")`）：phase=`creating`, progress=40
- DB status 列有时滞后于图实际中断点（一度显示 `awaiting_ripple_decision`，实际在 draft_gate）

证据：thread `783d907e` 停在 blogger_gate，DB 曾显示 `awaiting_ripple_decision/planning/20`，现算显示 `awaiting_blogger_selection/creating/40`。

## 根因
`backend/api/routes/_runner.py:_run_graph_and_persist` 在 `ainvoke` 因 interrupt 返回后：

- `:234` `final_phase = result.get("phase", "unknown")` —— 取的是**最后一个执行节点返回的 state 更新**里的 phase，而非图实际中断时的真实 phase。
- 图停在 `blogger_gate`（interrupt_before）时，最后执行节点（路由/orchestrator）返回 phase 可能仍是 `planning`，于是 `progress = get_progress("planning") = 20`。
- 而 `derive_status` 正确返回 `AWAITING_BLOGGER_SELECTION`（next 含 blogger_gate），但 phase 写入的是 `planning`。
- `/status` 现算用 `state.values.get("phase")`（真实 = creating）→ progress=40，并回写 DB 修正。两条路径 phase 来源不同 → 不同步。

## 修法（最小）
`_run_graph_and_persist` 的 `final_phase` 改为取**图真实状态** `snapshot.values.get("phase")`，与 `derive_status` 用同一个 snapshot 保持一致：
```python
values = snapshot.values or {}
final_phase = values.get("phase", "unknown")
has_error = values.get("error")
```
fallback：snapshot.values 无 phase 时再用 result。错误分支同理用 snapshot。

## 验收
- 工作流停在任意 gate 时，DB 的 phase/progress 与 `/status` 现算一致
- `_run_graph_and_persist` 写入的 phase 来自 snapshot.values，不再取 result.get("phase")
- 现有 runner 相关单测全绿；新增针对 phase 一致性的自检测试
