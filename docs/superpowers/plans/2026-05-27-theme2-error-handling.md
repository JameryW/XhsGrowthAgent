# 主题2：错误处理与恢复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现完善的错误处理系统，让用户明确知道发生了什么，提供可操作的恢复方案，降低挫败感。

**Architecture:** 创建4个Vue组件（ErrorCard、RetryIndicator、ErrorBoundary、OfflineRecovery）+ 1个composable（useRetry）+ 1个error store + 集成到API层和全局视图。采用指数退避重试、错误类型分类、离线状态检测设计。

**Tech Stack:** Vue 3 Composition API, TypeScript, Pinia stores, error classification, retry logic

---

## 文件结构

**新增文件：**
```
frontend/src/
├── components/
│   ├── ErrorCard.vue              # 错误状态卡片（4种类型）
│   ├── RetryIndicator.vue         # 重试进度指示
│   ├── ErrorBoundary.vue          # Vue错误边界捕获
│   └── OfflineRecovery.vue        # 离线恢复处理
│
├── composables/
│   └── useRetry.ts                # 重试逻辑（指数退避）
│
├── stores/
│   └── error.ts                   # 错误状态管理
│
└── types/
│   └── error.ts                   # 错误类型定义
```

**修改文件：**
```
frontend/src/
├── api/
│   └ workflow.ts                  # API调用层集成重试
│   └── review.ts                  # API调用层集成重试
│
├── views/
│   ├── Dashboard.vue              # ErrorCard集成
│   └── App.vue                    # ErrorBoundary包裹
│
├── components/
│   └── Navbar.vue                 # OfflineRecovery集成
│
└── composables/
    └── useLoading.ts              # 添加error phase映射
```

**测试文件：**
```
frontend/tests/
├── components/
│   ├── ErrorCard.spec.ts
│   ├── RetryIndicator.spec.ts
│   ├── ErrorBoundary.spec.ts
│   └── OfflineRecovery.spec.ts
│
├── composables/
│   └── useRetry.spec.ts
│
└── stores/
│   └── error.spec.ts
│
└── integration/
│   └── theme2-error.spec.ts       # 验收测试
```

---

## 任务分解

### Task 1: 创建错误类型定义

**Files:**
- Create: `frontend/src/types/error.ts`

**错误类型定义：**
```typescript
export type ErrorType = 'api' | 'timeout' | 'unknown' | 'retry_success'

export interface ErrorState {
  type: ErrorType
  message: string
  retryCount: number
  isRecovering: boolean
  recoverAction?: () => void
  timestamp: Date
}

export interface RetryConfig {
  maxRetries: number
  baseDelay: number
  maxDelay: number
}
```

**Commit:** `feat(theme2): define error types and interfaces`

---

### Task 2: 创建error store

**Files:**
- Create: `frontend/src/stores/error.ts`
- Test: `frontend/tests/stores/error.spec.ts`

**Store功能：**
- 状态：errorState, retryCount
- Actions: setError, clearError, incrementRetry, setRecovering
- 颜色映射：每种错误类型的背景色和文本色

**测试：**
- setError/clearError正确更新状态
- incrementRetry增加计数
- 错误类型颜色映射正确

**Commit:** `feat(theme2): implement error state store`

---

### Task 3: 创建useRetry composable

**Files:**
- Create: `frontend/src/composables/useRetry.ts`
- Test: `frontend/tests/composables/useRetry.spec.ts`

**功能：**
- 指数退避算法：1s → 2s → 4s
- retryWithBackoff函数
- delay计算函数
- 重试计数器

**测试：**
- 指数退避delay正确计算
- maxRetries限制工作
- 失败后抛出正确错误

**Commit:** `feat(theme2): implement useRetry composable with exponential backoff`

---

### Task 4: 实现ErrorCard组件

**Files:**
- Create: `frontend/src/components/ErrorCard.vue`
- Test: `frontend/tests/components/ErrorCard.spec.ts`

**组件功能：**
- 4种错误类型渲染（API、Timeout、Unknown、Retry Success）
- 颜色映射（玫瑰红、琥珀、紫罗兰、绿色）
- 恢复按钮（重新请求、检查状态、查看详情、继续）
- 显示重试计数

**测试：**
- 各类型渲染正确颜色
- 恢复按钮emit retry事件
- 错误消息显示

**Commit:** `feat(theme2): implement ErrorCard component with recovery actions`

---

### Task 5: 实现RetryIndicator组件

**Files:**
- Create: `frontend/src/components/RetryIndicator.vue`
- Test: `frontend/tests/components/RetryIndicator.spec.ts`

**组件功能：**
- 显示重试次数（第1次、第2次、第3次）
- 显示等待时间
- 进度动画

**测试：**
- retryCount显示正确
- nextRetryIn显示正确
- 动画类应用

**Commit:** `feat(theme2): implement RetryIndicator component`

---

### Task 6: 实现ErrorBoundary组件

**Files:**
- Create: `frontend/src/components/ErrorBoundary.vue`
- Test: `frontend/tests/components/ErrorBoundary.spec.ts`

**组件功能：**
- 捕获子组件渲染错误
- 显示友好错误界面
- 提供刷新页面按钮
- 使用Vue 3 errorCaptured生命周期

**测试：**
- 正常子组件正常渲染
- 错误子组件显示fallback
- 刷新按钮工作

**Commit:** `feat(theme2): implement ErrorBoundary component`

---

### Task 7: 实现OfflineRecovery组件

**Files:**
- Create: `frontend/src/components/OfflineRecovery.vue`
- Test: `frontend/tests/components/OfflineRecovery.spec.ts`

**组件功能：**
- 监听navigator.onLine
- 离线时显示警告条
- 重连成功显示通知
- 自动恢复

**测试：**
- 离线状态显示警告
- 在线状态隐藏
- 重连通知显示

**Commit:** `feat(theme2): implement OfflineRecovery component`

---

### Task 8: API调用层集成重试

**Files:**
- Modify: `frontend/src/api/workflow.ts`
- Modify: `frontend/src/api/review.ts`

**集成：**
- 在API调用函数中使用useRetry
- 错误时调用errorStore.setError
- 成功时clearError

**Commit:** `feat(theme2): integrate retry logic into API calls`

---

### Task 9: Dashboard集成ErrorCard

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`

**集成：**
- 导入ErrorCard
- 在工作流错误时显示ErrorCard替代简单错误提示
- 绑定errorStore状态

**Commit:** `feat(theme2): integrate ErrorCard into Dashboard view`

---

### Task 10: App.vue集成ErrorBoundary

**Files:**
- Modify: `frontend/src/App.vue` (或确认已在router view层)

**集成：**
- ErrorBoundary包裹router-view
- 捕获全局渲染错误

**Commit:** `feat(theme2): integrate ErrorBoundary into App view`

---

### Task 11: Navbar集成OfflineRecovery

**Files:**
- Modify: `frontend/src/components/Navbar.vue`

**集成：**
- OfflineRecovery在Navbar上方显示
- 监听在线状态

**Commit:** `feat(theme2): integrate OfflineRecovery into Navbar`

---

### Task 12: 主题2验收测试

**Files:**
- Create: `frontend/tests/integration/theme2-error.spec.ts`

**验收标准（checklist）：**
- ✅ 所有API错误有明确提示和可操作的恢复按钮
- ✅ 重试机制正常工作（指数退避，最多3次）
- ✅ 离线状态正确处理（显示警告，自动恢复）

**Commit:** `test(theme2): add acceptance tests for error handling`

---

### Task 13: 创建主题2完成总结

**Files:**
- Create: `docs/superpowers/plans/2026-05-27-theme2-error-summary.md`

**总结内容：**
- 已实现组件列表
- 测试覆盖统计
- 验收状态
- 提交记录

**Commit:** `docs(theme2): add completion summary`

---

## 实施统计

- **总任务数：13个**
- **总步骤数：约50个**
- **新增文件：10个**
- **修改文件：6个**
- **测试文件：7个**
- **预计完成时间：2-3小时**

---

## 实施策略

**开发模式：** 继续在main分支开发（与主题1保持一致）
**验收顺序：** 按任务顺序逐个验收
**验收标准：** 每个组件完成后验证单元测试通过
**最终验收：** Task 12验收测试覆盖checklist

---

## Spec Self-Review

### Placeholder Scan
- ✓ 无"TBD"、"TODO"标记
- ✓ 所有组件功能描述完整
- ✓ 所有实现有明确要求

### Internal Consistency
- ✓ 架构设计与组件清单一致
- ✓ API集成位置明确
- ✓ Store与组件接口匹配

### Scope Check
- ✓ 聚焦主题2范围，无越界
- ✓ 与主题1有清晰边界
- ✓ 组件职责单一

### Ambiguity Check
- ✓ 错误类型定义明确（4种）
- ✓ 重试策略明确（指数退避）
- ✓ 验收checklist具体可执行