# 前端 P2 架构级优化

承接 `08-01-frontend-ux-polish-aug`（已归档）PRD 中的 P2 清单。上一批 P0+P1 已完成并提交（e86e5d45..247be2dc）。

## 范围

### A. 小项（一个代理）
1. **死代码删除**：`frontend/src/components/StepIndicator.vue`（无导入，仅 main.css:284 注释引用）、`frontend/src/components/ProgressPhase.vue`（无导入）。删除文件并清理孤儿 CSS（如 `.pulse-animation`，先 grep 确认无使用）。
2. **cards.css 去重**：`frontend/src/styles/cards.css:65-80` 的 `.card` 逐字复制 `main.css:53-67` 的 `.liquid-glass`（两个真相源）；cards.css 重复输出整套 `@tailwind` 指令；其未分层（unlayered）滚动条规则（151-168）覆盖 main.css `@layer base` 的精细滚动条。单一来源：`.card` 改为基于/引用 `.liquid-glass` 或合并，删除重复 `@tailwind`，滚动条规则归入 layer。
3. **html lang 同步**：`index.html` 静态 `lang="zh-CN"`，切换英文后 `documentElement.lang` 不同步 → 在 i18n locale watcher（stores/language.ts 或 locales/index.ts）里同步。
4. **theme 三态**：`stores/theme.ts:132-134` 默认 mode 是 `system`，但 ThemeToggle 的 `toggle()` 只 light↔dark，用户无法回到跟随系统 → 三态循环（light → dark → system），ThemeToggle 图标/aria-label 区分三态（i18n key 补齐）。

### B. z-index 语义 token 化
`tailwind.config.js:77` 附近已有语义 z 层约定（INF-07）。现状：`App.vue` 的 `z-[80]`/`z-[100]`、ConnectionStatus/Toast/OfflineRecovery/MobileTabBar 的 `z-50` 等魔法值 → 映射到语义 token（`z-sticky`/`z-overlay`/`z-modal`/`z-toast` 等，按 config 现有定义；不足则扩展 config）。逐文件 grep `z-\[` 和 `z-50`/`z-40`/`z-30` 的使用点逐一替换，保持视觉层级关系不变。

### C. 暗色重映射冲突点收缩（有界增量，不做全量重写）
`main.css:548-1424` 约 900 行 `html.dark` 精确 class-token 全局重映射带 `!important`，会盖掉组件里刻意的 `dark:` 变体（已知案例：MobileTabBar 菜单的 `dark:bg-slate-900/95`）。
本批只做：
1. 找出组件中带 `dark:` 变体但被全局重映射 `!important` 覆盖的冲突点（grep 组件 `dark:` 类 vs main.css 重映射选择器），逐一修正——优先把重映射选择器收窄或给组件加更具体的显式规则。
2. shell 高频表面（Navbar/MobileTabBar/Toast/ConnectionStatus/App shell）若仍依赖全局重映射而非自身 dark: 变体，迁移为组件自身显式 `dark:`（增量，不动遗留页面）。
3. 在 main.css 重映射区顶部注释更新：标注"遗留兜底，新组件必须用显式 dark: 变体"。

## 约束

- 不改变任何视觉呈现为目标的等价重构；若某处必须改变视觉，在报告里显式说明。
- i18n：新增文案走 t() 双语；locale 文件由实施代理直接改（本批单代理串行触碰，无并行冲突）。
- 验收：`cd frontend && node scripts/check-i18n.mjs && npx vue-tsc --noEmit && npx vitest run && npm run build`（WorkflowReplay.spec.ts 3 个失败为既有问题，不算回归）。

## 不做

- 暗色重映射全量重写为 CSS 变量体系（工作量与回归风险大，本次仅有界收缩 + 文档化方向）。
