# 端到端用户体验优化计划

**日期:** 2026-05-30  
**范围:** XHS Growth Agent 前端、后端 API、LangGraph 工作流、实时事件、审核发布链路、分析闭环  
**目标:** 从用户完整旅程出发，优先修复影响信任感和任务完成率的断链，再提升启动、审核、发布、分析、恢复等关键流程的效率和可解释性。

---

## 一、现状判断

当前工程已经具备较完整的体验基础：

- 前端包含登录、启动页、Dashboard、Review、Analytics、History。
- 已有离线恢复、错误边界、Toast、快捷键、新手引导、多语言、骨架屏等组件。
- 后端具备统一响应、错误分类、工作流历史、审核中断、实时事件和系统健康检查。

主要 UX 风险不是组件缺失，而是端到端状态一致性不足。用户可能看到页面元素很丰富，但无法确认系统是否真的在执行、是否等待自己操作、审核后的发布行为是否与界面选择一致。

---

## 二、关键问题

### 1. 实时状态链路不可信

后端启动工作流时写入 `session_id`，但多个节点通过 `state.get("thread_id")` 发送实时事件：

- `backend/api/routes/workflow.py` 初始化状态只包含 `session_id`
- `backend/agents/nodes/orchestrator.py` 使用 `state.get("thread_id")`
- `backend/agents/nodes/trend_scout.py`、`content_strategist.py`、`copywriter.py` 等也使用 `thread_id`

前端 WebSocket handler 又把完整 `WsMessage` 当业务 payload 读取：

- `frontend/src/stores/workflow.ts` 中 `onEvent(...)` 回调直接读取 `p.thread_id`、`p.new_phase`、`p.data_type`
- 实际消息结构是 `{ event_type, thread_id, payload, timestamp, seq }`

结果：Dashboard、Review、实时内容更新可能依赖轮询兜底，实时提醒容易失效。

### 2. 审核与发布决策不一致

Review 页面有 dry-run toggle，但当前只是本地 UI 状态，没有提交到后端决策：

- `frontend/src/views/Review.vue` 中 `publishDryRun` 只控制弹窗显示和警告
- `reviewStore.submitDecision(decision, feedback)` 未携带 dry-run 发布选择
- 后端 `ReviewDecision` 也不接收发布选项

同时，审核路由中 `needs_revision` 和 `rejected` 都会进入修订分支，拒绝语义不够清晰。

### 3. Dashboard 进度和状态来源分散

Store 保存 `progressPercent`，Dashboard Header 和 Timeline 又各自按 phase 重新计算进度。用户看到的百分比、剩余时间、阶段状态可能不一致。

### 4. Analytics 周期切换口径不完整

`analyticsStore.setPeriod()` 只刷新 growth report，不刷新 performance 和 cost，页面指标可能混用不同周期的数据。

### 5. 工具型产品的信息密度和控制台感不足

当前界面已有大量装饰性渐变、光效和卡片。对于增长自动化工作台，后续应更偏向清晰、可扫描、可恢复、低误操作的操作台体验。

---

## 三、优化原则

1. **先修可信度，再修美观。** 用户必须能相信系统状态、下一步动作和发布结果。
2. **每个长耗时步骤都要有状态、原因、下一步。** 不只显示 loading，还要说明当前 agent、已完成产物和预计等待。
3. **每个风险操作都要显式确认。** 真实发布、取消、删除、拒绝都要有明确后果。
4. **实时优先，轮询兜底。** WebSocket 是主通道，轮询只用于恢复和校准。
5. **分析必须回到行动。** Analytics 不只是报表，要能直接生成下一轮内容策略。

---

## 四、P0：修通端到端状态链路

### 目标

保证工作流启动、阶段变化、内容产出、审核等待、完成和错误状态能稳定、实时、可恢复地反映到前端。

### 任务

- [ ] 在工作流 initial state 中同时写入 `thread_id` 和 `session_id`，并统一后续节点使用 `session_id` 或 `thread_id` 的规则。
- [ ] 修复所有 realtime emit 的 `thread_id` 来源，覆盖 orchestrator、trend_scout、content_strategist、copywriter、visual_designer、publisher、analyst、review_gate。
- [ ] 前端 WebSocket handler 统一接收 `WsMessage`，先校验 `msg.thread_id`，再读取 `msg.payload`。
- [ ] 为 `workflow.phase_changed`、`workflow.data_updated`、`review.pending` 建立前后端契约测试。
- [ ] 启动工作流成功后立即连接 WebSocket 并订阅当前 thread。
- [ ] History 恢复某个 workflow 时自动刷新状态并重新订阅 thread。
- [ ] WebSocket 重连后使用 `get_missed` 补齐丢失事件，并在前端显示“已恢复实时同步”。

### 验收标准

- 启动工作流后，Dashboard 在 1 秒内显示当前阶段。
- 进入审核阶段后，Review 导航和 Toast 都能稳定提醒用户处理。
- 断开 WebSocket 再恢复后，不丢失阶段变化和审核提醒。
- `workflow.data_updated` 能即时更新 Dashboard 上的趋势、策略、文案和视觉数据。

---

## 五、P0：修正审核与发布链路

### 目标

用户在 Review 页做出的“批准、修改、拒绝、试运行、真实发布”必须与后端行为完全一致。

### 任务

- [ ] 扩展 `ReviewDecision`，支持 `publish_options`，至少包含 `dry_run` 和 `auto_publish`。
- [ ] Review 页提交 approved 时携带 `publishDryRun`。
- [ ] 后端审核恢复时把发布选项写入 workflow state。
- [ ] Publisher 读取 workflow state 中的发布选项，优先于默认 settings。
- [ ] 明确 `rejected` 语义：拒绝后结束工作流并进入历史，而不是进入修订循环。
- [ ] `needs_revision` 才进入 revise_content，并保存当前版本到 version history。
- [ ] 审核提交后根据实际 next phase 展示确认结果：已进入发布、已进入修订、已拒绝归档。
- [ ] 发布前弹窗展示账号、真实/试运行、内容摘要、图片状态、失败恢复入口。

### 验收标准

- 用户选择 dry-run 后不会触发真实发布。
- 用户关闭 dry-run 后必须看到真实发布警告，并且后端实际按真实发布处理。
- 拒绝内容后工作流状态为 rejected/cancelled/completed 中明确的一种，不再继续改写内容。
- 修改意见进入下一轮文案生成，并能在版本历史中看到前后变化。

---

## 六、P1：优化首轮启动体验

### 目标

新用户首次进入系统时，能在不读 README 的情况下知道能不能启动、启动后会发生什么、当前是否会真实发布。

### 任务

- [ ] 将 Home 页健康检查升级为“启动前检查清单”。
- [ ] 区分必需项和可选项：LLM Provider 必需，XHS 凭证决定是否真实发布，Ripple 可选。
- [ ] 缺少 XHS 凭证时默认 preview/dry-run，并在确认弹窗明确说明。
- [ ] 表单保留垂类、主题、起始阶段，但提供推荐默认配置。
- [ ] 支持从 Analytics 传入 topic 后，在表单中清楚标记“来自分析推荐”。
- [ ] 首次登录后进入启动页；已有运行中 workflow 时进入 Dashboard 并提示可恢复。

### 验收标准

- 从登录到启动 dry-run workflow 不超过 60 秒。
- 缺少配置时用户能知道缺什么、影响什么、还能做什么。
- 点击 Analytics 热门话题后能带 topic 回到启动页并启动新工作流。

---

## 七、P1：让 Dashboard 成为可信控制台

### 目标

Dashboard 不只是展示进度，而是成为工作流控制和恢复的中心。

### 任务

- [ ] 统一进度来源，优先使用后端 `progress_percent`，前端只做缺省 fallback。
- [ ] Header、Timeline、ProgressPhase 使用同一个 store 字段。
- [ ] 当前阶段显示业务文案，而不是直接展示 `scouting`、`creating` 等内部枚举。
- [ ] 根据状态突出唯一主动作：
  - idle: 启动工作流
  - running: 查看进度/暂停
  - reviewing: 去审核
  - error: 重试/恢复/重新配置
  - completed: 查看分析/基于结果再创作
- [ ] 展示状态来源：实时同步、轮询刷新、历史快照。
- [ ] 增加 agent 级别执行详情：开始时间、耗时、失败原因、重试次数。

### 验收标准

- 同一页面所有进度数字一致。
- 等待审核时页面上最醒目的按钮是“去审核”。
- 错误状态必须有可操作恢复按钮，不只显示错误文本。

---

## 八、P1：打通 Analytics 到再创作闭环

### 目标

让分析页从“结果报表”变成“下一轮增长输入”。

### 任务

- [ ] `setPeriod()` 同步刷新 report、performance、cost，或前端按统一 period 过滤所有指标。
- [ ] 所有指标明确绑定 account 和 period。
- [ ] 增加指标：单篇成本、单次互动成本、最佳发布时间、失败率、平均审核轮次。
- [ ] 将热门话题、低表现原因、最佳标题模式转化为可点击的“新建工作流”入口。
- [ ] 从 Analytics 启动时预填 topic、niche、建议发布时间和内容角度。
- [ ] 空数据时展示下一步建议：先完成一次 dry-run 或发布工作流。

### 验收标准

- 切换周期后，帖子数、互动率、图表、洞察口径一致。
- 分析页至少有一个明确动作能启动下一轮内容生成。
- 没有数据时不是空表格，而是可执行的引导。

---

## 九、P2：界面、可访问性和移动端打磨

### 目标

让界面更像高频操作工具，降低视觉噪声，提升扫描效率和移动端可用性。

### 任务

- [ ] 收敛全局背景装饰和重复光效，减少对内容的干扰。
- [ ] 统一卡片圆角、阴影、边框和按钮状态。
- [ ] Dashboard 和 Review 页面提高信息密度，减少嵌套卡片。
- [ ] 小屏下将左侧导航改为顶部栏或抽屉导航。
- [ ] 所有表单和弹窗补齐焦点态、键盘操作和 aria label。
- [ ] 表格支持空状态、长标题截断、排序和可读时间格式。
- [ ] 所有 destructive action 增加强确认和撤销/恢复说明。

### 验收标准

- 375px 宽度下能完成启动、查看状态、审核三条主流程。
- 所有关键按钮文字不溢出、不换行错位。
- 键盘用户能完成登录、启动、审核和退出弹窗。

---

## 十、测试计划

### 后端测试

- [ ] `tests/unit/realtime/test_events.py` 扩展 payload 契约。
- [ ] `tests/unit/realtime/test_event_bus.py` 覆盖 missed events。
- [ ] `tests/integration/test_api_routes.py` 覆盖 review publish options。
- [ ] 增加 workflow start -> realtime event -> review pending 的集成测试。

### 前端测试

- [ ] `frontend/tests/stores/workflow.spec.ts` 覆盖 WebSocket message 解包。
- [ ] `frontend/tests/stores/review.spec.ts` 覆盖 dry-run publish option。
- [ ] `frontend/tests/stores/analytics.spec.ts` 覆盖 period 切换后的统一刷新。
- [ ] `frontend/tests/components` 补齐 Dashboard 主动作状态测试。

### E2E 测试

建议新增 Playwright 测试覆盖：

- [ ] 登录后启动 dry-run workflow。
- [ ] Dashboard 实时收到 phase change。
- [ ] 收到 review.pending 后进入 Review 页。
- [ ] 提交 needs_revision 后回到 Dashboard 并产生版本历史。
- [ ] 从 History 恢复 workflow 并重新订阅实时状态。
- [ ] Analytics 点击热门话题回到 Home 并预填 topic。

---

## 十一、实施顺序

### 里程碑 1：状态可信度

优先完成 P0 状态链路修复。没有这个基础，后续页面优化会建立在不可靠数据上。

交付物：

- 统一 thread id。
- WebSocket payload 解包修复。
- 前后端实时事件测试。
- Dashboard/Review 实时更新稳定。

### 里程碑 2：审核发布一致性

完成 Review 决策、dry-run/真实发布、拒绝/修订语义的端到端一致性。

交付物：

- ReviewDecision 扩展。
- Publisher 使用发布选项。
- 拒绝和修订路由分离。
- 审核提交后的明确反馈。

### 里程碑 3：启动和控制台体验

优化 Home 和 Dashboard，使用户能清楚启动、监控和恢复任务。

交付物：

- 启动前检查清单。
- 统一进度来源。
- Dashboard 主动作区。
- 状态来源和 agent 详情。

### 里程碑 4：分析闭环和界面打磨

让 Analytics 能指导下一轮创作，并收敛视觉风格。

交付物：

- Analytics 周期口径统一。
- 洞察到新工作流入口。
- 移动端导航。
- 可访问性和视觉一致性修复。

---

## 十二、成功指标

- 工作流阶段变化 1 秒内反映到 Dashboard。
- 审核等待提醒成功率 100%。
- WebSocket 断线恢复后不丢事件。
- dry-run/真实发布行为与 UI 选择完全一致。
- 用户从 Analytics 发起下一轮工作流的路径不超过 2 次点击。
- 核心 E2E 测试覆盖登录、启动、实时进度、审核、历史恢复、分析再创作。

---

## 十三、风险与注意事项

- 不要先做大规模视觉重构。当前最大问题是状态和语义一致性。
- 不要让前端继续推断复杂工作流状态。后端应提供明确 phase、status、progress、next_action。
- 发布相关变更必须默认保守，缺少凭证或状态不明确时强制 dry-run。
- 历史数据和运行中 graph state 需要明确区分，否则用户会误以为已恢复实时执行。
- 变更 API 契约后必须同步 OpenAPI、前端类型和合同测试。

