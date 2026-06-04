# feat: show Ripple simulation progress on frontend

## Goal

在 Ripple 模拟运行期间，RipplePanel 实时展示执行进度（当前 Wave/总 Wave、百分比、耗时），完成后平滑过渡到结果展示。

## Requirements

* 后端在 `wait_for_completion()` 每次轮询到新状态时，通过 EventBus 推送 `ripple.progress` 事件
* 前端接收 `ripple.progress` 事件，RipplePanel 内部展示进度
* 进度展示包含：当前 Wave / 总 Wave、百分比进度条、已用时间
* Ripple 不可用（disabled）时不显示进度区域
* 模拟完成后进度区域平滑过渡到结果卡片

## Acceptance Criteria

* [ ] Ripple 模拟运行期间，RipplePanel 显示 Wave 进度 + 百分比条 + 耗时
* [ ] 进度通过 WebSocket 实时推送（复用现有 EventBus，~10s 间隔）
* [ ] 模拟完成后进度区域过渡到结果展示
* [ ] Ripple disabled 时进度区域不显示
* [ ] 中英文 locale 更新

## Definition of Done

* Lint / typecheck green
* 中英文 locale 更新
* 手动验证：模拟运行时可见进度，完成后过渡到结果

## Technical Approach

### 后端改动

1. **backend/realtime/events.py**: 新增 `RIPPLE_PROGRESS` EventType
2. **backend/services/ripple_service.py**: `wait_for_completion()` 每次轮询后 emit `RIPPLE_PROGRESS` 事件，携带 `{ job_id, status, current_wave, total_waves, progress, elapsed_seconds }`
3. **backend/state/substates.py**: RippleSubState 新增 `progress` 可选字段

### 前端改动

1. **frontend/src/types/workflow.ts**: 新增 `RippleProgress` 类型 + `ripple_progress` 状态字段
2. **frontend/src/realtime/events.ts**: EventType 新增 `RIPPLE_PROGRESS`
3. **frontend/src/stores/workflow.ts**: 处理 `ripple.progress` 事件，更新 `ripple_progress` 状态
4. **frontend/src/components/RipplePanel.vue**: 新增进度展示区域（Wave 计数 + 进度条 + 耗时），有结果时过渡到结果卡片
5. **frontend/src/locales/{zh-CN,en}.json**: 新增进度相关文案

### 数据流

```
RippleService.wait_for_completion()
  → 每 10s poll get_simulation_status()
  → 每次 poll 后 EventBus.emit(RIPPLE_PROGRESS, {job_id, current_wave, total_waves, progress, elapsed_seconds})
  → WebSocket → 前端
  → workflow store 更新 ripple_progress
  → RipplePanel 渲染进度
```

## Out of Scope

* 取消单个 Ripple 模拟
* 前端直接轮询 Ripple API
* Ripple 模拟结果内容改动

## Technical Notes

* Ripple API status 响应包含: status, progress, current_wave, total_waves
* EventBus 已有 WebSocket 通道基础设施，只需新增事件类型
* 进度展示复用 RipplePanel 现有位置，无结果时显示进度，有结果时过渡
