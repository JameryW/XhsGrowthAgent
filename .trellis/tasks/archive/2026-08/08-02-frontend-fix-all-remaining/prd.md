# 修复所有剩余前端已知问题

承接 08-01（P0+P1）与 08-02（P2）两批。用户目标：修复所有记录在案的剩余问题。

## 范围

### 1. WorkflowReplay.spec.ts 3 个既有测试失败
`frontend/tests/components/WorkflowReplay.spec.ts` 的 `getCheckpoint` mock 调用断言失败（step 导航相关），为两批改动之前就存在的既有失败。先定位根因（组件行为变了 spec 没跟上，还是组件 bug），最小修复使测试通过，不改变 WorkflowReplay 的用户可见行为。

### 2. `:global(html.dark)` 编译陷阱 16 处存量
Vue scoped 样式中 `:global(html.dark) .x` 经本工具链编译后尾部类名被丢弃，规则从未生效。存量：Navbar.vue 2 处（`.app-sidebar`、`.app-nav-item[aria-current]` 的暗色 shadow）、WorkflowTabBar.vue 4 处、EvaluationView.vue 10 处。参考已修复的 `.app-nav-section` 写法（组件 scoped 内普通 `html.dark .x` 选择器，编译为 `html.dark .x[data-v-…]`）逐一修复。修复后这些暗色规则开始生效——逐个核对规则内容是否仍是正确意图（它们从未渲染过，可能已过时），过时则修正为与当前视觉一致或删除。

### 3. views/遗留组件失效 `dark:` 变体激活迁移（~1700 处）
main.css 暗色重映射层 47 条通用 token 规则带 `!important`，压制了组件中作者写了但从未生效的 `dark:` 变体。豁免机制已就位：元素加 `dark-explicit` 标记后，`:not(.dark-explicit)` 让其自身 `dark:` 生效（见 main.css 重映射区顶部注释与 .trellis/spec/frontend/component-patterns.md 的 Dark Mode Convention 章节）。
- 检测脚本（agent 自写，可参考）：`.tmp-build/dark_conflicts.py`——解析 main.css 重映射选择器与全部 .vue 的逐元素 class token，找出「元素同时带被重映射基础类 + 同属性 dark: 变体」的点。
- 迁移原则：只给**确实带有同属性 dark: 变体**的元素加标记（无 dark: 的元素继续靠重映射兜底，不能误标）；按文件分批，每批跑构建 + 相关测试。
- 风险：这些 dark: 变体从未渲染过，可能有个别过时/错误——迁移后以 dark: 变体为准（作者意图），明显错误的（如 dark 下反而更亮的文字）按当前重映射渲染值修正 dark: 变体。
- shell 五组件（Navbar/MobileTabBar/Toast/ConnectionStatus/PageHeader）已迁移，勿重复。

## 约束

- i18n 双语、reduced-motion、44px 等既有约定不变；不改 API/状态语义。
- 验收：cd frontend && node scripts/check-i18n.mjs && npx vue-tsc --noEmit && npx vitest run（目标：WorkflowReplay 修复后 696 全绿）&& npm run build。
- 完成后把「剩余技术债」从文档中移除相应条目，更新 spec。
