# PRD: 开始创作 → 立即弹模式选择

## Goal

当前 Home 页点「开始创作」时，WorkflowStartForm 默认铺开，用户须先填表（账号/选题/垂类）才能点按钮，点后才弹 CreationModeModal 选简单/自由模式。要求改成：点「开始创作」立即弹模式选择，不先逼填表。

## Current Behavior

- `WorkflowStartForm` 默认渲染（Home.vue:131）。
- 按钮「开始创作」`@click="handleFormSubmit"` → 先 `startFormRef.getConfig()` 再 `showCreationMode=true`（Home.vue:58-64）。
- 简单模式 `chooseSimpleMode` → `showConfirm=true`，但此时若用户没填表，`ConfirmStartModal` 展示空字段。

## Target Behavior

1. 进入 Home 页，`WorkflowStartForm` 默认**隐藏**。
2. 点「开始创作」→ 立即 `showCreationMode=true`（不调 getConfig，不依赖表单）。
3. CreationModeModal 选「自由模式」→ 直接跳 `/tui?mode=free`，topic/niche 来自 query param 预填（analytics 跳转过来时携带）或留空让 TUI 内输入。不依赖 formConfig。
4. CreationModeModal 选「简单模式」→ 关闭 modal，**展开** `WorkflowStartForm`，聚焦让用户填表。表单下方按钮文案改为「启动简单模式」，点击 → `getConfig()` → `showConfirm=true` → `confirmStart`（原逻辑不变）。
5. 选简单模式前不应触发 `ConfirmStartModal`（避免空字段弹窗）。

## Implementation Sketch

Home.vue:
- 新增 `const showSimpleForm = ref(false)`，默认 false。
- `WorkflowStartForm` 外层加 `v-if="showSimpleForm"`。
- `handleFormSubmit`（开始创作按钮）：改为只 `showCreationMode.value = true`，去掉 getConfig 调用。
- `chooseSimpleMode`：`showCreationMode=false; showSimpleForm=true`。
- 简单模式表单下按钮（原开始创作按钮位置）：文案 `home.startWorkflow` 复用或新增 `home.startSimple`；点击 → `getConfig()` 填 formConfig → `showConfirm=true`。
- `chooseFreeMode`：不依赖 formConfig；从 `route.query` 或 `prefilledTopic` 取 topic/niche 传 TUI query，否则只传 `mode=free`。
- 顶部「开始创作」主按钮（表单隐藏时仍可见，作为入口）保留，点击即弹 modal。

i18n: 若新增 `home.startSimple` key，zh-CN/en 都加。优先复用现有 `home.startWorkflow`（已=「开始创作」）减少新增。

## Acceptance Criteria

- Home 页初始加载：表单不显示，只有「开始创作」入口按钮 + checklist + nav。
- 点「开始创作」：立即弹 CreationModeModal，不要求先填表。
- 选自由模式：直接跳 `/tui?mode=free`（topic/niche 若有 query 则带上），不报错。
- 选简单模式：modal 关闭，表单展开，用户填表后点「启动简单模式」→ ConfirmStartModal 展示已填字段 → 确认启动原工作流。
- 不出现 ConfirmStartModal 展示空字段的场景（简单模式必须先经表单填好）。
- `vue-tsc --noEmit` + `ruff check .` 通过。
- 现有相关测试（若有 Home/creation mode 测试）通过。
