# 前端交互体验说明

本项目的前端以“下一步动作明确、状态来源单一、移动端路径完整”为交互原则。下面记录当前入口、状态和自由创作工作区的行为，避免新增页面时重新引入死链或账号上下文丢失。

## 信息架构与路由

| 入口 | 路径 | 交互约定 |
|------|------|----------|
| 开始创作 | `/start` | 首屏欢迎区说明创作目标，展示当前账号上下文和“配置 → 确认 → 创作”三步 cue；趋势/Brief 模式确认后启动，自由创作进入 `/tui?mode=free` |
| 工作台 | `/dashboard/:threadId?` | 可通过历史记录深链打开指定工作流；状态 Hero 按空闲/运行中/等待输入或审核/完成/错误切换标题、进度和 CTA，下一步卡片优先提示待处理动作 |
| 内容审核 | `/review/:threadId?` | 可深链打开指定审核项；展开卡片后底部操作栏保持可见 |
| 增长 | `/analytics`、`/evaluation` | 统一从移动端“更多”访问；页面显示当前账号、周期或评估上下文 |
| 历史 | `/history` | 查看、恢复、回放工作流；空状态的“返回首页”回到工作台而不是重新开始；列表按 offset 分页（每页 50）“加载更多”，并显示已加载/总数与到底完成态 |
| 设置 | `/settings?tab=...` | 桌面端侧栏、窄屏横向标签；账号和系统配置保持独立 |
| 帮助 | `/help` | FAQ、快捷键和反馈报告；反馈复制到剪贴板，不使用未配置的邮箱地址 |
| 自由创作 | `/tui?mode=free` | 需要登录；终端保留命令能力，顶部提供建议、草稿、帮助快捷操作，并展示当前 XHS 账号 |

桌面侧栏展示品牌、当前工作区状态、开始创作主行动，并将工作台/审核归入“工作区”、分析/评估/历史归入“洞察与历史”；当前账号、赛道、实时连接状态和设置入口集中在底部上下文卡。当前路由使用图标底色、左侧渐变标记、文字层级和箭头共同表达，不只依赖颜色；待审核状态会在审核入口显示提示标记。平板保留折叠图标和 tooltip/aria-label。移动端底部保留创作、工作台、审核，增长相关入口统一收纳在“更多”菜单，菜单顶部同步展示当前账号和连接状态。语言切换在桌面侧栏之外还需覆盖窄屏：移动端“更多”菜单与平板底栏均提供语言切换入口。

## 首屏体验与状态层级

- `/start` 的欢迎 Hero 先回答“现在可以做什么”，右侧显示所选账号和绑定赛道；账号未选定时明确提示选择账号。配置表单以三步 cue 固定用户位置，三种模式卡片同时展示适用场景和当前选中状态。
- 创作表单的主行动保持单一且占据卡片底部；模式、账号、主题等核心配置先展示，高级选项默认收起。模式卡片和快捷入口在窄屏使用可换行布局，按钮触控高度不低于 44px。
- `/dashboard` 首屏先渲染状态 Hero 和进度条，再渲染下一步卡片、时间线与阶段产物：空闲引导开始创作，运行中展示实时进度，等待输入/审核突出用户行动，完成提供历史入口，错误提供恢复路径。回放模式使用历史快照层级，不把快照误标为已完成。状态来源仍是 `workflowStore.effectiveState`，不改变工作流 API 语义。首屏 CTA 保持层级唯一：nextAction 卡片是唯一主行动，状态 Hero 只展示状态与进度，不再重复放置 CTA。
- 工作台运行中会在有 `agent_timeline` 起始时间时显示当前 agent 的累计时长；ETA 只有在已有完成 agent 样本时显示，并明确使用“约”语义。Ripple 高频进度按 job 保留最新事件、每 200ms 批量更新，避免整棵视图树随每条 WS 消息重渲染。
- Hero 只使用颜色和图标增强信息层级，动效不是理解状态的必要条件；新增过渡遵循 `prefers-reduced-motion` 降级原则。

## 公开页与洞察页约定

- Showcase 列表按 20 条分页，加载更多沿用当前筛选上下文，并显示“已加载 X / 共 Y”与到底完成态（计数区域用 aria-live 播报）；Showcase/Replay 在路由进入时同步 `title`、description、OG 和 Twitter meta，语言切换时更新。
- Replay 选择步骤后会在浏览器空闲时间预取下一步详情；预取失败不打断当前步骤，所有请求仍使用 AbortController 和缓存过期策略。
- Analytics 的互动图表在无数据时显示可见空态、提供双语屏幕阅读摘要；趋势点可见，表格 shares 与图表口径一致，并支持导出当前账号周期的 CSV。趋势图基于最近 ≤20 条已加载笔记计算，与互动图（服务端周期总量）口径不同，页面上必须注明这一差异，避免被读作同一指标。
- Evaluation 雷达只展示加权维度，使用固定顺序和 rationale tooltip；无匹配筛选结果与真实空列表分开表达：筛选无结果提供一键清除筛选，真实空列表带下一步 CTA，窄屏雷达降低高度。

当前五页的错误恢复统一使用 `components/ErrorState.vue`：公开页通过
presentational props 保留各自重试语义，Dashboard 仍由 workflow/error store 适配；不要再新增
独立错误卡。Dashboard 的内容骨架需要同时说明当前工作流阶段，草稿和版本卡使用主题表面而不是
单一蓝色语义。Analytics 的周期摘要以服务端 delta 为准，表格排序使用原始数值，并通过行点击
打开单篇详情；已有数据刷新失败时保留旧数据并明确标记为 stale。

## 状态与错误恢复

- `realtimeStore.connectionStatus` 是实时连接状态的唯一来源。连接中/重连中显示轻量提示；已断开时由受控的离线恢复条提示，不再同时渲染浏览器离线条和连接卡片。
- API 错误的“重试”只刷新当前 `threadId`。没有当前工作流时才回到开始创作，不会隐式创建默认工作流。
- 历史记录、评估和分析的空状态需要区分“没有数据”和“加载失败”，并提供原因和下一步动作。
- 账号列表加载失败或为空时，创作表单显示错误/空态并提供重试与账号管理设置入口，不得静默回退 `default` 伪账号。
- 账号上下文必须来自 `accountsStore.activeAccount` 或创作表单显式选择；自由创作工作区只使用 XHS 账号 ID，不使用控制台用户 UUID。

## 可访问性与响应式

- 主要按钮和移动端菜单项使用至少 44px 的触控高度。
- 所有弹窗统一具备 `role="dialog"`、`aria-modal`、Escape 关闭与焦点管理（复用 `useFocusTrap`：打开时聚焦主操作、关闭后还原焦点），适用范围含帮助/快捷键面板、ConfirmStartModal、Review 发布弹窗、WorkflowTabBar 关闭确认框；引导找不到异步目标时会明确提示，而不是绘制空高亮框。
- 设置标签在窄屏横向滚动，审核操作栏在展开卡片底部保持可见；吸底操作栏在移动端需抬高避开 MobileTabBar：`bottom-[calc(4.5rem+env(safe-area-inset-bottom,0px))] md:bottom-0`。
- reduced-motion 降级由 `main.css` 的 `@media (prefers-reduced-motion: reduce)` 块统一承载：覆盖 Tailwind 的 `animate-pulse`/`animate-spin`/`animate-spin-slow` 及组件自定义动画类（`mesh-drift-3`、`scale-bounce-animation`、Review 加载 `.spin`、modal scale/fade 过渡），并将 `scroll-behavior` 降级为 `auto`。新增动画只需把类名登记进该块，不再各自写 media query；JS 侧的 `scrollIntoView` 等平滑滚动需通过 `useReducedMotion` 选择 `behavior`。
- `AppIcon` 在无 `ariaLabel` 时默认 `aria-hidden`（装饰性图标不进无障碍树），只有显式给出标签才暴露 `role="img"`。
- 所有模板文案都进入 `en.json` 和 `zh-CN.json`。AgentTUI 的终端输出属于 ANSI 渲染域，仍需通过 `t()` 生成可见文案。

## 主题、暗色与层级约定

- 主题切换为三态循环 light → dark → system（`themeStore.toggle()`），ThemeToggle 用 Sun/Moon/Monitor 图标区分，aria-label 走 `theme.light/dark/system`；新增主题相关交互不要退回二态切换。
- 暗色模式：新组件必须使用自身的显式 `dark:` 变体，不得依赖 `main.css` 末尾 `html.dark` 全局重映射兜底层。该层规则带 `!important`，会压制组件里同属性的 `dark:` 变体——若元素同时带被重映射的基础类和自己的 `dark:` 意图，给该元素加 `dark-explicit` 标记类即可豁免重映射。全部 views 与组件已于 2026-08-02 完成迁移（约 1400 处标记），失效 `dark:` 变体已清零；重映射层现在只兜底极少数无 `dark:` 变体的元素。不得向重映射层新增规则，除非在注释里说明服务的遗留页面。
- z-index 一律使用 `tailwind.config.js` 的语义 token（`z-base/sticky/overlay/dropdown/modal/toast/chrome/max`），禁止 `z-[...]` 魔法值和裸数字层级；token 与使用场景见 `.trellis/spec/frontend/component-patterns.md`。
- 已知陷阱：scoped 样式里的 `:global(html.dark) .x` 在本工具链编译后尾部类名被丢弃，规则从未生效（Navbar、WorkflowTabBar、EvaluationView 的存量已于 2026-08-02 全部修复或移除）。暗色覆盖应写组件自身的 `dark:` 变体或依赖 `dark-explicit` 机制；scoped CSS 需要全局暗色规则时用普通 `html.dark .x` 写法。

## 本地验证

```bash
cd frontend
npm run type-check
npm run i18n:check
npm run test:run
npm run build
```

构建可能报告大 chunk 提示（AgentTUI 包含 xterm/WebGL 依赖），这不是构建失败；需要关注命令最终是否输出 `built`。

2026-08-09 验收记录：前端全量为 64 个文件 / 675 个测试，后端全量为 2153 个测试；
`type-check`、`i18n:check`、`ruff format --check`、`ruff check` 和 `mypy backend` 均通过。
Vite 的 ECharts 手动分包已按实际注册模块拆分，当前构建不再产生 500KB chunk 警告。
公开页浏览器验收仍分为两种证据：默认严格模式要求目标环境 live 列表为空；已有 owner 审批案例的
环境使用 `--allow-existing-public`，该报告会单独记录 live 数量，不能替代空态安全门槛。
