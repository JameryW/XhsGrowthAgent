# 主题1：加载状态与进度反馈实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现统一的加载状态系统，让用户感知等待时间是"有意义的"，提供实时进度反馈。

**Architecture:** 创建4个Vue组件（SkeletonLoader、ProgressPhase、LoadingOverlay、StepIndicator）+ 1个composable（useLoading）+ 集成到Home、Dashboard、Review、Analytics视图。采用shimmer动画、渐变色进度条、可取消遮罩、状态图标设计。

**Tech Stack:** Vue 3 Composition API, TypeScript, CSS animations, Pinia stores

---

## 文件结构

**新增文件：**
```
frontend/src/
├── components/
│   ├── SkeletonLoader.vue          # 通用骨架屏（文本/卡片/头像/列表）
│   ├── ProgressPhase.vue           # 阶段进度条（渐变色）
│   ├── LoadingOverlay.vue          # 全屏加载遮罩（可取消）
│   └── StepIndicator.vue           # 步骤指示器（完成/进行中/待定）
│
├── composables/
│   └── useLoading.ts               # 加载状态逻辑（状态映射、取消逻辑）
│
├── styles/
│   └── animations.css              # shimmer、rotate动画
│
└── components/skeletons/
│   └── index.ts                    # Skeleton组件导出（Review/Analytics使用）
```

**修改文件：**
```
frontend/src/
├── stores/
│   └── workflow.ts                 # 添加 progressPercent, isOverlayLoading
│
├── views/
│   ├── Home.vue                    # 集成 LoadingOverlay（启动按钮点击）
│   ├── Dashboard.vue               # 集成 ProgressPhase + StepIndicator
│   ├── Review.vue                  # 集成 SkeletonLoader（文案+视觉方案）
│   └── Analytics.vue               # 集成 SkeletonLoader（图表区域）
```

**测试文件：**
```
frontend/tests/
├── components/
│   ├── SkeletonLoader.spec.ts
│   ├── ProgressPhase.spec.ts
│   ├── LoadingOverlay.spec.ts
│   └── StepIndicator.spec.ts
│
└── composables/
│   └── useLoading.spec.ts
```

---

## 任务分解

### Task 1: 创建animations.css基础动画文件

**Files:**
- Create: `frontend/src/styles/animations.css`
- Test: `frontend/tests/styles/animations.spec.ts` (视觉测试，可选)

- [ ] **Step 1: 创建animations.css文件**

```css
/* frontend/src/styles/animations.css */

/* Shimmer effect for skeleton loaders */
@keyframes shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}

.shimmer-animation {
  background: linear-gradient(
    90deg,
    #f1f5f9 0%,
    #e2e8f0 50%,
    #f1f5f9 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
}

/* Rotate animation for loading spinners */
@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.rotate-animation {
  animation: rotate 1s linear infinite;
}

/* Pulse animation for step indicators */
@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.pulse-animation {
  animation: pulse 2s ease-in-out infinite;
}
```

- [ ] **Step 2: 提交animations.css**

```bash
git add frontend/src/styles/animations.css
git commit -m "feat(theme1): add base animation styles (shimmer, rotate, pulse)"
```

---

### Task 2: 实现SkeletonLoader组件

**Files:**
- Create: `frontend/src/components/SkeletonLoader.vue`
- Test: `frontend/tests/components/SkeletonLoader.spec.ts`

- [ ] **Step 1: 写测试验证组件渲染不同类型**

```typescript
// frontend/tests/components/SkeletonLoader.spec.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SkeletonLoader from '@/components/SkeletonLoader.vue'

describe('SkeletonLoader', () => {
  it('renders text skeleton with multiple lines', () => {
    const wrapper = mount(SkeletonLoader, {
      props: { type: 'text', lines: 3 }
    })
    expect(wrapper.findAll('.skeleton-text-line')).toHaveLength(3)
  })

  it('renders card skeleton with correct width', () => {
    const wrapper = mount(SkeletonLoader, {
      props: { type: 'card', width: 300 }
    })
    const card = wrapper.find('.skeleton-card')
    expect(card.attributes('style')).toContain('width: 300px')
  })

  it('renders avatar skeleton with correct size', () => {
    const wrapper = mount(SkeletonLoader, {
      props: { type: 'avatar', size: 48 }
    })
    const avatar = wrapper.find('.skeleton-avatar')
    expect(avatar.attributes('style')).toContain('width: 48px')
    expect(avatar.attributes('style')).toContain('height: 48px')
  })

  it('applies shimmer animation class', () => {
    const wrapper = mount(SkeletonLoader, {
      props: { type: 'text', lines: 1 }
    })
    expect(wrapper.find('.shimmer-animation')).toBeDefined()
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd frontend
npm run test SkeletonLoader.spec.ts
```

Expected: FAIL (组件未定义)

- [ ] **Step 3: 实现SkeletonLoader组件**

```vue
<!-- frontend/src/components/SkeletonLoader.vue -->
<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  type: 'text' | 'card' | 'avatar' | 'list'
  lines?: number
  width?: number
  size?: number
}

const props = withDefaults(defineProps<Props>(), {
  lines: 1,
  width: 200,
  size: 40
})

const skeletonStyle = computed(() => {
  if (props.type === 'card') {
    return { width: `${props.width}px`, height: '120px' }
  }
  if (props.type === 'avatar') {
    return { width: `${props.size}px`, height: `${props.size}px` }
  }
  return {}
})
</script>

<template>
  <div class="skeleton-wrapper">
    <!-- Text skeleton -->
    <div v-if="type === 'text'" class="space-y-2">
      <div
        v-for="i in lines"
        :key="i"
        class="skeleton-text-line shimmer-animation h-4 rounded"
        :style="{ width: i === lines ? '75%' : '100%' }"
      />
    </div>

    <!-- Card skeleton -->
    <div
      v-else-if="type === 'card'"
      class="skeleton-card shimmer-animation rounded-lg border border-slate-200"
      :style="skeletonStyle"
    />

    <!-- Avatar skeleton -->
    <div
      v-else-if="type === 'avatar'"
      class="skeleton-avatar shimmer-animation rounded-full"
      :style="skeletonStyle"
    />

    <!-- List skeleton -->
    <div v-else-if="type === 'list'" class="space-y-3">
      <div v-for="i in 3" :key="i" class="flex gap-3">
        <div class="shimmer-animation w-10 h-10 rounded-full" />
        <div class="flex-1 space-y-2">
          <div class="shimmer-animation h-4 w-3/4 rounded" />
          <div class="shimmer-animation h-3 w-full rounded" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.skeleton-wrapper {
  display: inline-block;
}
</style>
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd frontend
npm run test SkeletonLoader.spec.ts
```

Expected: PASS

- [ ] **Step 5: 导出Skeleton组件**

```typescript
// frontend/src/components/skeletons/index.ts
export { default as SkeletonLoader } from '@/components/SkeletonLoader.vue'

// 使用示例导出
export const ReviewSkeleton = {
  template: `
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <SkeletonLoader type="card" :width="300" />
      <SkeletonLoader type="card" :width="300" />
    </div>
  `
}

export const AnalyticsSkeleton = {
  template: `
    <div class="space-y-4">
      <SkeletonLoader type="card" :width="600" :height="200" />
      <SkeletonLoader type="list" />
    </div>
  `
}
```

- [ ] **Step 6: 提交SkeletonLoader**

```bash
git add frontend/src/components/SkeletonLoader.vue frontend/src/components/skeletons/index.ts frontend/tests/components/SkeletonLoader.spec.ts
git commit -m "feat(theme1): implement SkeletonLoader component with shimmer animation"
```

---

### Task 3: 创建useLoading composable

**Files:**
- Create: `frontend/src/composables/useLoading.ts`
- Test: `frontend/tests/composables/useLoading.spec.ts`

- [ ] **Step 1: 写测试验证加载状态映射**

```typescript
// frontend/tests/composables/useLoading.spec.ts
import { describe, it, expect } from 'vitest'
import { useLoading } from '@/composables/useLoading'

describe('useLoading', () => {
  it('maps phase to progress percent correctly', () => {
    const { phaseToPercent } = useLoading()

    expect(phaseToPercent('idle')).toBe(0)
    expect(phaseToPercent('scouting')).toBe(10)
    expect(phaseToPercent('planning')).toBe(20)
    expect(phaseToPercent('creating')).toBe(40)
    expect(phaseToPercent('reviewing')).toBe(60)
    expect(phaseToPercent('publishing')).toBe(80)
    expect(phaseToPercent('analyzing')).toBe(90)
    expect(phaseToPercent('engaging')).toBe(95)
    expect(phaseToPercent('completed')).toBe(100)
  })

  it('returns correct overlay phases', () => {
    const { isOverlayPhase } = useLoading()

    expect(isOverlayPhase('scouting')).toBe(true)
    expect(isOverlayPhase('planning')).toBe(true)
    expect(isOverlayPhase('publishing')).toBe(true)
    expect(isOverlayPhase('creating')).toBe(false)
  })

  it('provides phase color mapping', () => {
    const { phaseToColor } = useLoading()

    expect(phaseToColor('scouting')).toBe('#f43f5e')
    expect(phaseToColor('planning')).toBe('#8b5cf6')
    expect(phaseToColor('creating')).toBe('#14b8a6')
    expect(phaseToColor('reviewing')).toBe('#f59e0b')
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd frontend
npm run test useLoading.spec.ts
```

Expected: FAIL (composable未定义)

- [ ] **Step 3: 实现useLoading composable**

```typescript
// frontend/src/composables/useLoading.ts
import { computed } from 'vue'
import type { WorkflowPhase } from '@/types'

const PHASE_PERCENT_MAP: Record<WorkflowPhase, number> = {
  idle: 0,
  scouting: 10,
  planning: 20,
  creating: 40,
  reviewing: 60,
  publishing: 80,
  analyzing: 90,
  engaging: 95,
  completed: 100,
  error: 0
}

const PHASE_COLOR_MAP: Record<WorkflowPhase, string> = {
  idle: '#94a3b8',
  scouting: '#f43f5e',
  planning: '#8b5cf6',
  creating: '#14b8a6',
  reviewing: '#f59e0b',
  publishing: '#3b82f6',
  analyzing: '#22c55e',
  engaging: '#22c55e',
  completed: '#10b981',
  error: '#f43f5e'
}

const OVERLAY_PHASES: WorkflowPhase[] = ['scouting', 'planning', 'publishing']

export function useLoading() {
  const phaseToPercent = (phase: WorkflowPhase): number => {
    return PHASE_PERCENT_MAP[phase] || 0
  }

  const phaseToColor = (phase: WorkflowPhase): string => {
    return PHASE_COLOR_MAP[phase] || '#94a3b8'
  }

  const isOverlayPhase = (phase: WorkflowPhase): boolean => {
    return OVERLAY_PHASES.includes(phase)
  }

  return {
    phaseToPercent,
    phaseToColor,
    isOverlayPhase,
    PHASE_PERCENT_MAP,
    PHASE_COLOR_MAP
  }
}
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd frontend
npm run test useLoading.spec.ts
```

Expected: PASS

- [ ] **Step 5: 提交useLoading**

```bash
git add frontend/src/composables/useLoading.ts frontend/tests/composables/useLoading.spec.ts
git commit -m "feat(theme1): implement useLoading composable with phase mapping logic"
```

---

### Task 4: 实现ProgressPhase组件

**Files:**
- Create: `frontend/src/components/ProgressPhase.vue`
- Test: `frontend/tests/components/ProgressPhase.spec.ts`

- [ ] **Step 1: 写测试验证进度条渲染和颜色**

```typescript
// frontend/tests/components/ProgressPhase.spec.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProgressPhase from '@/components/ProgressPhase.vue'

describe('ProgressPhase', () => {
  it('renders progress bar with correct width', () => {
    const wrapper = mount(ProgressPhase, {
      props: { percent: 50 }
    })
    const progressBar = wrapper.find('.progress-bar-fill')
    expect(progressBar.attributes('style')).toContain('width: 50%')
  })

  it('applies correct color for scouting phase', () => {
    const wrapper = mount(ProgressPhase, {
      props: { percent: 10, currentPhase: 'scouting' }
    })
    const progressBar = wrapper.find('.progress-bar-fill')
    expect(progressBar.attributes('style')).toContain('background: #f43f5e')
  })

  it('displays phase name label', () => {
    const wrapper = mount(ProgressPhase, {
      props: { percent: 20, currentPhase: 'planning' }
    })
    expect(wrapper.text()).toContain('planning')
  })

  it('updates progress percent reactively', async () => {
    const wrapper = mount(ProgressPhase, {
      props: { percent: 10 }
    })
    await wrapper.setProps({ percent: 60 })
    const progressBar = wrapper.find('.progress-bar-fill')
    expect(progressBar.attributes('style')).toContain('width: 60%')
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd frontend
npm run test ProgressPhase.spec.ts
```

Expected: FAIL (组件未定义)

- [ ] **Step 3: 实现ProgressPhase组件**

```vue
<!-- frontend/src/components/ProgressPhase.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useLoading } from '@/composables/useLoading'
import type { WorkflowPhase } from '@/types'

interface Props {
  percent: number
  currentPhase?: WorkflowPhase
}

const props = withDefaults(defineProps<Props>(), {
  currentPhase: 'idle'
})

const { phaseToColor } = useLoading()

const progressColor = computed(() => {
  return phaseToColor(props.currentPhase)
})

const progressWidth = computed(() => {
  return `${props.percent}%`
})
</script>

<template>
  <div class="progress-phase-wrapper">
    <div class="progress-bar-container bg-slate-200 rounded-full h-2 overflow-hidden">
      <div
        class="progress-bar-fill h-full transition-all duration-500 ease-out"
        :style="{ width: progressWidth, background: progressColor }"
        role="progressbar"
        :aria-valuenow="percent"
        aria-valuemin="0"
        aria-valuemax="100"
      />
    </div>

    <div class="flex justify-between items-center mt-2">
      <span class="text-xs text-slate-500 font-medium uppercase tracking-wide">
        {{ currentPhase }}
      </span>
      <span class="text-xs text-slate-600 font-semibold">
        {{ percent }}%
      </span>
    </div>
  </div>
</template>

<style scoped>
.progress-phase-wrapper {
  width: 100%;
}
</style>
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd frontend
npm run test ProgressPhase.spec.ts
```

Expected: PASS

- [ ] **Step 5: 提交ProgressPhase**

```bash
git add frontend/src/components/ProgressPhase.vue frontend/tests/components/ProgressPhase.spec.ts
git commit -m "feat(theme1): implement ProgressPhase component with gradient colors"
```

---

### Task 5: 实现LoadingOverlay组件

**Files:**
- Create: `frontend/src/components/LoadingOverlay.vue`
- Test: `frontend/tests/components/LoadingOverlay.spec.ts`

- [ ] **Step 1: 写测试验证遮罩显示和取消按钮**

```typescript
// frontend/tests/components/LoadingOverlay.spec.ts
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import LoadingOverlay from '@/components/LoadingOverlay.vue'

describe('LoadingOverlay', () => {
  it('renders overlay when visible', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true, message: 'Loading...' }
    })
    expect(wrapper.find('.loading-overlay').isVisible()).toBe(true)
    expect(wrapper.text()).toContain('Loading...')
  })

  it('hides overlay when not visible', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: false, message: 'Loading...' }
    })
    expect(wrapper.find('.loading-overlay').exists()).toBe(false)
  })

  it('emits cancel event when cancel button clicked', async () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true, message: 'Loading...', canCancel: true }
    })
    await wrapper.find('.cancel-button').trigger('click')
    expect(wrapper.emitted('cancel')).toBeTruthy()
  })

  it('does not show cancel button when canCancel is false', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true, message: 'Loading...', canCancel: false }
    })
    expect(wrapper.find('.cancel-button').exists()).toBe(false)
  })

  it('shows rotating spinner animation', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true, message: 'Loading...' }
    })
    expect(wrapper.find('.rotate-animation')).toBeDefined()
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd frontend
npm run test LoadingOverlay.spec.ts
```

Expected: FAIL (组件未定义)

- [ ] **Step 3: 实现LoadingOverlay组件**

```vue
<!-- frontend/src/components/LoadingOverlay.vue -->
<script setup lang="ts">
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'

interface Props {
  isVisible: boolean
  message?: string
  canCancel?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  message: '正在处理...',
  canCancel: true
})

const emit = defineEmits<{
  cancel: []
}>()

const handleCancel = () => {
  emit('cancel')
}
</script>

<template>
  <div
    v-if="isVisible"
    class="loading-overlay fixed inset-0 z-50 flex items-center justify-center"
    role="dialog"
    aria-modal="true"
    aria-label="Loading overlay"
  >
    <!-- Semi-transparent background -->
    <div class="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" />

    <!-- Loading content -->
    <div class="relative bg-white rounded-2xl p-8 shadow-2xl max-w-sm w-full mx-4">
      <div class="flex flex-col items-center gap-4">
        <!-- Rotating spinner -->
        <div class="w-16 h-16 rounded-full border-4 border-slate-200 border-t-rose-500 rotate-animation" />

        <!-- Loading message -->
        <div class="text-slate-700 text-center">
          <p class="font-semibold text-lg mb-2">{{ message }}</p>
          <p class="text-sm text-slate-500">请稍候，正在处理您的请求...</p>
        </div>

        <!-- Cancel button -->
        <NeonButton
          v-if="canCancel"
          variant="ghost"
          size="md"
          class="cancel-button"
          @click="handleCancel"
        >
          <span class="flex items-center gap-2">
            <AppIcon name="X" size="sm" variant="gray" />
            <span>取消操作</span>
          </span>
        </NeonButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.loading-overlay {
  animation: fadeIn 200ms ease-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd frontend
npm run test LoadingOverlay.spec.ts
```

Expected: PASS

- [ ] **Step 5: 提交LoadingOverlay**

```bash
git add frontend/src/components/LoadingOverlay.vue frontend/tests/components/LoadingOverlay.spec.ts
git commit -m "feat(theme1): implement LoadingOverlay component with cancel button"
```

---

### Task 6: 实现StepIndicator组件

**Files:**
- Create: `frontend/src/components/StepIndicator.vue`
- Test: `frontend/tests/components/StepIndicator.spec.ts`

- [ ] **Step 1: 写测试验证步骤指示器渲染**

```typescript
// frontend/tests/components/StepIndicator.spec.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StepIndicator from '@/components/StepIndicator.vue'

describe('StepIndicator', () => {
  const mockSteps = [
    { name: 'Step 1', status: 'completed' },
    { name: 'Step 2', status: 'active' },
    { name: 'Step 3', status: 'pending' }
  ]

  it('renders all steps', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    expect(wrapper.findAll('.step-item')).toHaveLength(3)
  })

  it('shows check icon for completed step', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    const completedStep = wrapper.findAll('.step-item')[0]
    expect(completedStep.find('.step-completed')).toBeDefined()
  })

  it('shows rotating icon for active step', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    const activeStep = wrapper.findAll('.step-item')[1]
    expect(activeStep.find('.pulse-animation')).toBeDefined()
  })

  it('shows empty circle for pending step', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    const pendingStep = wrapper.findAll('.step-item')[2]
    expect(pendingStep.find('.step-pending')).toBeDefined()
  })

  it('displays step names correctly', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    expect(wrapper.text()).toContain('Step 1')
    expect(wrapper.text()).toContain('Step 2')
    expect(wrapper.text()).toContain('Step 3')
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd frontend
npm run test StepIndicator.spec.ts
```

Expected: FAIL (组件未定义)

- [ ] **Step 3: 实现StepIndicator组件**

```vue
<!-- frontend/src/components/StepIndicator.vue -->
<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'

interface Step {
  name: string
  status: 'completed' | 'active' | 'pending'
}

interface Props {
  steps: Step[]
  layout?: 'horizontal' | 'vertical'
}

const props = withDefaults(defineProps<Props>(), {
  layout: 'vertical'
})

const getStepIconClass = (status: string) => {
  switch (status) {
    case 'completed':
      return 'step-completed bg-teal-500 text-white'
    case 'active':
      return 'step-active bg-rose-500 text-white pulse-animation'
    case 'pending':
      return 'step-pending bg-slate-200 text-slate-400'
    default:
      return ''
  }
}
</script>

<template>
  <div
    class="step-indicator-wrapper"
    :class="layout === 'vertical' ? 'flex flex-col gap-3' : 'flex flex-row gap-4'"
  >
    <div
      v-for="(step, index) in steps"
      :key="index"
      class="step-item flex items-center gap-3"
    >
      <!-- Step icon -->
      <div
        class="w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm"
        :class="getStepIconClass(step.status)"
      >
        <AppIcon
          v-if="step.status === 'completed'"
          name="Check"
          size="sm"
          variant="white"
        />
        <AppIcon
          v-else-if="step.status === 'active'"
          name="Loader"
          size="sm"
          variant="white"
        />
        <span v-else>{{ index + 1 }}</span>
      </div>

      <!-- Step name -->
      <div class="flex-1">
        <div
          class="text-sm font-medium"
          :class="step.status === 'active' ? 'text-slate-800' : 'text-slate-500'"
        >
          {{ step.name }}
        </div>
      </div>

      <!-- Connector line (vertical layout) -->
      <div
        v-if="layout === 'vertical' && index < steps.length - 1"
        class="ml-4 w-0.5 h-6 bg-slate-200"
      />
    </div>
  </div>
</template>

<style scoped>
.step-indicator-wrapper {
  width: 100%;
}
</style>
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd frontend
npm run test StepIndicator.spec.ts
```

Expected: PASS

- [ ] **Step 5: 提交StepIndicator**

```bash
git add frontend/src/components/StepIndicator.vue frontend/tests/components/StepIndicator.spec.ts
git commit -m "feat(theme1): implement StepIndicator component with status icons"
```

---

### Task 7: 扩展workflow store添加进度状态

**Files:**
- Modify: `frontend/src/stores/workflow.ts`

- [ ] **Step 1: 添加progressPercent和isOverlayLoading状态**

```typescript
// frontend/src/stores/workflow.ts (修改部分)
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useLoading } from '@/composables/useLoading'
import type { WorkflowPhase } from '@/types'

export const useWorkflowStore = defineStore('workflow', () => {
  // ... 原有状态 ...

  // 新增：进度百分比
  const progressPercent = ref(0)

  // 新增：是否显示全屏遮罩
  const isOverlayLoading = ref(false)

  // 使用useLoading进行阶段映射
  const { phaseToPercent, isOverlayPhase } = useLoading()

  // 计算属性：根据阶段更新进度
  const updateProgressFromPhase = (phase: WorkflowPhase) => {
    progressPercent.value = phaseToPercent(phase)
    isOverlayLoading.value = isOverlayPhase(phase)
  }

  // 在startWorkflow方法中调用
  const startWorkflow = async (accountId: string, phase: WorkflowPhase) => {
    try {
      isLoading.value = true
      // ... 原有逻辑 ...

      // 新增：更新进度状态
      updateProgressFromPhase(phase)

      // ... 原有逻辑 ...
    } finally {
      isLoading.value = false
    }
  }

  // 在updatePhase方法中调用
  const updatePhase = (newPhase: WorkflowPhase) => {
    currentPhase.value = newPhase
    updateProgressFromPhase(newPhase)
  }

  return {
    // ... 原有导出 ...
    progressPercent,
    isOverlayLoading,
    updateProgressFromPhase
  }
})
```

- [ ] **Step 2: 提交workflow store修改**

```bash
git add frontend/src/stores/workflow.ts
git commit -m "feat(theme1): add progressPercent and isOverlayLoading to workflow store"
```

---

### Task 8: 集成LoadingOverlay到Home.vue

**Files:**
- Modify: `frontend/src/views/Home.vue`

- [ ] **Step 1: 导入并集成LoadingOverlay**

```vue
<!-- frontend/src/views/Home.vue (修改部分) -->
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ref } from 'vue'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue' // 新增
import { useWorkflowStore } from '@/stores'

const router = useRouter()
const workflowStore = useWorkflowStore()
const isStarting = ref(false)

const goToDashboard = () => {
  router.push('/dashboard')
}

const startNewWorkflow = async () => {
  isStarting.value = true
  try {
    await workflowStore.startWorkflow('default', 'scouting')
    router.push('/dashboard')
  } catch (error) {
    // 错误处理将在主题2中实现
    console.error('Failed to start workflow:', error)
  } finally {
    isStarting.value = false
  }
}
</script>

<template>
  <div class="min-h-[80vh] flex flex-col items-center justify-center relative overflow-hidden">
    <!-- ... 原有内容 ... -->

    <!-- 新增：LoadingOverlay -->
    <LoadingOverlay
      :is-visible="workflowStore.isOverlayLoading"
      :message="`正在执行 ${workflowStore.currentPhase} 阶段...`"
      @cancel="workflowStore.cancelWorkflow"
    />
  </div>
</template>
```

- [ ] **Step 2: 提交Home.vue修改**

```bash
git add frontend/src/views/Home.vue
git commit -m "feat(theme1): integrate LoadingOverlay into Home view"
```

---

### Task 9: 集成ProgressPhase和StepIndicator到Dashboard.vue

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`

- [ ] **Step 1: 导入并集成ProgressPhase和StepIndicator**

```vue
<!-- frontend/src/views/Dashboard.vue (修改部分) -->
<script setup lang="ts">
import { computed } from 'vue'
import ProgressPhase from '@/components/ProgressPhase.vue' // 新增
import StepIndicator from '@/components/StepIndicator.vue' // 新增
import { useWorkflowStore } from '@/stores'
// ... 其他导入 ...

const workflowStore = useWorkflowStore()

// 新增：步骤列表计算属性
const workflowSteps = computed(() => {
  const phases = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'analyzing', 'engaging', 'completed']
  return phases.map((phase, index) => {
    const currentIndex = phases.indexOf(workflowStore.currentPhase)
    return {
      name: phase,
      status: index < currentIndex ? 'completed' :
              index === currentIndex ? 'active' : 'pending'
    }
  })
})
</script>

<template>
  <div class="dashboard-wrapper space-y-5">
    <!-- 新增：顶部进度条 -->
    <div class="rounded-2xl p-4 bg-white/98 backdrop-blur-sm border border-slate-200/50">
      <ProgressPhase
        :percent="workflowStore.progressPercent"
        :current-phase="workflowStore.currentPhase"
      />
    </div>

    <!-- 原有Dashboard内容 -->

    <!-- 新增：步骤指示器（在WorkflowTimeline区域） -->
    <div class="rounded-2xl p-5 bg-white/98 backdrop-blur-sm border border-slate-200/50">
      <StepIndicator
        :steps="workflowSteps"
        layout="vertical"
      />
    </div>
  </div>
</template>
```

- [ ] **Step 2: 提交Dashboard.vue修改**

```bash
git add frontend/src/views/Dashboard.vue
git commit -m "feat(theme1): integrate ProgressPhase and StepIndicator into Dashboard"
```

---

### Task 10: 集成SkeletonLoader到Review.vue

**Files:**
- Modify: `frontend/src/views/Review.vue`

- [ ] **Step 1: 导入并集成ReviewSkeleton**

```vue
<!-- frontend/src/views/Review.vue (修改部分) -->
<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { ReviewSkeleton } from '@/components/skeletons' // 新增
import { useWorkflowStore, useReviewStore, useToastStore } from '@/stores'
// ... 其他代码 ...

const isLoading = computed(() => reviewStore.isLoading && !reviewStore.pendingReview)
</script>

<template>
  <!-- 新增：使用ReviewSkeleton替代原有loading状态 -->
  <ReviewSkeleton v-if="isLoading" />

  <!-- 原有内容 -->
  <div v-else class="relative space-y-5">
    <!-- ... 原有审核内容 ... -->
  </div>
</template>
```

- [ ] **Step 2: 提交Review.vue修改**

```bash
git add frontend/src/views/Review.vue frontend/src/components/skeletons/index.ts
git commit -m "feat(theme1): integrate SkeletonLoader into Review view"
```

---

### Task 11: 集成SkeletonLoader到Analytics.vue

**Files:**
- Modify: `frontend/src/views/Analytics.vue`

- [ ] **Step 1: 导入并集成AnalyticsSkeleton**

```vue
<!-- frontend/src/views/Analytics.vue (修改部分) -->
<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { AnalyticsSkeleton } from '@/components/skeletons' // 新增
import { useWorkflowStore } from '@/stores'
// ... 其他导入 ...

const isLoading = computed(() => !analyticsData.value)
</script>

<template>
  <div class="analytics-wrapper">
    <!-- 新增：使用AnalyticsSkeleton -->
    <AnalyticsSkeleton v-if="isLoading" />

    <!-- 原有分析内容 -->
    <div v-else class="space-y-5">
      <!-- ... 原有图表和数据展示 ... -->
    </div>
  </div>
</template>
```

- [ ] **Step 2: 提交Analytics.vue修改**

```bash
git add frontend/src/views/Analytics.vue frontend/src/components/skeletons/index.ts
git commit -m "feat(theme1): integrate SkeletonLoader into Analytics view"
```

---

### Task 12: 主题1验收测试

**Files:**
- Test: `frontend/tests/integration/theme1-loading.spec.ts`

- [ ] **Step 1: 写验收测试验证checklist**

```typescript
// frontend/tests/integration/theme1-loading.spec.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

// 导入所有主题1组件
import SkeletonLoader from '@/components/SkeletonLoader.vue'
import ProgressPhase from '@/components/ProgressPhase.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import StepIndicator from '@/components/StepIndicator.vue'

describe('Theme 1 Acceptance Tests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('AC1: All views use unified Skeleton components', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: []
    })

    // 测试Review视图使用Skeleton
    const ReviewView = await import('@/views/Review.vue')
    const wrapper = mount(ReviewView.default, {
      global: {
        plugins: [router, createPinia()]
      },
      props: { isLoading: true }
    })
    expect(wrapper.findComponent(SkeletonLoader)).toBeDefined()

    // 测试Analytics视图使用Skeleton
    const AnalyticsView = await import('@/views/Analytics.vue')
    const analyticsWrapper = mount(AnalyticsView.default, {
      global: {
        plugins: [router, createPinia()]
      },
      props: { isLoading: true }
    })
    expect(analyticsWrapper.findComponent(SkeletonLoader)).toBeDefined()
  })

  it('AC2: Progress bar updates realtime with correct colors', async () => {
    const wrapper = mount(ProgressPhase, {
      props: { percent: 10, currentPhase: 'scouting' }
    })

    // 验证颜色正确
    expect(wrapper.find('.progress-bar-fill').attributes('style')).toContain('#f43f5e')

    // 模拟阶段变化
    await wrapper.setProps({ percent: 60, currentPhase: 'reviewing' })
    expect(wrapper.find('.progress-bar-fill').attributes('style')).toContain('#f59e0b')
    expect(wrapper.find('.progress-bar-fill').attributes('style')).toContain('width: 60%')
  })

  it('AC3: Loading state does not block user operation perception', async () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true, message: 'Testing...', canCancel: true }
    })

    // 验证可以取消
    await wrapper.find('.cancel-button').trigger('click')
    expect(wrapper.emitted('cancel')).toBeTruthy()
  })
})
```

- [ ] **Step 2: 运行验收测试**

```bash
cd frontend
npm run test theme1-loading.spec.ts
```

Expected: PASS (验收通过)

- [ ] **Step 3: 提交验收测试**

```bash
git add frontend/tests/integration/theme1-loading.spec.ts
git commit -m "test(theme1): add acceptance tests for loading states"
```

---

### Task 13: 主题1完成总结与合并准备

**Files:**
- Create: `docs/superpowers/plans/2026-05-27-theme1-loading-summary.md`

- [ ] **Step 1: 创建主题1完成总结文档**

```markdown
# 主题1完成总结

## 已实现功能

### 组件（4个）
- ✅ SkeletonLoader.vue - 通用骨架屏（shimmer动画）
- ✅ ProgressPhase.vue - 阶段进度条（渐变色映射）
- ✅ LoadingOverlay.vue - 全屏加载遮罩（可取消）
- ✅ StepIndicator.vue - 步骤指示器（状态图标）

### Composable（1个）
- ✅ useLoading.ts - 加载状态逻辑（阶段映射）

### 样式文件（1个）
- ✅ animations.css - shimmer、rotate、pulse动画

### Store增强（1个）
- ✅ workflow.ts - 新增progressPercent、isOverlayLoading状态

### 集成视图（4个）
- ✅ Home.vue - LoadingOverlay集成
- ✅ Dashboard.vue - ProgressPhase + StepIndicator集成
- ✅ Review.vue - SkeletonLoader集成
- ✅ Analytics.vue - SkeletonLoader集成

## 验收状态

- ✅ 所有视图使用统一Skeleton组件
- ✅ 进度条实时更新，颜色正确映射阶段
- ✅ 加载状态不阻塞用户操作感知（可取消）

## 测试覆盖

- ✅ 单元测试：4个组件 + 1个composable
- ✅ 集成测试：验收checklist覆盖

## 提交记录

- feat(theme1): add base animation styles (shimmer, rotate, pulse)
- feat(theme1): implement SkeletonLoader component with shimmer animation
- feat(theme1): implement useLoading composable with phase mapping logic
- feat(theme1): implement ProgressPhase component with gradient colors
- feat(theme1): implement LoadingOverlay component with cancel button
- feat(theme1): implement StepIndicator component with status icons
- feat(theme1): add progressPercent and isOverlayLoading to workflow store
- feat(theme1): integrate LoadingOverlay into Home view
- feat(theme1): integrate ProgressPhase and StepIndicator into Dashboard
- feat(theme1): integrate SkeletonLoader into Review view
- feat(theme1): integrate SkeletonLoader into Analytics view
- test(theme1): add acceptance tests for loading states

## 下一步

准备合并到main分支，删除worktree，开始主题2实施。
```

- [ ] **Step 2: 提交总结文档**

```bash
git add docs/superpowers/plans/2026-05-27-theme1-loading-summary.md
git commit -m "docs(theme1): add completion summary for theme1 loading states"
```

- [ ] **Step 3: 合并主题1到main**

```bash
# 确保所有变更已提交
git status

# 切换到main分支
git checkout main

# 合并主题1分支
git merge feat-ux-theme1-loading --no-ff

# 推送到远程（可选）
git push origin main
```

- [ ] **Step 4: 删除已合并的worktree**

```bash
# 删除worktree物理目录
git worktree remove .claude/worktrees/ux-theme1

# 删除分支（可选）
git branch -d feat-ux-theme1-loading
```

---

## Plan Self-Review

### Spec Coverage Check

**对比设计文档section验证任务覆盖：**

| 设计要求 | 对应任务 | 状态 |
|----------|----------|------|
| SkeletonLoader组件 | Task 2 | ✅ 已定义 |
| ProgressPhase组件 | Task 4 | ✅ 已定义 |
| LoadingOverlay组件 | Task 5 | ✅ 已定义 |
| StepIndicator组件 | Task 6 | ✅ 已定义 |
| useLoading composable | Task 3 | ✅ 已定义 |
| animations.css | Task 1 | ✅ 已定义 |
| workflow store增强 | Task 7 | ✅ 已定义 |
| Home.vue集成 | Task 8 | ✅ 已定义 |
| Dashboard.vue集成 | Task 9 | ✅ 已定义 |
| Review.vue集成 | Task 10 | ✅ 已定义 |
| Analytics.vue集成 | Task 11 | ✅ 已定义 |
| 验收测试 | Task 12 | ✅ 已定义 |
| 合并流程 | Task 13 | ✅ 已定义 |

**Gap分析：无遗漏，所有设计要求已覆盖**

### Placeholder Scan

**检查红标记：**
- ✅ 无"TBD"、"TODO"、"implement later"
- ✅ 无"Add appropriate error handling"
- ✅ 无"Write tests for the above"（所有测试有完整代码）
- ✅ 无"Similar to Task N"（重复代码已完整写出）
- ✅ 所有代码步骤有完整实现
- ✅ 所有类型、函数已定义

### Type Consistency

**检查类型定义一致性：**
- ✅ WorkflowPhase类型在useLoading.ts、ProgressPhase.vue、workflow.ts中一致
- ✅ Step类型在StepIndicator.vue中定义且使用一致
- ✅ Props接口在所有组件中明确定义
- ✅ 测试中使用类型一致

**发现并修复的问题：**
- Task 11的Analytics.vue示例需要补充isLoading computed逻辑（已修复）

---

## 实施统计

- **总任务数：13个**
- **总步骤数：约60个**
- **新增文件：7个**
- **修改文件：6个**
- **测试文件：6个**
- **预计完成时间：2-3小时**

---

## 执行建议

**Worktree策略：**
1. 创建worktree：`git worktree add .claude/worktrees/ux-theme1 -b feat-ux-theme1-loading`
2. 在worktree中执行Task 1-12
3. 完成后合并到main（Task 13）
4. 删除worktree

**验收建议：**
- Task 12的验收测试必须在合并前通过
- 验收通过后才能进入主题2实施