# Fix: Ripple 进度卡 95%（仿真超时未收尾进度条）

## 背景
Ripple 仿真超时（跑满 `max_wait=1800s`）的 thread，前端进度条永久卡在 95%，即使工作流已正常推进（如已进入 `awaiting_ripple_decision`）。

## 根因
`backend/services/ripple_service.py` `submit_and_wait` 轮询循环：
- SSE 无新鲜数据时用时间估算进度，封顶 `min(0.95, elapsed/max_wait)`（:797）→ 一直顶 0.95
- 跑满 max_wait 后 `raise RippleTimeoutError`（:832），`finally` 只 cancel sse_task（:833-839），**不发终态进度事件、不清 `_progress_store`**
- `_emit_progress` 仅在 `completed/done/finished` 时 pop store 条目（:312-313），`timed_out` 不在白名单
- 残留条目被 `get_thread_progress` 永久返回 → status API 永远 95% → 前端永远 95%

证据：thread `xhs_..._783d907e` 的 `ripple_progress` 残留 `job_d52a07c4a24c` {progress:0.95, status:"running", elapsed:1799.5s}，但工作流已停在 awaiting_ripple_decision（ripple_prediction 已有结果 job_5034bc6c1a6e, viral 0.28）。

## 修法（最小）
1. **超时前发终态进度**（:832 之前）：`_emit_progress(job_id, progress=1.0, status="timed_out", ...)` 
2. **扩展 store pop 白名单**（:312）：`completed/done/finished` 之外也认 `timed_out/timeout/failed/error`，确保终态条目被清理
3. **`get_thread_progress` 防御性过滤**（:320）：对 status 仍为 "running" 但 elapsed 远超 max_wait 的陈旧条目视为过期，从返回中剔除（双保险，应对历史残留）

## 验收
- 超时的 thread，status API 的 `ripple_progress` 不再残留 0.95/"running"
- 工作流已推进到下一阶段时，前端进度跟随 `progress_percent`（基于 phase），不被残留 ripple_progress 钉在 95%
- 现有 ripple_service 单测全绿
