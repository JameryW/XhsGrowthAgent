# PRD: Showcase Workflow Replay with Node Inspection

## Summary

在展示页面（Showcase.vue）中，点击工作流卡片进入该工作流的回放页面，支持点击单个流程节点查看当时该节点的执行状态。未登录用户只能查看，不能操作工作流；登录用户可以操作。

## Background

当前 Showcase 页面展示工作流列表卡片，但点击无任何交互。Dashboard 中已有完整的 Replay 模式（workflow store 的 `enterReplayMode`/`selectCheckpoint`），但 Showcase 页面作为公开页面，无法使用 Dashboard 的认证上下文。

## Requirements

### R1: 点击工作流卡片进入回放页面

- 点击 Showcase 页面中的工作流卡片，导航到 `/replay/:threadId` 页面
- 新建 `WorkflowReplay.vue` 视图，作为公开页面（`meta.public: true`）
- 页面布局继承 Showcase 的浅色主题风格
- 顶部显示返回按钮，返回 Showcase 列表

### R2: 回放页面展示工作流 Pipeline 时间线

- 复用 `WorkflowTimeline.vue` 的 Pipeline 节点展示逻辑
- 页面自动进入 replay 模式，加载 checkpoint 历史
- 所有节点默认可点击（与 Dashboard replay 模式行为一致）
- 点击节点切换到该节点的 checkpoint 状态

### R3: 点击节点查看执行状态

- 点击某个 Pipeline 节点，下方显示该节点执行时的详细状态
- 状态面板展示对应 checkpoint 的数据：trend_data / content_plan / copy_content / visual_plan 等
- 使用与 Showcase 卡片类似的卡片式展示，复用浅色主题
- 面板内容根据节点类型动态展示：
  - scouting → 热门话题、竞品分析
  - planning → 选题方向、内容角度
  - creating → 标题、正文、标签
  - reviewing → 审核状态
  - publishing → 发布结果
  - analyzing → 增长洞察

### R4: 未登录用户只能查看，不能操作

- Replay 页面为公开页面，不需要登录即可访问
- 未登录用户：
  - 可以查看工作流回放、点击节点查看状态
  - **不能**操作工作流（暂停/恢复/取消/重试等）
  - 隐藏或禁用所有操作按钮
- 登录用户：
  - 在 Replay 页面中可以看到"进入管控台"按钮
  - 可以操作工作流（跳转到 Dashboard 对应工作流）
- 判断方式：使用 `useAuthStore().isAuthenticated`

### R5: 路由配置

- 新增路由 `/replay/:threadId`，`meta.public: true`
- Showcase 卡片点击 → `router.push({ name: 'replay', params: { threadId } })`
- 登录用户可从 Replay 页面跳转 Dashboard 查看实时状态

## Technical Design

### 新建文件

1. `frontend/src/views/WorkflowReplay.vue` — 回放页面主视图

### 修改文件

1. `frontend/src/router/index.ts` — 新增 replay 路由
2. `frontend/src/views/Showcase.vue` — 卡片添加点击事件
3. `frontend/src/locales/zh-CN.json` — 新增 replay 相关翻译
4. `frontend/src/locales/en.json` — 新增 replay 相关翻译

### 实现方案

#### WorkflowReplay.vue

页面结构：
```
<nav> — 返回 Showcase + 页面标题 + (登录用户)进入管控台按钮
<replay-banner> — 回放模式提示条
<WorkflowTimeline> — Pipeline 时间线（复用现有组件，自动进入 replay 模式）
<NodeStatePanel> — 选中节点的状态详情面板
```

关键逻辑：
- `onMounted`: 使用 `workflowStore.setThreadId(threadId)` + `workflowStore.enterReplayMode()`
- 监听 `workflowStore.activeCheckpointId` 变化，更新节点状态面板
- 使用 `workflowStore.effectiveState` 获取当前选中 checkpoint 的完整数据
- 通过 `useAuthStore().isAuthenticated` 判断是否显示操作按钮

#### 节点状态面板

根据当前选中节点的 `current_agent` 字段决定展示内容：
- 每种 agent 类型对应不同的数据展示卡片
- 复用 Showcase 中已有的数据展示样式（topic、hot topics、title、hashtags 等）
- 面板为只读展示，不包含编辑功能

## Acceptance Criteria

- [ ] Showcase 卡片可点击，跳转到 /replay/:threadId
- [ ] Replay 页面自动加载 checkpoint 历史并进入 replay 模式
- [ ] Pipeline 时间线所有节点可点击，点击后高亮选中
- [ ] 点击节点后下方展示该节点执行时的状态数据
- [ ] 未登录用户只能查看，无法操作工作流
- [ ] 登录用户可以看到"进入管控台"按钮跳转 Dashboard
- [ ] 浅色主题风格与 Showcase 一致
- [ ] 中英文翻译完整
