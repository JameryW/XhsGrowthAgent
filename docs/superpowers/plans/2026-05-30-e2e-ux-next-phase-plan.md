# 端到端 UX 下一阶段优化计划

**日期:** 2026-05-30  
**范围:** XHS Growth Agent 前端、后端 API、实时事件、审核发布链路、分析闭环、移动端与可访问性  
**目标:** 在已有加载、错误恢复、离线、引导、实时同步和审核发布能力之上，把完整用户旅程打磨成可信、低误操作、可恢复、能闭环的增长工作台。

---

## 一、当前基线

现有工程已经完成了多项 UX 基础能力：

- 加载态、骨架屏、阶段进度、错误恢复、离线提示、新手引导、快捷键和移动端 Tab 已具备。
- 工作流启动时已经同时写入 `session_id` 和 `thread_id`。
- 前端 WebSocket handler 已按 `{ event_type, thread_id, payload, timestamp, seq }` 结构读取业务数据。
- WebSocket 客户端已有重连、重新订阅和 `get_missed` 补传机制。
- Review 已支持提交 `publish_options.dry_run`，Publisher 会优先读取 state 中的发布选项。
- `rejected` 已明确结束工作流，不再进入修订循环。
- Analytics 热门话题已经可以跳转回首页并预填 topic。
- Dashboard 已展示状态来源，并优先使用后端 `progress_percent`。

相关基线文档：

- `docs/superpowers/plans/2026-05-30-end-to-end-ux-optimization-plan.md`
- `docs/superpowers/plans/2026-05-30-e2e-ux-implementation.md`
- `docs/superpowers/plans/2026-05-30-optimization-execution-summary.md`

下一阶段不应继续堆叠组件，而应围绕端到端任务完成率、状态可信度和误操作防护做收敛。

---

## 二、P0：端到端可信链路

### 目标

确保用户从启动到分析再创作的主路径中，每一步都能知道系统是否在工作、是否等待自己、真实后果是什么，以及异常后如何恢复。

### 任务

- [ ] 增加一条固定 E2E 验收路径：登录 -> 启动前检查 -> dry-run 启动 -> Dashboard 实时进度 -> Review 审核 -> 模拟/真实发布 -> Analytics -> 带 topic 再启动。
- [ ] Dashboard 所有进度、当前 agent、状态来源、最后同步时间只从 workflow store 派生，避免页面和组件各自计算。
- [ ] WebSocket 断线恢复后，在 UI 中明确展示“已恢复实时同步”或“已补齐事件”，并记录最后补传 seq。
- [ ] `paused` 和 `cancelled` 不应把进度回退到 0，应保留最后有效进度，并突出“恢复、取消、查看历史”的主动作。
- [ ] 发布确认弹窗展示账号、dry-run/live、auto-publish、标题摘要、图片状态和失败恢复入口。
- [ ] Review 提交后使用后端返回的 `next_phase` 展示实际结果：已进入发布、已进入修订、已拒绝归档或已完成。
- [ ] 为 workflow start -> realtime event -> review pending -> review submit -> publish result 建立端到端测试。

### 验收标准

- 启动工作流后，Dashboard 在 1 秒内显示当前阶段。
- 断开 WebSocket 后恢复，不丢失阶段变化和审核提醒。
- 真实发布前必须看到 live mode 强确认。
- paused/cancelled 状态不造成进度倒退或下一步动作不明。
- Review 提交后页面展示的状态与后端 `next_phase` 一致。

---

## 三、P1：启动和审核效率

### 目标

减少首次启动和人工审核中的犹豫、误判和重复输入。

### 任务

- [ ] 启动前检查清单直接影响表单：LLM 缺失时禁用启动；XHS 凭证缺失时默认并锁定 dry-run，或要求显式确认才能切换。
- [ ] Home 表单明确展示推荐来源：来自 Analytics 的 topic、niche、内容角度、建议发布时间应一起预填。
- [ ] 快速启动仍应经过风险确认，但不要求用户理解所有配置项。
- [ ] Review 页“修改”按钮先展开结构化反馈区，而不是立即校验 revision reason。
- [ ] Review 内容预览改成更接近小红书笔记卡片：标题长度、正文长度、话题标签、封面提示、图片缺失风险都即时标注。
- [ ] 版本历史增加“采纳此版本、复制、对比后回滚”操作。
- [ ] 审核反馈分成必填的主原因和可选的字段级问题，降低提交失败率。

### 验收标准

- 从登录到启动 dry-run workflow 不超过 60 秒。
- 缺少配置时用户能知道缺什么、影响什么、还能做什么。
- Review 阶段用户在 2 次点击内可以找到主动作。
- 需要修改时，用户不会因为未提前填写 revision reason 被直接打断。

---

## 四、P1：Analytics 到再创作闭环

### 目标

让 Analytics 不只是报表，而是下一轮内容生成的输入。

### 任务

- [ ] 后端 `/analytics/performance/{account_id}` 支持 `period` 参数，确保列表和图表与报告口径一致。
- [ ] 后端 `/analytics/costs` 支持按 `account_id` 和 `period` 聚合，避免成本指标与当前页面周期脱节。
- [ ] Analytics 顶部明确展示 account、period、样本数和更新时间。
- [ ] 空数据时展示可执行引导：完成一次 dry-run、完成一次真实发布、或从推荐垂类启动。
- [ ] 热门话题按钮不仅携带 `topic`，还携带 `niche`、建议内容角度和建议发布时间。
- [ ] 增加再创作转化指标：推荐 topic 点击率、从推荐 topic 到工作流启动成功率。

### 验收标准

- 切换周期后，指标卡、趋势图、帖子表格和洞察使用同一 period。
- 没有数据时不是空表格，而是清晰的下一步。
- 从 Analytics 点击热门话题后，Home 表单无需重复输入主要配置即可启动。

---

## 五、P2：界面、移动端和可访问性

### 目标

让产品更像高频增长工作台，降低视觉噪声，提高小屏可用性和键盘可操作性。

### 任务

- [ ] 继续收敛装饰性 neon、渐变和动画，保留状态表达所需的颜色，不用装饰抢内容注意力。
- [ ] Dashboard、Review、Analytics 减少嵌套卡片，统一使用 `frontend/src/styles/cards.css` 中的卡片、按钮、徽标、表格样式。
- [ ] 移动端 Tab 增加 Review 待办徽标、运行中状态点、错误状态点。
- [ ] 表格补齐空状态、排序、长标题截断和可读时间格式。
- [ ] 所有弹窗补齐焦点锁定、Esc 关闭、Enter 确认和 aria label。
- [ ] 所有 destructive action 增加强确认，并说明是否可恢复。
- [ ] 验证 375px 宽度下启动、查看状态、审核三条主流程无文字溢出和按钮错位。

### 验收标准

- 375px 宽度下能完成启动、查看状态、审核三条主流程。
- 键盘用户能完成登录、启动、审核、关闭弹窗和切换 Analytics 周期。
- 关键按钮文字不溢出，不与图标或后续内容重叠。

---

## 六、测试计划

### 后端

- [ ] `tests/integration/test_api_routes.py` 覆盖 review publish options、rejected 结束、next_phase 返回。
- [ ] `tests/unit/realtime/test_event_contract.py` 扩展 workflow started、phase changed、review pending、publish result 契约。
- [ ] `tests/unit/realtime/test_websocket.py` 覆盖按订阅 thread 补传 missed events。
- [ ] Analytics 路由测试增加 `period`、`account_id` 聚合口径。

### 前端

- [ ] workflow store 测试覆盖 WebSocket 补传后状态更新、paused/cancelled 进度保留。
- [ ] review store 和 Review 页面测试覆盖 dry-run/live publish options、revision feedback 流程。
- [ ] analytics store 测试覆盖 period 切换后 report/performance/costs 同步刷新。
- [ ] 移动端组件测试覆盖 MobileTabBar 状态徽标。

### E2E

- [ ] 登录后首次 dry-run 启动。
- [ ] 工作流进入 reviewing 后从 Dashboard 跳转 Review。
- [ ] Review approved + dry-run 后进入发布结果。
- [ ] Review needs_revision 后进入修订循环并保留版本历史。
- [ ] Analytics 点击热门 topic 后回到 Home 并预填表单。
- [ ] WebSocket 断线重连后补齐事件。

---

## 七、执行顺序

1. 先补 P0 E2E 测试和状态一致性问题，锁住主路径可信度。
2. 再优化 Review 和 Home 的交互效率，降低启动与审核摩擦。
3. 接着补齐 Analytics 后端口径，让再创作闭环可信。
4. 最后做移动端、表格、弹窗和视觉收敛。

---

## 八、核心指标

- 首次 dry-run 启动耗时不超过 60 秒。
- 工作流阶段变化 1 秒内反映到 Dashboard。
- 真实发布误触发率为 0。
- Review 阶段主动作发现路径不超过 2 次点击。
- Analytics 周期切换后所有指标口径一致。
- 375px 宽度下核心流程无文字溢出、遮挡或按钮错位。
