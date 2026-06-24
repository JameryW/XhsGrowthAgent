# Fix: content_versions 多轮循环累加导致 6 个版本

## 现象
thread `ed6fd1fe` 出现 6 个版本文案（A/B/C 重复两轮）。choice_gate 用 version_id 首次匹配，第二轮 A/B/C 永远选不到，选择语义损坏。

## 根因（已定位）
工作流支持设计内的多轮增长循环：`analyst → orchestrator → content_strategist → ripple_gate → copywriter → ... → version_generator`。每轮循环 version_generator 都生成 A/B/C 三版本。

- `backend/state/schema.py:91` `content_versions: Annotated[list, _append_list]` —— reducer 是 append 累加
- `backend/agents/version_generator.py:109` 每轮返回 `"content_versions": versions`（3 个新版本），append 到现有列表 → 每轮 +3
- `backend/agents/nodes/optimization/choice_gate.py:49-52` 用 `next(v for v in versions if v.version_id == selected)` 取**第一个**匹配，6 个版本里两套 A/B/C，选 "A" 永远命中第一轮的 A

证据（postgres）：`version_generator` 在两个不同 checkpoint（`1f16edbc`、`1f16f9b4`）各写过 3 条版本，共 6 条，version_id A/B/C 各重复两次。

## 修法（最小）
版本是"当前这一轮的候选"，历史轮次无意义 → 每轮 replace 而非 append。

方案：`content_versions` 的 reducer 从 `_append_list` 改为 `replace`（state/reducers.py 已有 `replace`）。

影响面核查（实施时必须确认）：
- `review.py:121` 提交修改版 `content_versions = [version_entry]` —— replace 语义下仍正确（写一个替换全部，符合"修改版只留这一个"）。但需确认 review 修改版流程是否依赖 append 累加历史。
- `version_generator.py` 每轮返回完整 3 版本，replace 下正好替换为当前轮。
- choice_gate 读 `content_versions` —— replace 后只剩当前轮 3 个，version_id 唯一，`next()` 匹配正确。
- 任何依赖"版本历史"的读取（如 version_history 展示）需确认是否要保留历史 —— 若前端展示需要历史，则改 choice_gate 去重取最新轮而非改 reducer。

## 备选方案（若历史有意义）
保留 append，但：
- version_id 带轮次后缀（如 `A_2`）保证全局唯一
- choice_gate 只在最新轮里匹配

倾向方案 A（replace），最简且符合"版本是当前轮候选"语义。实施前确认前端 version_history 展示需求。

## 验收
- 多轮循环后 content_versions 只保留当前轮的 A/B/C（3 个），不再累加
- choice_gate 选择 version_id 正确命中当前轮
- review 修改版提交流程不受破坏
- 现有 version_generator / choice_gate / review 相关测试全绿，新增多轮累加回归测试
