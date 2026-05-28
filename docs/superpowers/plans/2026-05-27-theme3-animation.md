# 主题3：动画与过渡效果实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提升界面流畅感和专业感，通过动画传达状态变化，庆祝成功时刻增强成就感。

**Architecture:** 创建3个Vue组件（PageTransition、CelebrationEffect、AnimatedCounter）+ 增强animations.css + 集成到路由、Dashboard、Review、全局按钮。采用页面过渡、庆祝彩纸、数字动画、微交互设计。

**Tech Stack:** Vue 3 Composition API, CSS animations, Canvas for celebrations, requestAnimationFrame

---

## 文件结构

**新增文件：**
```
frontend/src/
├── components/
│   ├── PageTransition.vue        # 页面切换动画（Fade + Slide）
│   ├── CelebrationEffect.vue     # 庆祝动画系统（Confetti/Pulse/Stars）
│   └── AnimatedCounter.vue       # 数字动画（平滑递增）
│
└── composables/
│   └── useAnimation.ts           # 动画辅助逻辑（计数器、触发器）
```

**修改文件：**
```
frontend/src/
├── styles/
│   └── animations.css            # 增强微交互动画
│
├── router/
│   └── index.ts                  # 配置PageTransition默认过渡
│
├── views/
│   ├── Dashboard.vue             # AnimatedCounter进度更新
│   └── Review.vue                # CelebrationEffect庆祝动画
│
├── components/
│   └── NeonButton.vue            # 微交互旋转动画（已有，增强）
│   └── ErrorCard.vue             # 错误抖动动画
│
└── App.vue                       # PageTransition包裹router-view
```

**测试文件：**
```
frontend/tests/
├── components/
│   ├── PageTransition.spec.ts
│   ├── CelebrationEffect.spec.ts
│   └── AnimatedCounter.spec.ts
│
├── composables/
│   └── useAnimation.spec.ts
│
└── integration/
│   └── theme3-animation.spec.ts  # 验收测试
```

---

## 任务分解

### Task 1: 增强animations.css添加微交互动画

**Files:**
- Modify: `frontend/src/styles/animations.css`

**新增动画：**
```css
/* Shake animation for errors */
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  10%, 30%, 50%, 70%, 90% { transform: translateX(-4px); }
  20%, 40%, 60%, 80% { transform: translateX(4px); }
}

.shake-animation {
  animation: shake 300ms ease;
}

/* Scale bounce for success */
@keyframes scale-up-bounce {
  0% { transform: scale(0.95); }
  50% { transform: scale(1.05); }
  100% { transform: scale(1); }
}

.scale-bounce-animation {
  animation: scale-up-bounce 200ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Fade slide for page transitions */
@keyframes fade-slide-in {
  from {
    opacity: 0;
    transform: translateX(10px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.fade-slide-animation {
  animation: fade-slide-in 200ms ease-out;
}
```

**Commit:** `feat(theme3): add micro-interaction animations (shake, scale-bounce, fade-slide)`

---

### Task 2: 创建useAnimation composable

**Files:**
- Create: `frontend/src/composables/useAnimation.ts`
- Test: `frontend/tests/composables/useAnimation.spec.ts`

**功能：**
- animatedCounter(start, end, duration, onUpdate) - 数字递增动画
- triggerCelebration(type) - 触发庆祝动画
- onAnimationEnd(callback) - 动画结束回调

**测试：**
- 数字递增正确（0→100）
- 时间控制正确（500ms）
- 回调触发正确

**Commit:** `feat(theme3): implement useAnimation composable`

---

### Task 3: 实现PageTransition组件

**Files:**
- Create: `frontend/src/components/PageTransition.vue`
- Test: `frontend/tests/components/PageTransition.spec.ts`

**组件功能：**
- 使用Vue transition组件
- Fade + Slide动画（淡入淡出 + 水平滑动）
- 时长：200ms，缓动：ease-out
- 支持mode="out-in"（先出后进）

**测试：**
- 进入动画触发
- 离开动画触发
- mode="out-in"工作

**Commit:** `feat(theme3): implement PageTransition component`

---

### Task 4: 实现AnimatedCounter组件

**Files:**
- Create: `frontend/src/components/AnimatedCounter.vue`
- Test: `frontend/tests/components/AnimatedCounter.spec.ts`

**组件功能：**
- Props: value (number), duration (number, default 500ms)
- 使用useAnimation animatedCounter
- 显示递增数字
- 平滑过渡

**测试：**
- 数字从0递增到目标值
- 时间控制正确
- 响应式更新

**Commit:** `feat(theme3): implement AnimatedCounter component`

---

### Task 5: 实现CelebrationEffect组件

**Files:**
- Create: `frontend/src/components/CelebrationEffect.vue`
- Test: `frontend/tests/components/CelebrationEffect.spec.ts`

**组件功能：**
- Props: type ('confetti' | 'pulse' | 'stars'), isActive (boolean)
- Canvas绘制彩纸（从顶部飘落）
- Pulse脉冲动画（中心扩散）
- Stars星星闪烁
- requestAnimationFrame实现

**测试：**
- 触发时canvas渲染
- 结束后清理canvas
- 不同类型正确渲染

**Commit:** `feat(theme3): implement CelebrationEffect component`

---

### Task 6: Router集成PageTransition

**Files:**
- Modify: `frontend/src/router/index.ts`

**集成：**
- 配置transition-name="fade-slide"
- 设置默认过渡动画
- 确保所有路由使用过渡

**Commit:** `feat(theme3): configure PageTransition in router`

---

### Task 7: Dashboard集成AnimatedCounter

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`

**集成：**
- ProgressPhase进度百分比使用AnimatedCounter
- 替换静态数字显示

**Commit:** `feat(theme3): integrate AnimatedCounter into Dashboard`

---

### Task 8: Review集成CelebrationEffect

**Files:**
- Modify: `frontend/src/views/Review.vue`

**集成：**
- 提交成功后触发CelebrationEffect
- 监听workflowStore.phase === 'completed'
- 显示confetti彩纸动画

**Commit:** `feat(theme3): integrate CelebrationEffect into Review`

---

### Task 9: ErrorCard集成shake动画

**Files:**
- Modify: `frontend/src/components/ErrorCard.vue`

**集成：**
- ErrorCard显示时添加shake-animation类
- 错误抖动效果300ms

**Commit:** `feat(theme3): integrate shake animation into ErrorCard`

---

### Task 10: NeonButton增强loading动画

**Files:**
- Modify: `frontend/src/components/NeonButton.vue`

**增强：**
- loading状态使用rotate-animation（已有）
- success状态添加scale-bounce-animation
- 完善微交互效果

**Commit:** `feat(theme3): enhance NeonButton animations`

---

### Task 11: App.vue集成PageTransition

**Files:**
- Modify: `frontend/src/App.vue`

**集成：**
- 使用PageTransition包裹router-view
- 配置过渡动画

**Commit:** `feat(theme3): integrate PageTransition into App`

---

### Task 12: 主题3验收测试

**Files:**
- Create: `frontend/tests/integration/theme3-animation.spec.ts`

**验收标准（checklist）：**
- ✅ AC1: 页面切换流畅无卡顿（Home→Dashboard→Review）
- ✅ AC2: 完成时有庆祝动画（工作流完成触发Confetti彩纸）
- ✅ AC3: 微交互反馈及时（按钮loading旋转，错误抖动）

**Commit:** `test(theme3): add acceptance tests for animations`

---

### Task 13: 创建主题3完成总结

**Files:**
- Create: `docs/superpowers/plans/2026-05-27-theme3-animation-summary.md`

**总结内容：**
- 已实现组件列表（3个）
- 已实现composable（1个）
- 动画增强（animations.css）
- 集成视图（7个）
- 测试覆盖统计
- 验收状态
- 提交记录

**Commit:** `docs(theme3): add completion summary`

---

## 实施统计

- **总任务数：13个**
- **总步骤数：约40个**
- **新增文件：4个**
- **修改文件：8个**
- **测试文件：5个**
- **预计完成时间：1.5-2小时**

---

## 实施策略

**开发模式：** 继续在main分支开发
**验收顺序：** 按任务顺序逐个验收
**验收标准：** 每个组件完成后验证单元测试通过
**最终验收：** Task 12验收测试覆盖checklist

---

## Spec Self-Review

### Placeholder Scan
- ✓ 无"TBD"、"TODO"标记
- ✓ 所有动画时长明确定义
- ✓ 所有组件功能描述完整

### Internal Consistency
- ✓ 动画时长与组件集成一致（200ms过渡，300ms弹跳）
- ✓ Router配置与App.vue集成匹配
- ✓ CelebrationEffect类型定义明确

### Scope Check
- ✓ 聚焦主题3范围，无越界
- ✓ 与主题1/2有清晰边界
- ✓ 组件职责单一

### Ambiguity Check
- ✓ 动画规范统一（时长、缓动函数）
- ✓ Canvas实现明确（requestAnimationFrame）
- ✓ 验收checklist具体可执行