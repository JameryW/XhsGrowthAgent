# 合并创作模式进表单 — free 作为第三模式

## Goal

消除「点开始创作 → 进另一页还要点开始创作」的困惑。当前 Home.vue 用 CreationModeModal 独立遮罩做简单/自由分流，选简单后才展开表单+第二个同名按钮，体验上像重复入口。将自由模式并入 WorkflowStartForm 作为第三模式选项（trend / brief / free），删掉 CreationModeModal 中间层，点「开始创作」直接展开表单，选模式 + 填配置 + 启动一气呵成。

## What I already know

- Home.vue (`frontend/src/views/Home.vue`): 两个同文案按钮 A/B。A(`handleFormSubmit`) 弹 CreationModeModal；选简单→`showSimpleForm=true` 展开 WorkflowStartForm + 按钮 B(`submitSimpleForm`)→ConfirmStartModal；选自由→`router.push({name:'tui', query:{mode:'free',...}})`。
- WorkflowStartForm.vue: 顶部已有 trend/brief 双列模式选择(行138-176)，`getConfig()` 返回 `workflowMode: 'trend'|'brief'`。自由模式需扩成第三列。
- CreationModeModal.vue: 独立 modal，emit `simple`/`free`/`cancel`。选 2 后删除此组件。
- ConfirmStartModal.vue: 确认启动，仅 trend/brief 走它；free 直接跳 /tui 不经确认。
- i18n: `home.creationMode.*`, `home.trendMode`, `home.briefMode` 在 locale 文件。

## Assumptions (temporary)

- free 模式选后隐藏 trend/brief 专属字段（topic/brief/niche/phase/options），只留模式选择 + 底部按钮，按钮文案改「进入自由创作」或类似，点击直接 router.push /tui?mode=free。
- topic/niche 预填（来自 analytics query）仍传给 free 模式 query，逻辑从 Home 挪进 form 的 submit。
- free 模式不经 ConfirmStartModal（它不启动 workflow，只跳 TUI）。

## Open Questions

- (resolved) free 模式按钮文案 → 新 key `home.form.enterFree` = 「进入自由创作」(zh) / "Enter Free Mode" (en)。

## Requirements (final)

- 点 Home「开始创作」直接展开 WorkflowStartForm（无 CreationModeModal 中间遮罩）。
- WorkflowStartForm 模式选择扩为 trend / brief / free 三列，模式列表数组化驱动（为未来扩展留口）。
- 选 free 时：隐藏 trend/brief 专属配置字段（topic/brief/niche/phase/options），底部按钮文案用 `home.form.enterFree`，点击直接 `router.push('/tui?mode=free')`（携带 topic/niche/account_id query）。
- 选 trend/brief 时：保持现状，底部按钮文案沿用 `home.startWorkflow` → ConfirmStartModal → 启动。
- 删除 CreationModeModal.vue 及 Home 中相关 state/handlers（showCreationMode, chooseSimpleMode, chooseFreeMode, handleFormSubmit 分流逻辑）。
- Home 不再有两个同文案按钮，只剩一个「开始创作」展开表单。
- `WorkflowMode` 类型扩为 `'trend' | 'brief' | 'free'`；ConfirmStartModal 不接收 free（Home 在 free 时不打开它）。
- analytics 预填 topic/niche 在 free 模式下一并传 query。
- 三模式扩展性：模式列表用数组驱动，便于后续加协作/批量模式。

## Acceptance Criteria

- [ ] Home 只有一个「开始创作」按钮，点击直接展开表单。
- [ ] 表单顶部三模式可选；free 选中后配置字段（topic/brief/niche/phase/options）隐藏。
- [ ] free 模式底部按钮文案 = `home.form.enterFree`，点击跳 `/tui?mode=free` 并带预填 query（topic/niche/account_id）。
- [ ] trend/brief 流程不变，仍经 ConfirmStartModal。
- [ ] `WorkflowMode` 类型 = `'trend' | 'brief' | 'free'`。
- [ ] CreationModeModal.vue 删除，无残留引用。
- [ ] i18n key `home.form.enterFree` 补齐（en + zh）。
- [ ] 模式列表数组化驱动（非硬编码三列）。
- [ ] npm run build 过；前端 lint/typecheck 过。

## Definition of Done (team quality bar)

- Tests: 前端无单测框架则至少 npm run build 过；改动文件 lint 过。
- Lint / typecheck / CI green。
- Docs: 无需（行为变更自明）。
- Rollout: 纯前端，deploy.sh 重新 build 即可。

## Out of Scope (explicit)

- TUI (/tui) 页面内部改造。
- ConfirmStartModal 内 free 分支（free 不走它）。
- analytics 预填逻辑变更（仅传值路径调整）。

## Technical Notes

- 文件: `frontend/src/views/Home.vue`, `frontend/src/components/WorkflowStartForm.vue`, `frontend/src/components/CreationModeModal.vue`(删), i18n locale。
- 约束: 保持 liquid-glass 视觉风格，三列模式按钮 grid-cols-3。
- 参考 PR #202 commit message 描述的原始设计意图。
