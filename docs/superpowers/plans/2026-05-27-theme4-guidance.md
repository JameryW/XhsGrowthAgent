# 主题4：用户引导与帮助实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 降低新用户学习成本，在关键时刻提供操作提示，让用户随时获取帮助。

**Architecture:** 创建3个Vue组件（OnboardingTour、TooltipHelper、HelpCenter）+ 增强KeyboardShortcuts.vue + 2个composables（useOnboarding、useShortcuts）+ 1个onboarding store + 集成到App、Home、Review、Navbar。采用3步式引导、浮动tooltip、快捷键监听、帮助中心设计。

**Tech Stack:** Vue 3 Composition API, TypeScript, Pinia stores, keyboard event handling, localStorage

---

## 文件结构

**新增文件：**
```
frontend/src/
├── components/
│   ├── OnboardingTour.vue        # 新手引导流程（3步式）
│   ├── TooltipHelper.vue         # 操作提示组件（浮动tooltip）
│   └── HelpCenter.vue            # 帮助中心入口
│
├── composables/
│   ├── useOnboarding.ts          # 引导状态逻辑
│   └── useShortcuts.ts           # 快捷键监听逻辑
│
├── stores/
│   └── onboarding.ts             # 引导状态管理
│   └── shortcuts.ts              # 快捷键状态管理
│
└── types/
│   └── onboarding.ts             # 引导类型定义
```

**修改文件：**
```
frontend/src/
├── components/
│   └── KeyboardShortcuts.vue     # 增强快捷键面板（从简单列表改为可视化）
│
├── views/
│   ├── Home.vue                  # 步骤1和2高亮启动按钮
│   └── Review.vue                # 步骤3高亮操作按钮 + TooltipHelper
│
├── components/
│   └── Navbar.vue                # HelpCenter入口按钮
│
└── App.vue                       # OnboardingTour首次访问检测
```

**测试文件：**
```
frontend/tests/
├── components/
│   ├── OnboardingTour.spec.ts
│   ├── TooltipHelper.spec.ts
│   └── HelpCenter.spec.ts
│
├── composables/
│   ├── useOnboarding.spec.ts
│   └── useShortcuts.spec.ts
│
├── stores/
│   ├── onboarding.spec.ts
│   └── shortcuts.spec.ts
│
└── integration/
│   └── theme4-guidance.spec.ts   # 验收测试
```

---

## 任务分解

### Task 1: 创建引导类型定义

**Files:**
- Create: `frontend/src/types/onboarding.ts`
- Modify: `frontend/src/types/index.ts`

**类型定义：**
```typescript
export type OnboardingStep = 1 | 2 | 3

export interface OnboardingState {
  isActive: boolean
  currentStep: OnboardingStep
  hasCompleted: boolean
}

export interface TourStep {
  step: OnboardingStep
  title: string
  description: string
  highlightElement: string
  position: 'top' | 'bottom' | 'left' | 'right'
}
```

**Commit:** `feat(theme4): define onboarding types and interfaces`

---

### Task 2: 创建onboarding store

**Files:**
- Create: `frontend/src/stores/onboarding.ts`
- Test: `frontend/tests/stores/onboarding.spec.ts`

**Store功能：**
- State: isActive, currentStep, hasCompleted
- Actions: startTour(), nextStep(), skipTour(), completeTour()
- Getters: isStep1, isStep2, isStep3
- localStorage同步（has_completed_onboarding）

**测试：**
- startTour设置isActive=true
- nextStep增加步骤
- completeTour标记完成并同步localStorage
- skipTour跳过并标记完成

**Commit:** `feat(theme4): implement onboarding state store`

---

### Task 3: 创建shortcuts store

**Files:**
- Create: `frontend/src/stores/shortcuts.ts`
- Test: `frontend/tests/stores/shortcuts.spec.ts`

**Store功能：**
- State: showPanel, activeShortcuts（根据页面筛选）
- Actions: showPanel(), hidePanel(), executeShortcut(key)
- 快捷键映射表（Ctrl+K, Ctrl+R, Esc, ?, A, P, R, G H, G D）

**测试：**
- showPanel/hidePanel工作
- 快捷键映射正确
- executeShortcut执行对应操作

**Commit:** `feat(theme4): implement shortcuts state store`

---

### Task 4: 创建useOnboarding composable

**Files:**
- Create: `frontend/src/composables/useOnboarding.ts`
- Test: `frontend/tests/composables/useOnboarding.spec.ts`

**功能：**
- checkLocalStorage() - 检查是否已完成引导
- getCurrentStep() - 获取当前步骤
- advanceStep() - 前进到下一步
- TOUR_STEPS配置（3步内容）

**测试：**
- localStorage检测正确
- 步骤前进正确
- TOUR_STEPS内容正确

**Commit:** `feat(theme4): implement useOnboarding composable`

---

### Task 5: 创建useShortcuts composable

**Files:**
- Create: `frontend/src/composables/useShortcuts.ts`
- Test: `frontend/tests/composables/useShortcuts.spec.ts`

**功能：**
- setupKeyboardListeners() - 全局键盘监听
- handleKeyPress(event) - 按键处理
- SHORTCUTS_MAP配置（所有快捷键）
- 页面筛选逻辑（根据当前路由）

**测试：**
- 键盘监听正确设置
- 按键处理正确
- 页面筛选工作

**Commit:** `feat(theme4): implement useShortcuts composable`

---

### Task 6: 实现OnboardingTour组件

**Files:**
- Create: `frontend/src/components/OnboardingTour.vue`
- Test: `frontend/tests/components/OnboardingTour.spec.ts`

**组件功能：**
- Props: isActive, currentStep
- 3步式引导：
  - 步骤1：了解工作流（Home页，高亮启动按钮）
  - 步骤2：启动第一个工作流（Home页，点击按钮）
  - 步骤3：审核与发布（Review页，高亮操作按钮）
- 遮罩层 + 高亮框 + 步骤指示器
- Skip/Next/Complete按钮
- Emits: next, skip, complete

**测试：**
- 遮罩层渲染
- 高亮框位置正确
- 步骤内容显示
- 按钮emit事件

**Commit:** `feat(theme4): implement OnboardingTour component`

---

### Task 7: 实现TooltipHelper组件

**Files:**
- Create: `frontend/src/components/TooltipHelper.vue`
- Test: `frontend/tests/components/TooltipHelper.spec.ts`

**组件功能：**
- Props: content (string), position ('top'|'bottom'|'left'|'right')
- 浮动tooltip显示
- 箭头指向触发元素
- hover/focus时显示
- 柔和背景样式

**测试：**
- 内容显示正确
- 位置正确
- 箭头样式
- 事件触发

**Commit:** `feat(theme4): implement TooltipHelper component`

---

### Task 8: 实现HelpCenter组件

**Files:**
- Create: `frontend/src/components/HelpCenter.vue`
- Test: `frontend/tests/components/HelpCenter.spec.ts`

**组件功能：**
- 问号图标按钮
- 点击展开下拉菜单：
  - FAQ（常见问题）
  - 快捷键列表（链接到KeyboardShortcuts）
  - 反馈入口（mailto链接）
- Emits: open-faq, open-shortcuts

**测试：**
- 按钮渲染
- 下拉菜单展开
- FAQ链接
- 反馈链接

**Commit:** `feat(theme4): implement HelpCenter component`

---

### Task 9: 增强KeyboardShortcuts组件

**Files:**
- Modify: `frontend/src/components/KeyboardShortcuts.vue`
- Test: `frontend/tests/components/KeyboardShortcuts.spec.ts` (更新现有)

**增强内容：**
- 从简单列表改为可视化面板
- 添加快捷键描述
- 分类显示（全局、Dashboard、Review）
- 快捷键操作按钮（如"Try it"）
- 使用shortcuts store状态

**测试：**
- 可视化面板渲染
- 分类正确
- 快捷键列表完整

**Commit:** `feat(theme4): enhance KeyboardShortcuts with visual panel`

---

### Task 10: App集成OnboardingTour

**Files:**
- Modify: `frontend/src/App.vue`

**集成：**
- 检测localStorage has_completed_onboarding
- 首次访问时触发OnboardingTour
- 使用onboardingStore状态

**Commit:** `feat(theme4): integrate OnboardingTour into App`

---

### Task 11: Home集成步骤1和2

**Files:**
- Modify: `frontend/src/views/Home.vue`

**集成：**
- OnboardingTour步骤1高亮启动按钮
- 步骤2自动点击启动按钮并跳转Dashboard
- TooltipHelper添加提示

**Commit:** `feat(theme4): integrate onboarding steps into Home`

---

### Task 12: Review集成步骤3和TooltipHelper

**Files:**
- Modify: `frontend/src/views/Review.vue`

**集成：**
- 步骤3高亮操作按钮（Approve/Revise/Reject）
- TooltipHelper添加按钮提示
- 首次进入时触发步骤3

**Commit:** `feat(theme4): integrate onboarding step3 and tooltips into Review`

---

### Task 13: Navbar集成HelpCenter

**Files:**
- Modify: `frontend/src/components/Navbar.vue`

**集成：**
- 右上角添加HelpCenter按钮
- 问号图标
- 点击展开帮助菜单

**Commit:** `feat(theme4): integrate HelpCenter into Navbar`

---

### Task 14: 全局快捷键监听

**Files:**
- Modify: `frontend/src/App.vue` 或创建独立监听文件

**集成：**
- 使用useShortcuts composable
- 全局键盘事件监听
- 按 ? 显示KeyboardShortcuts面板
- 处理所有快捷键

**Commit:** `feat(theme4): setup global keyboard shortcuts listener`

---

### Task 15: 主题4验收测试

**Files:**
- Create: `frontend/tests/integration/theme4-guidance.spec.ts`

**验收标准（checklist）：**
- ✅ AC1: 新用户完成引导流程（首次访问触发，3步完成）
- ✅ AC2: 快捷键功能正常（按 ? 显示面板，各快捷键生效）
- ✅ AC3: 帮助信息准确有用（HelpCenter FAQ覆盖常见问题）

**Commit:** `test(theme4): add acceptance tests for user guidance`

---

### Task 16: 创建主题4完成总结

**Files:**
- Create: `docs/superpowers/plans/2026-05-27-theme4-guidance-summary.md`

**总结内容：**
- 已实现组件列表（3个新增 + 1个增强）
- 已实现composables（2个）
- 已实现stores（2个）
- 集成视图（5个）
- 测试覆盖统计
- 验收状态
- 提交记录
- 全流程UX优化完成总结

**Commit:** `docs(theme4): add completion summary and final UX optimization report`

---

## 实施统计

- **总任务数：16个**
- **总步骤数：约50个**
- **新增文件：11个**
- **修改文件：7个**
- **测试文件：9个**
- **预计完成时间：2-2.5小时**

---

## 实施策略

**开发模式：** 继续在main分支开发
**验收顺序：** 按任务顺序逐个验收
**验收标准：** 每个组件完成后验证单元测试通过
**最终验收：** Task 15验收测试覆盖checklist
**完成标志：** Task 16总结包含全流程UX优化最终报告

---

## Spec Self-Review

### Placeholder Scan
- ✓ 无"TBD"、"TODO"标记
- ✓ 所有引导步骤内容明确
- ✓ 所有快捷键映射完整

### Internal Consistency
- ✓ OnboardingTour步骤与Home/Review集成一致
- ✓ useShortcuts与shortcuts store接口匹配
- ✓ 快捷键列表与v3规范一致

### Scope Check
- ✓ 聚焦主题4范围，无越界
- ✓ 与主题1-3有清晰边界
- ✓ 组件职责单一

### Ambiguity Check
- ✓ 引导步骤内容具体（启动按钮、审核按钮）
- ✓ 快捷键映射明确（Ctrl+K, ?, A, P, R等）
- ✓ 验收checklist具体可执行