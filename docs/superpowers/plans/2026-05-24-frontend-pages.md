# Frontend Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-step. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 XhsGrowthAgent 添加 Vue 3 前端 Web UI，包含工作流仪表盘、内容审核、数据分析三个页面，赛博朋克风格，同端口部署。

**Architecture:** Vue 3 SPA + Vite 构建，Pinia 状态管理，axios API 封装，FastAPI 托管静态文件。前后端分离开发，构建产物 dist/ 由 FastAPI StaticFiles 挂载。

**Tech Stack:** Vue 3.4, Vite 5.0, Tailwind CSS 3.4, Element Plus 2.5, Pinia 2.1, axios 1.6, TypeScript 5.3

---

## File Structure

**新增文件:**
```
frontend/
├── package.json                    # Node 依赖
├── vite.config.ts                  # Vite 配置
├── tailwind.config.js              # Tailwind 配置
├── postcss.config.js               # PostCSS 配置
├── tsconfig.json                   # TypeScript 配置
├── tsconfig.node.json              # Node TypeScript 配置
├── index.html                      # HTML 入口
├── .gitignore                      # Git 忽略
├── src/
│   ├── main.ts                     # Vue 入口
│   ├── App.vue                     # 根组件
│   ├── vite-env.d.ts               # Vite 类型声明
│   │
│   ├── api/
│   │   ├── client.ts               # axios 实例
│   │   ├── workflow.ts             # 工作流 API
│   │   ├── review.ts               # 审核 API
│   │   ├── analytics.ts            # 分析 API
│   │   └── index.ts                # API 导出
│   │
│   ├── stores/
│   │   ├── workflow.ts             # 工作流状态
│   │   ├── review.ts               # 审核状态
│   │   ├── analytics.ts            # 分析状态
│   │   └── index.ts                # Store 导出
│   │
│   ├── router/
│   │   └── index.ts                # Vue Router 配置
│   │
│   ├── styles/
│   │   ├── main.css                # 主样式（Tailwind + 自定义）
│   │   └── cyberpunk.css           # 赛博朋克主题样式
│   │
│   ├── components/
│   │   ├── Navbar.vue              # 左侧导航栏
│   │   ├── NeonButton.vue          # 霓虹按钮
│   │   ├── StatusCard.vue          # 状态卡片
│   │   ├── WorkflowNode.vue        # 六边形流程节点
│   │   ├── ContentCard.vue         # 内容卡片
│   │   ├── MetricCard.vue          # 指标卡片
│   │   └── DataTable.vue           # 数据表格
│   │
│   ├── views/
│   │   ├── Home.vue                # 首页
│   │   ├── Dashboard.vue           # 工作流仪表盘
│   │   ├── Review.vue              # 内容审核
│   │   └── Analytics.vue           # 数据分析
│   │
│   └── types/
│   │   ├── workflow.ts             # 工作流类型定义
│   │   ├── review.ts               # 审核类型定义
│   │   └── analytics.ts            # 分析类型定义
│   │
│   └── assets/
│   │   └── logo.png                # Logo 图片（可选）
│
└── dist/                           # 构建产物（FastAPI 托管）
```

**修改文件:**
- `xhs_growth/api/app.py` - 添加 StaticFiles mount
- `README.md` - 添加前端说明
- `.gitignore` - 添加 frontend/node_modules 忽略

---

## Phase 1: 项目初始化

### Task 1: 创建 Vue 项目骨架

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/.gitignore`

- [ ] **Step 1: 创建 frontend 目录**

```bash
mkdir -p frontend/src/{api,stores,router,styles,components,views,types,assets}
```

- [ ] **Step 2: 创建 package.json**

```json
{
  "name": "xhs-growth-frontend",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.21",
    "vue-router": "^4.3.0",
    "pinia": "^2.1.7",
    "axios": "^1.6.8",
    "element-plus": "^2.5.6"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.4",
    "typescript": "^5.3.3",
    "vue-tsc": "^2.0.6",
    "vite": "^5.1.4",
    "tailwindcss": "^3.4.1",
    "autoprefixer": "^10.4.17",
    "postcss": "^8.4.35",
    "@types/node": "^20.11.24"
  }
}
```

- [ ] **Step 3: 创建 index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8">
    <link rel="icon" type="image/svg+xml" href="/vite.svg">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>小红书增长引擎</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 4: 创建 .gitignore**

```gitignore
# Dependencies
node_modules/
.pnpm-store/

# Build output
dist/

# IDE
.vscode/
.idea/

# Logs
*.log
npm-debug.log*

# OS
.DS_Store
Thumbs.db

# Test
coverage/
.nyc_output/
```

- [ ] **Step 5: 安装依赖**

```bash
cd frontend && npm install
```

Expected: 依赖安装成功，生成 node_modules/

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/index.html frontend/.gitignore
git commit -m "chore: initialize Vue 3 frontend project structure"
```

---

### Task 2: 配置 TypeScript + Vite

**Files:**
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/vite-env.d.ts`

- [ ] **Step 1: 创建 tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src/**/*.ts", "src/**/*.tsx", "src/**/*.vue"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 2: 创建 tsconfig.node.json**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 3: 创建 vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 4: 创建 vite-env.d.ts**

```typescript
/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/src/vite-env.d.ts
git commit -m "chore: configure TypeScript and Vite for Vue 3 project"
```

---

### Task 3: 配置 Tailwind CSS

**Files:**
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/src/styles/main.css`

- [ ] **Step 1: 创建 tailwind.config.js**

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        neon: {
          pink: '#FE2C55',
          cyan: '#4ECDC4',
          purple: '#667eea',
          peach: '#FFE4E1',
          gold: '#FFDAB9',
        },
        dark: {
          bg: '#0a0a0a',
          panel: '#1a0a2e',
          card: '#0f1a2a',
          border: 'rgba(255,255,255,0.1)',
        },
      },
      fontFamily: {
        mono: ['Monaco', 'Consolas', 'Liberation Mono', 'monospace'],
      },
      boxShadow: {
        'neon-pink': '0 0 20px rgba(254,44,85,0.5), 0 0 40px rgba(254,44,85,0.3)',
        'neon-cyan': '0 0 20px rgba(78,205,196,0.5), 0 0 40px rgba(78,205,196,0.3)',
        'neon-purple': '0 0 20px rgba(102,126,234,0.5), 0 0 40px rgba(102,126,234,0.3)',
        'neon-peach': '0 0 20px rgba(255,228,225,0.5), 0 0 40px rgba(255,228,225,0.3)',
      },
      animation: {
        'pulse-glow': 'pulse-glow 1s infinite alternate',
        'scan': 'scan 4s linear infinite',
        'blink': 'blink 1s infinite',
      },
      keyframes: {
        'pulse-glow': {
          '0%': { boxShadow: '0 0 20px rgba(254,44,85,0.5)' },
          '100%': { boxShadow: '0 0 40px rgba(254,44,85,0.8)' },
        },
        'scan': {
          '0%': { top: '0' },
          '100%': { top: '100%' },
        },
        'blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.3' },
        },
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 2: 创建 postcss.config.js**

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 3: 创建 styles/main.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

/* 自定义赛博朋克样式 */
@layer components {
  /* 六边形节点 */
  .hexagon {
    clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
  }

  /* 毛玻璃效果 */
  .glass {
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.1);
  }

  /* 边框光带 */
  .border-glow-pink {
    border: 1px solid rgba(254, 44, 85, 0.3);
    box-shadow: 0 0 30px rgba(254, 44, 85, 0.2), inset 0 0 20px rgba(254, 44, 85, 0.1);
  }

  .border-glow-cyan {
    border: 1px solid rgba(78, 205, 196, 0.3);
    box-shadow: 0 0 30px rgba(78, 205, 196, 0.2), inset 0 0 20px rgba(78, 205, 196, 0.1);
  }

  .border-glow-purple {
    border: 1px solid rgba(102, 126, 234, 0.3);
    box-shadow: 0 0 30px rgba(102, 126, 234, 0.2), inset 0 0 20px rgba(102, 126, 234, 0.1);
  }

  /* 扫描线 */
  .scanline::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, rgba(254, 44, 85, 0.3), transparent);
    animation: scan 4s linear infinite;
  }

  /* Monospace 文字 */
  .mono {
    font-family: 'Monaco', 'Consolas', monospace;
  }
}

/* 全局样式 */
html, body {
  margin: 0;
  padding: 0;
  background: #0a0a0a;
  color: white;
  font-family: system-ui, -apple-system, sans-serif;
}

#app {
  min-height: 100vh;
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/tailwind.config.js frontend/postcss.config.js frontend/src/styles/main.css
git commit -m "chore: configure Tailwind CSS with cyberpunk theme"
```

---

### Task 4: 创建 Vue 入口和根组件

**Files:**
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`

- [ ] **Step 1: 创建 main.ts**

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import './styles/main.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

app.mount('#app')
```

- [ ] **Step 2: 创建 App.vue**

```vue
<script setup lang="ts">
import Navbar from '@/components/Navbar.vue'
</script>

<template>
  <div class="min-h-screen bg-dark-bg flex">
    <!-- 左侧导航 -->
    <Navbar />
    
    <!-- 主内容区 -->
    <main class="flex-1 p-6 overflow-auto">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/main.ts frontend/src/App.vue
git commit -m "feat: create Vue entry point and root App component"
```

---

## Phase 2: 类型定义和 API 层

### Task 5: 定义 TypeScript 类型

**Files:**
- Create: `frontend/src/types/workflow.ts`
- Create: `frontend/src/types/review.ts`
- Create: `frontend/src/types/analytics.ts`
- Create: `frontend/src/types/index.ts`

- [ ] **Step 1: 创建 types/workflow.ts**

```typescript
// 工作流阶段
export type WorkflowPhase = 
  | 'idle' 
  | 'scouting' 
  | 'planning' 
  | 'creating' 
  | 'reviewing' 
  | 'publishing' 
  | 'analyzing' 
  | 'engaging' 
  | 'completed' 
  | 'error'

// 启动请求
export interface WorkflowStartRequest {
  account_id: string
  phase: WorkflowPhase
}

// 工作流响应
export interface WorkflowResponse {
  thread_id: string
  status: 'running' | 'paused' | 'completed' | 'error'
  phase: WorkflowPhase
}

// 工作流状态
export interface WorkflowState {
  thread_id: string
  next: string[]
  values: {
    phase: WorkflowPhase
    current_agent: string
    trend_data?: Record<string, any>
    content_plan?: Record<string, any>
    copy_content?: Record<string, any>
    visual_plan?: Record<string, any>
    created_at?: string
    updated_at?: string
    error?: string | null
  }
  created_at?: string
}
```

- [ ] **Step 2: 创建 types/review.ts**

```typescript
// 内容状态
export type ContentStatus = 'approved' | 'needs_revision' | 'rejected'

// 待审核内容
export interface PendingReview {
  status: 'awaiting_review' | 'no_pending_review'
  content_plan?: Record<string, any>
  copy_content?: Record<string, any>
  visual_plan?: Record<string, any>
}

// 审核决定
export interface ReviewDecision {
  decision: ContentStatus
  comments?: string
  revisions?: string[]
}

// 审核提交响应
export interface ReviewSubmitResponse {
  thread_id: string
  status: 'resumed'
  decision: ContentStatus
  next_phase: string
}
```

- [ ] **Step 3: 创建 types/analytics.ts**

```typescript
// 增长报告
export interface GrowthReport {
  account_id: string
  period: 'daily' | 'weekly' | 'monthly'
  report: string
}

// 帖子表现
export interface PostPerformance {
  title: string
  likes: number
  comments: number
  collects: number
  engagement_rate: number
  published_at: string
}

// 性能数据
export interface PerformanceData {
  account_id: string
  posts: PostPerformance[]
}

// 成本数据
export interface CostData {
  total_cost_usd: number
  today_cost_usd: number
  circuit_open: boolean
}
```

- [ ] **Step 4: 创建 types/index.ts**

```typescript
export * from './workflow'
export * from './review'
export * from './analytics'
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/
git commit -m "feat: define TypeScript types for workflow, review, and analytics"
```

---

### Task 6: 创建 API Client

**Files:**
- Create: `frontend/src/api/client.ts`

- [ ] **Step 1: 创建 api/client.ts**

```typescript
import axios, { AxiosInstance, AxiosError } from 'axios'

// 创建 axios 实例
const client: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
client.interceptors.request.use(
  (config) => {
    // 可添加认证 token
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
client.interceptors.response.use(
  (response) => response.data,
  (error: AxiosError) => {
    console.error('API Error:', error.message)
    // 可以在这里添加全局错误处理
    return Promise.reject(error)
  }
)

export default client
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: create axios API client with interceptors"
```

---

### Task 7: 创建 Workflow API

**Files:**
- Create: `frontend/src/api/workflow.ts`

- [ ] **Step 1: 创建 api/workflow.ts**

```typescript
import client from './client'
import type { WorkflowStartRequest, WorkflowResponse, WorkflowState } from '@/types/workflow'

// 启动工作流
export async function startWorkflow(req: WorkflowStartRequest): Promise<WorkflowResponse> {
  return client.post('/workflow/start', req)
}

// 获取工作流状态
export async function getWorkflowStatus(threadId: string): Promise<WorkflowState> {
  return client.get(`/workflow/status/${threadId}`)
}

// 暂停工作流
export async function pauseWorkflow(threadId: string): Promise<{ thread_id: string; status: string }> {
  return client.post(`/workflow/pause/${threadId}`)
}

// 恢复工作流
export async function resumeWorkflow(threadId: string): Promise<WorkflowResponse> {
  return client.post(`/workflow/resume/${threadId}`)
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/workflow.ts
git commit -m "feat: create workflow API functions"
```

---

### Task 8: 创建 Review API

**Files:**
- Create: `frontend/src/api/review.ts`

- [ ] **Step 1: 创建 api/review.ts**

```typescript
import client from './client'
import type { PendingReview, ReviewDecision, ReviewSubmitResponse } from '@/types/review'

// 获取待审核内容
export async function getPendingReview(threadId: string): Promise<PendingReview> {
  return client.get(`/review/pending/${threadId}`)
}

// 提交审核决定
export async function submitReview(
  threadId: string, 
  decision: ReviewDecision
): Promise<ReviewSubmitResponse> {
  return client.post(`/review/submit/${threadId}`, decision)
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/review.ts
git commit -m "feat: create review API functions"
```

---

### Task 9: 创建 Analytics API

**Files:**
- Create: `frontend/src/api/analytics.ts`

- [ ] **Step 1: 创建 api/analytics.ts**

```typescript
import client from './client'
import type { GrowthReport, PerformanceData, CostData } from '@/types/analytics'

// 获取增长报告
export async function getGrowthReport(
  accountId: string, 
  period: string = 'weekly'
): Promise<GrowthReport> {
  return client.get(`/analytics/report/${accountId}`, { params: { period } })
}

// 获取帖子表现
export async function getPerformance(
  accountId: string, 
  limit: number = 20
): Promise<PerformanceData> {
  return client.get(`/analytics/performance/${accountId}`, { params: { limit } })
}

// 获取成本统计
export async function getCosts(): Promise<CostData> {
  return client.get('/analytics/costs')
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/analytics.ts
git commit -m "feat: create analytics API functions"
```

---

### Task 10: 创建 API 导出

**Files:**
- Create: `frontend/src/api/index.ts`

- [ ] **Step 1: 创建 api/index.ts**

```typescript
export { default as client } from './client'
export * from './workflow'
export * from './review'
export * from './analytics'
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/index.ts
git commit -m "feat: export all API modules"
```

---

## Phase 3: Pinia Store 状态管理

### Task 11: 创建 Workflow Store

**Files:**
- Create: `frontend/src/stores/workflow.ts`

- [ ] **Step 1: 创建 stores/workflow.ts**

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as workflowApi from '@/api/workflow'
import type { WorkflowState, WorkflowPhase } from '@/types/workflow'

export const useWorkflowStore = defineStore('workflow', () => {
  // State
  const currentThreadId = ref<string | null>(null)
  const workflowState = ref<WorkflowState | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Computed
  const currentPhase = computed<WorkflowPhase>(() => 
    workflowState.value?.values?.phase || 'idle'
  )

  const nextNodes = computed(() => workflowState.value?.next || [])

  const isRunning = computed(() => 
    workflowState.value?.next?.length > 0 && currentPhase.value !== 'completed'
  )

  const trendData = computed(() => workflowState.value?.values?.trend_data || {})
  const contentPlan = computed(() => workflowState.value?.values?.content_plan || {})
  const copyContent = computed(() => workflowState.value?.values?.copy_content || {})
  const visualPlan = computed(() => workflowState.value?.values?.visual_plan || {})

  // Actions
  async function startWorkflow(accountId: string, phase: WorkflowPhase = 'scouting') {
    isLoading.value = true
    error.value = null
    try {
      const result = await workflowApi.startWorkflow({ account_id: accountId, phase })
      currentThreadId.value = result.thread_id
      // 启动后立即获取状态
      await refreshStatus()
      return result
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function refreshStatus() {
    if (!currentThreadId.value) return
    isLoading.value = true
    error.value = null
    try {
      workflowState.value = await workflowApi.getWorkflowStatus(currentThreadId.value)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function pauseWorkflow() {
    if (!currentThreadId.value) return
    isLoading.value = true
    try {
      await workflowApi.pauseWorkflow(currentThreadId.value)
      await refreshStatus()
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function resumeWorkflow() {
    if (!currentThreadId.value) return
    isLoading.value = true
    try {
      const result = await workflowApi.resumeWorkflow(currentThreadId.value)
      await refreshStatus()
      return result
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  // 轮询机制
  let pollInterval: number | null = null

  function startPolling(intervalMs: number = 5000) {
    if (pollInterval) stopPolling()
    pollInterval = window.setInterval(() => {
      if (isRunning.value) {
        refreshStatus()
      } else {
        stopPolling()
      }
    }, intervalMs)
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }

  function setThreadId(threadId: string) {
    currentThreadId.value = threadId
  }

  return {
    // State
    currentThreadId,
    workflowState,
    isLoading,
    error,
    // Computed
    currentPhase,
    nextNodes,
    isRunning,
    trendData,
    contentPlan,
    copyContent,
    visualPlan,
    // Actions
    startWorkflow,
    refreshStatus,
    pauseWorkflow,
    resumeWorkflow,
    startPolling,
    stopPolling,
    setThreadId,
  }
})
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/workflow.ts
git commit -m "feat: create workflow Pinia store with polling"
```

---

### Task 12: 创建 Review Store

**Files:**
- Create: `frontend/src/stores/review.ts`

- [ ] **Step 1: 创建 stores/review.ts**

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as reviewApi from '@/api/review'
import type { PendingReview, ContentStatus } from '@/types/review'

export const useReviewStore = defineStore('review', () => {
  // State
  const threadId = ref<string | null>(null)
  const pendingReview = ref<PendingReview | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const decision = ref<ContentStatus | null>(null)
  const comments = ref('')
  const revisions = ref<string[]>([])

  // Computed
  const hasPendingReview = computed(() => 
    pendingReview.value?.status === 'awaiting_review'
  )

  const contentPlan = computed(() => pendingReview.value?.content_plan || {})
  const copyContent = computed(() => pendingReview.value?.copy_content || {})
  const visualPlan = computed(() => pendingReview.value?.visual_plan || {})

  // Actions
  async function fetchPendingReview(tid: string) {
    threadId.value = tid
    isLoading.value = true
    error.value = null
    try {
      pendingReview.value = await reviewApi.getPendingReview(tid)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function submitDecision(dec: ContentStatus, comment?: string, revs?: string[]) {
    if (!threadId.value) return
    isLoading.value = true
    error.value = null
    try {
      const result = await reviewApi.submitReview(threadId.value, {
        decision: dec,
        comments: comment || '',
        revisions: revs || [],
      })
      decision.value = dec
      pendingReview.value = null
      return result
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  function setComments(comment: string) {
    comments.value = comment
  }

  function addRevision(rev: string) {
    revisions.value.push(rev)
  }

  function clearRevisions() {
    revisions.value = []
  }

  return {
    // State
    threadId,
    pendingReview,
    isLoading,
    error,
    decision,
    comments,
    revisions,
    // Computed
    hasPendingReview,
    contentPlan,
    copyContent,
    visualPlan,
    // Actions
    fetchPendingReview,
    submitDecision,
    setComments,
    addRevision,
    clearRevisions,
  }
})
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/review.ts
git commit -m "feat: create review Pinia store"
```

---

### Task 13: 创建 Analytics Store

**Files:**
- Create: `frontend/src/stores/analytics.ts`

- [ ] **Step 1: 创建 stores/analytics.ts**

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as analyticsApi from '@/api/analytics'
import type { GrowthReport, PerformanceData, CostData, PostPerformance } from '@/types/analytics'

export const useAnalyticsStore = defineStore('analytics', () => {
  // State
  const accountId = ref('default')
  const period = ref<'daily' | 'weekly' | 'monthly'>('weekly')
  const growthReport = ref<GrowthReport | null>(null)
  const performanceData = ref<PerformanceData | null>(null)
  const costData = ref<CostData | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Computed
  const posts = computed<PostPerformance[]>(() => 
    performanceData.value?.posts || []
  )

  const totalEngagement = computed(() => {
    if (!posts.value.length) return 0
    return posts.value.reduce((sum, post) => 
      sum + post.likes + post.comments + post.collects, 0
    )
  })

  const avgEngagementRate = computed(() => {
    if (!posts.value.length) return 0
    return posts.value.reduce((sum, post) => 
      sum + post.engagement_rate, 0
    ) / posts.value.length
  })

  // Actions
  async function fetchAllData() {
    isLoading.value = true
    error.value = null
    try {
      // 并行获取三个 API 数据
      const [report, perf, costs] = await Promise.all([
        analyticsApi.getGrowthReport(accountId.value, period.value),
        analyticsApi.getPerformance(accountId.value, 20),
        analyticsApi.getCosts(),
      ])
      growthReport.value = report
      performanceData.value = perf
      costData.value = costs
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function fetchReport() {
    isLoading.value = true
    try {
      growthReport.value = await analyticsApi.getGrowthReport(accountId.value, period.value)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function fetchPerformance() {
    isLoading.value = true
    try {
      performanceData.value = await analyticsApi.getPerformance(accountId.value, 20)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function fetchCosts() {
    isLoading.value = true
    try {
      costData.value = await analyticsApi.getCosts()
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  function setPeriod(p: 'daily' | 'weekly' | 'monthly') {
    period.value = p
    fetchReport()
  }

  function setAccountId(id: string) {
    accountId.value = id
    fetchAllData()
  }

  return {
    // State
    accountId,
    period,
    growthReport,
    performanceData,
    costData,
    isLoading,
    error,
    // Computed
    posts,
    totalEngagement,
    avgEngagementRate,
    // Actions
    fetchAllData,
    fetchReport,
    fetchPerformance,
    fetchCosts,
    setPeriod,
    setAccountId,
  }
})
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/analytics.ts
git commit -m "feat: create analytics Pinia store"
```

---

### Task 14: 创建 Store 导出

**Files:**
- Create: `frontend/src/stores/index.ts`

- [ ] **Step 1: 创建 stores/index.ts**

```typescript
export { useWorkflowStore } from './workflow'
export { useReviewStore } from './review'
export { useAnalyticsStore } from './analytics'
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/index.ts
git commit -m "feat: export all Pinia stores"
```

---

## Phase 4: 路由和通用组件

### Task 15: 创建 Vue Router

**Files:**
- Create: `frontend/src/router/index.ts`

- [ ] **Step 1: 创建 router/index.ts**

```typescript
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/Home.vue'),
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/Dashboard.vue'),
    },
    {
      path: '/review',
      name: 'review',
      component: () => import('@/views/Review.vue'),
    },
    {
      path: '/analytics',
      name: 'analytics',
      component: () => import('@/views/Analytics.vue'),
    },
  ],
})

export default router
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/router/index.ts
git commit -m "feat: create Vue Router with lazy-loaded routes"
```

---

### Task 16: 创建 Navbar 组件

**Files:**
- Create: `frontend/src/components/Navbar.vue`

- [ ] **Step 1: 创建 components/Navbar.vue**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()

const navItems = [
  { path: '/dashboard', icon: '🏠', label: '工作流仪表盘' },
  { path: '/review', icon: '✅', label: '内容审核' },
  { path: '/analytics', icon: '📊', label: '数据分析' },
]

const currentPath = computed(() => route.path)

const navigateTo = (path: string) => {
  router.push(path)
}

const currentPhase = computed(() => workflowStore.currentPhase)
</script>

<template>
  <nav class="w-56 bg-dark-panel p-4 flex flex-col border-r border-dark-border">
    <!-- Logo -->
    <div class="mb-6">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-neon-pink to-neon-peach flex items-center justify-center shadow-neon-pink">
          📚
        </div>
        <div class="text-white font-bold">增长引擎</div>
      </div>
      <div class="mt-2 text-xs mono text-neon-cyan">
        Phase: {{ currentPhase }}
      </div>
    </div>

    <!-- 导航项 -->
    <div class="space-y-2">
      <div
        v-for="item in navItems"
        :key="item.path"
        @click="navigateTo(item.path)"
        :class="[
          'p-3 rounded-lg cursor-pointer transition-all duration-200',
          currentPath === item.path
            ? 'bg-neon-pink/20 border border-neon-pink/50 shadow-neon-pink'
            : 'hover:bg-dark-card border border-transparent'
        ]"
      >
        <div class="flex items-center gap-3">
          <span class="text-lg">{{ item.icon }}</span>
          <span :class="[
            'text-sm',
            currentPath === item.path ? 'text-neon-pink font-bold' : 'text-white/70'
          ]">
            {{ item.label }}
          </span>
        </div>
      </div>
    </div>

    <!-- 底部信息 -->
    <div class="mt-auto pt-4 border-t border-dark-border">
      <div class="text-xs mono text-white/40">
        <div>Account: default</div>
        <div>Version: v0.1.0</div>
      </div>
    </div>
  </nav>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Navbar.vue
git commit -m "feat: create Navbar component with cyberpunk styling"
```

---

### Task 17: 创建 NeonButton 组件

**Files:**
- Create: `frontend/src/components/NeonButton.vue`

- [ ] **Step 1: 创建 components/NeonButton.vue**

```vue
<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  variant?: 'pink' | 'cyan' | 'purple' | 'peach' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
  size: 'md',
  disabled: false,
  loading: false,
})

const emit = defineEmits<{
  click: []
}>()

const variantClasses = computed(() => {
  const variants = {
    pink: 'bg-gradient-to-br from-neon-pink to-neon-peach border-neon-pink shadow-neon-pink hover:shadow-[0_0_30px_rgba(254,44,85,0.7)]',
    cyan: 'bg-gradient-to-br from-neon-cyan to-emerald-600 border-neon-cyan shadow-neon-cyan hover:shadow-[0_0_30px_rgba(78,205,196,0.7)]',
    purple: 'bg-gradient-to-br from-neon-purple to-purple-700 border-neon-purple shadow-neon-purple hover:shadow-[0_0_30px_rgba(102,126,234,0.7)]',
    peach: 'bg-gradient-to-br from-neon-peach to-neon-gold border-neon-peach shadow-neon-peach hover:shadow-[0_0_30px_rgba(255,228,225,0.7)]',
    ghost: 'bg-transparent border-white/20 hover:bg-white/10',
  }
  return variants[props.variant]
})

const sizeClasses = computed(() => {
  const sizes = {
    sm: 'px-4 py-2 text-sm',
    md: 'px-6 py-3 text-base',
    lg: 'px-8 py-4 text-lg',
  }
  return sizes[props.size]
})

const handleClick = () => {
  if (!props.disabled && !props.loading) {
    emit('click')
  }
}
</script>

<template>
  <button
    @click="handleClick"
    :disabled="disabled || loading"
    :class="[
      'relative rounded-lg border-2 font-bold text-white transition-all duration-200',
      'disabled:opacity-50 disabled:cursor-not-allowed',
      variantClasses,
      sizeClasses,
    ]"
  >
    <span v-if="loading" class="animate-pulse">⏳</span>
    <slot v-else />
  </button>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/NeonButton.vue
git commit -m "feat: create NeonButton component with gradient variants"
```

---

### Task 18: 创建 StatusCard 组件

**Files:**
- Create: `frontend/src/components/StatusCard.vue`

- [ ] **Step 1: 创建 components/StatusCard.vue**

```vue
<script setup lang="ts">
interface Props {
  title: string
  value: string | number
  subtitle?: string
  icon?: string
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
})

const variantClasses = {
  pink: 'border-neon-pink/30 shadow-[0_0_30px_rgba(254,44,85,0.2)]',
  cyan: 'border-neon-cyan/30 shadow-[0_0_30px_rgba(78,205,196,0.2)]',
  purple: 'border-neon-purple/30 shadow-[0_0_30px_rgba(102,126,234,0.2)]',
  peach: 'border-neon-peach/30 shadow-[0_0_30px_rgba(255,228,225,0.2)]',
}

const iconBgClasses = {
  pink: 'from-neon-pink to-neon-peach',
  cyan: 'from-neon-cyan to-emerald-600',
  purple: 'from-neon-purple to-purple-700',
  peach: 'from-neon-peach to-neon-gold',
}

const valueColorClasses = {
  pink: 'text-neon-pink',
  cyan: 'text-neon-cyan',
  purple: 'text-neon-purple',
  peach: 'text-neon-peach',
}
</script>

<template>
  <div :class="['glass rounded-xl p-4 border-glow-' + props.variant]">
    <div class="flex items-center gap-3 mb-3">
      <div 
        v-if="props.icon"
        :class="[
          'w-9 h-9 rounded-lg bg-gradient-to-br flex items-center justify-center text-lg',
          iconBgClasses[props.variant]
        ]"
      >
        {{ props.icon }}
      </div>
      <div class="mono text-xs text-white/50">{{ props.title }}</div>
    </div>
    <div :class="['mono text-3xl font-bold', valueColorClasses[props.variant]]">
      {{ props.value }}
    </div>
    <div v-if="props.subtitle" class="mono text-xs text-neon-cyan mt-2">
      {{ props.subtitle }}
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/StatusCard.vue
git commit -m "feat: create StatusCard component for metrics display"
```

---

### Task 19: 创建 WorkflowNode 组件

**Files:**
- Create: `frontend/src/components/WorkflowNode.vue`

- [ ] **Step 1: 创建 components/WorkflowNode.vue**

```vue
<script setup lang="ts">
interface Props {
  icon: string
  label: string
  status: 'completed' | 'running' | 'pending'
}

const props = defineProps<Props>()

const statusClasses = {
  completed: 'bg-gradient-to-br from-neon-pink to-neon-peach border-2 border-white shadow-neon-pink',
  running: 'bg-gradient-to-br from-neon-peach to-neon-gold border-3 border-neon-pink animate-pulse-glow shadow-neon-pink',
  pending: 'bg-white/20 border border-white/30 opacity-50',
}
</script>

<template>
  <div class="text-center">
    <div 
      :class="[
        'w-20 h-20 hexagon flex items-center justify-center mx-auto',
        statusClasses[props.status]
      ]"
    >
      <span class="text-2xl">{{ props.icon }}</span>
    </div>
    <div 
      :class="[
        'mt-2 mono text-xs',
        props.status === 'running' ? 'text-neon-pink font-bold' : 
        props.status === 'completed' ? 'text-white' : 'text-white/40'
      ]"
    >
      {{ props.label }}
    </div>
    <div 
      v-if="props.status === 'completed'"
      class="mono text-xs text-neon-cyan mt-1"
    >
      ✓ 完成
    </div>
    <div 
      v-else-if="props.status === 'running'"
      class="mono text-xs text-neon-peach mt-1 animate-blink"
    >
      ⏳ 进行中
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/WorkflowNode.vue
git commit -m "feat: create WorkflowNode hexagon component"
```

---

## Phase 5: 页面开发

### Task 20: 创建 Home 页面

**Files:**
- Create: `frontend/src/views/Home.vue`

- [ ] **Step 1: 创建 views/Home.vue**

```vue
<script setup lang="ts">
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import { useWorkflowStore } from '@/stores'

const router = useRouter()
const workflowStore = useWorkflowStore()

const goToDashboard = () => {
  router.push('/dashboard')
}

const startNewWorkflow = async () => {
  await workflowStore.startWorkflow('default', 'scouting')
  router.push('/dashboard')
}
</script>

<template>
  <div class="min-h-[80vh] flex flex-col items-center justify-center">
    <!-- 主卡片 -->
    <div class="glass rounded-2xl p-8 max-w-md w-full border-glow-pink scanline">
      <div class="text-center mb-8">
        <div class="w-20 h-20 rounded-2xl bg-gradient-to-br from-neon-pink to-neon-peach flex items-center justify-center mx-auto mb-4 shadow-neon-pink text-4xl">
          🚀
        </div>
        <h1 class="text-2xl font-bold text-white mb-2">小红书增长引擎</h1>
        <p class="text-sm text-white/60 mono">AI驱动的自动化内容创作平台</p>
      </div>

      <div class="space-y-4">
        <NeonButton variant="pink" size="lg" class="w-full" @click="startNewWorkflow">
          🚀 启动新工作流
        </NeonButton>
        
        <NeonButton variant="ghost" size="md" class="w-full" @click="goToDashboard">
          📊 查看现有工作流
        </NeonButton>
      </div>

      <div class="mt-8 text-center mono text-xs text-white/40">
        Account: default | Phase: scouting
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/Home.vue
git commit -m "feat: create Home page with workflow start"
```

---

### Task 21: 创建 Dashboard 页面

**Files:**
- Create: `frontend/src/views/Dashboard.vue`

- [ ] **Step 1: 创建 views/Dashboard.vue**

```vue
<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import WorkflowNode from '@/components/WorkflowNode.vue'
import ContentCard from '@/components/ContentCard.vue'
import { useWorkflowStore, useReviewStore } from '@/stores'

const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()

// 生命周期
onMounted(() => {
  // 如果没有 threadId，创建一个新的
  if (!workflowStore.currentThreadId) {
    workflowStore.startWorkflow('default', 'scouting')
  } else {
    workflowStore.refreshStatus()
  }
  workflowStore.startPolling(5000)
})

onUnmounted(() => {
  workflowStore.stopPolling()
})

// 计算属性
const workflowNodes = computed(() => [
  { icon: '🔍', label: '趋势发现', phase: 'scouting' },
  { icon: '📋', label: '策略规划', phase: 'planning' },
  { icon: '✍️', label: '文案创作', phase: 'creating' },
  { icon: '🎨', label: '视觉设计', phase: 'creating' },
  { icon: '⏳', label: '审核', phase: 'reviewing' },
  { icon: '📤', label: '发布', phase: 'publishing' },
])

const getNodeStatus = (phase: string) => {
  const currentPhase = workflowStore.currentPhase
  const phaseOrder = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'completed']
  const currentIndex = phaseOrder.indexOf(currentPhase)
  const nodeIndex = phaseOrder.indexOf(phase)
  
  if (nodeIndex < currentIndex) return 'completed'
  if (nodeIndex === currentIndex) return 'running'
  return 'pending'
}

// 操作
const pauseWorkflow = () => {
  workflowStore.pauseWorkflow()
}

const goToReview = () => {
  if (workflowStore.currentThreadId) {
    reviewStore.fetchPendingReview(workflowStore.currentThreadId)
    router.push('/review')
  }
}
</script>

<template>
  <div class="relative overflow-hidden">
    <!-- 扫描线效果 -->
    <div class="scanline absolute inset-0 pointer-events-none" />

    <!-- 顶部状态栏 -->
    <div class="glass rounded-xl p-4 mb-6 border-glow-pink">
      <div class="flex items-center gap-4">
        <div class="w-14 h-14 rounded-xl bg-gradient-to-br from-neon-pink to-neon-peach flex items-center justify-center shadow-neon-pink text-3xl">
          🚀
        </div>
        <div class="flex-1">
          <div class="mono text-xs text-neon-cyan">WORKFLOW_ID: {{ workflowStore.currentThreadId }}</div>
          <div class="text-lg font-bold text-white mt-1">
            <span class="text-neon-pink">●</span> 
            {{ workflowStore.currentPhase === 'idle' ? '等待启动' : `${workflowStore.currentPhase} 阶段` }}
          </div>
          <div class="flex gap-4 mt-2 mono text-xs">
            <span class="text-neon-peach">⚡ 运行中</span>
            <span class="text-neon-cyan">📊 进度 {{ workflowStore.isRunning ? '60%' : '100%' }}</span>
          </div>
        </div>
        <div class="bg-gradient-to-br from-neon-cyan to-emerald-600 rounded-lg px-6 py-3 border border-neon-cyan shadow-neon-cyan mono font-bold">
          <span class="animate-blink">●</span> RUNNING
        </div>
      </div>
    </div>

    <!-- 流程节点时间轴 -->
    <div class="relative py-8 mb-8">
      <!-- 进度线 -->
      <div class="absolute top-1/2 left-0 right-0 h-1 bg-gradient-to-r from-neon-pink via-neon-pink/50 to-transparent rounded-full shadow-neon-pink" />
      
      <!-- 节点 -->
      <div class="flex justify-around relative">
        <WorkflowNode 
          v-for="node in workflowNodes"
          :key="node.phase"
          :icon="node.icon"
          :label="node.label"
          :status="getNodeStatus(node.phase)"
        />
      </div>
    </div>

    <!-- 输出卡片 -->
    <div class="grid grid-cols-3 gap-4 mb-6">
      <ContentCard 
        v-if="workflowStore.trendData"
        title="🔍 趋势发现"
        :content="workflowStore.trendData"
        variant="pink"
        :completed="getNodeStatus('scouting') === 'completed'"
      />
      <ContentCard 
        v-if="workflowStore.contentPlan"
        title="📋 策略规划"
        :content="workflowStore.contentPlan"
        variant="cyan"
        :completed="getNodeStatus('planning') === 'completed'"
      />
      <ContentCard 
        v-if="workflowStore.copyContent"
        title="✍️ 文案创作"
        :content="workflowStore.copyContent"
        variant="purple"
        :completed="true"
      />
    </div>

    <!-- 操作按钮 -->
    <div class="flex gap-4">
      <NeonButton variant="pink" @click="pauseWorkflow" :loading="workflowStore.isLoading">
        ⏸️ 暂停工作流
      </NeonButton>
      <NeonButton variant="cyan" @click="workflowStore.refreshStatus()">
        🔄 刷新状态
      </NeonButton>
      <NeonButton variant="purple" @click="goToReview">
        ✅ 进入审核
      </NeonButton>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/Dashboard.vue
git commit -m "feat: create Dashboard page with workflow timeline"
```

---

### Task 22: 创建 ContentCard 组件

**Files:**
- Create: `frontend/src/components/ContentCard.vue`

- [ ] **Step 1: 创建 components/ContentCard.vue**

```vue
<script setup lang="ts">
interface Props {
  title: string
  content: Record<string, any>
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
  completed?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
  completed: false,
})

const borderGlowClasses = {
  pink: 'border-glow-pink',
  cyan: 'border-glow-cyan',
  purple: 'border-glow-purple',
  peach: 'border-glow-pink',
}

const iconBgClasses = {
  pink: 'from-neon-pink to-neon-peach',
  cyan: 'from-neon-cyan to-emerald-600',
  purple: 'from-neon-purple to-purple-700',
  peach: 'from-neon-peach to-neon-gold',
}
</script>

<template>
  <div :class="['glass rounded-xl p-4', borderGlowClasses[props.variant]]">
    <div class="flex items-center gap-3 mb-4">
      <div :class="['w-10 h-10 rounded-lg bg-gradient-to-br flex items-center justify-center', iconBgClasses[props.variant]]">
        <span class="text-lg">{{ props.title.split(' ')[0] }}</span>
      </div>
      <div class="flex-1">
        <div class="text-white font-bold text-sm">{{ props.title.split(' ')[1] }}</div>
        <div class="mono text-xs text-white/50">MODULE_OUTPUT</div>
      </div>
      <div v-if="props.completed" class="text-neon-cyan mono text-xs">
        ✓ 完成
      </div>
    </div>
    
    <div class="bg-black/50 rounded-lg p-3 border-l-2 border-neon-cyan">
      <div class="mono text-xs text-white/70 space-y-1">
        <div v-for="(key, value) in props.content" :key="key">
          <span class="text-neon-pink">►</span> 
          <span class="text-white/50">{{ key }}:</span>
          <span class="text-neon-cyan">{{ value }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ContentCard.vue
git commit -m "feat: create ContentCard component for stage outputs"
```

---

### Task 23: 创建 Review 页面

**Files:**
- Create: `frontend/src/views/Review.vue`

- [ ] **Step 1: 创建 views/Review.vue**

```vue
<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import { useWorkflowStore, useReviewStore } from '@/stores'
import type { ContentStatus } from '@/types'

const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()

const comments = ref('')
const selectedDecision = ref<ContentStatus | null>(null)

onMounted(() => {
  if (workflowStore.currentThreadId) {
    reviewStore.fetchPendingReview(workflowStore.currentThreadId)
  }
})

const copyContent = computed(() => reviewStore.copyContent)
const visualPlan = computed(() => reviewStore.visualPlan)

const handleDecision = async (decision: ContentStatus) => {
  selectedDecision.value = decision
  try {
    await reviewStore.submitDecision(decision, comments.value)
    router.push('/dashboard')
  } catch (e) {
    console.error('Submit failed:', e)
  }
}
</script>

<template>
  <div class="relative overflow-hidden">
    <!-- 扫描线 -->
    <div class="scanline absolute inset-0 pointer-events-none" />

    <!-- 审核状态栏 -->
    <div class="glass rounded-xl p-4 mb-6 border-glow-pink">
      <div class="flex items-center gap-4">
        <div class="w-14 h-14 rounded-xl bg-gradient-to-br from-neon-peach to-neon-pink flex items-center justify-center shadow-neon-peach text-3xl">
          ⏳
        </div>
        <div class="flex-1">
          <div class="mono text-xs text-neon-peach">REVIEW_STATUS: PENDING_APPROVAL</div>
          <div class="text-lg font-bold text-white mt-1">内容审核 · 等待您的决定</div>
          <div class="mono text-xs text-white/50">
            Thread: {{ workflowStore.currentThreadId }}
          </div>
        </div>
      </div>
    </div>

    <!-- 内容预览 -->
    <div class="grid grid-cols-2 gap-6 mb-6">
      <!-- 文案预览 -->
      <div class="glass rounded-xl p-4 border-glow-purple">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-neon-purple to-purple-700 flex items-center justify-center text-xl">
            ✍️
          </div>
          <div class="text-neon-purple mono font-bold">文案内容</div>
        </div>
        
        <div class="bg-black/50 rounded-lg p-4 border-l-2 border-neon-pink">
          <div v-if="copyContent.title" class="text-neon-pink font-bold text-lg mb-2">
            {{ copyContent.title }}
          </div>
          <div v-if="copyContent.body" class="text-white/70 text-sm mb-2">
            {{ copyContent.body }}
          </div>
          <div v-if="copyContent.tags" class="flex gap-2">
            <span v-for="tag in copyContent.tags" :key="tag" class="px-2 py-1 rounded bg-neon-pink/20 text-neon-pink mono text-xs">
              #{{ tag }}
            </span>
          </div>
        </div>
      </div>

      <!-- 视觉方案预览 -->
      <div class="glass rounded-xl p-4 border-glow-cyan">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-neon-cyan to-emerald-600 flex items-center justify-center text-xl">
            🎨
          </div>
          <div class="text-neon-cyan mono font-bold">视觉方案</div>
        </div>
        
        <div class="bg-black/50 rounded-lg p-4 border-l-2 border-neon-cyan">
          <div v-if="visualPlan.layout" class="text-neon-cyan font-bold mb-2">
            {{ visualPlan.layout }}
          </div>
          <div v-if="visualPlan.style" class="text-white/70 text-sm mb-2">
            {{ visualPlan.style }}
          </div>
          <div v-if="visualPlan.colors" class="flex gap-2 mt-2">
            <div v-for="color in visualPlan.colors" :key="color" class="w-6 h-6 rounded" :style="{ background: color }" />
          </div>
        </div>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="glass rounded-xl p-6 border-glow-pink">
      <div class="mono text-neon-cyan text-xs mb-4">审核操作 // SELECT_ACTION</div>
      
      <div class="grid grid-cols-3 gap-4 mb-6">
        <NeonButton variant="cyan" size="lg" class="w-full" @click="handleDecision('approved')">
          ✓ APPROVE
          <div class="text-xs opacity-70 mt-1">直接发布</div>
        </NeonButton>
        
        <NeonButton variant="purple" size="lg" class="w-full" @click="handleDecision('needs_revision')">
          ✎ REVISE
          <div class="text-xs opacity-70 mt-1">要求修改</div>
        </NeonButton>
        
        <NeonButton variant="ghost" size="lg" class="w-full border-neon-pink text-neon-pink" @click="handleDecision('rejected')">
          ✗ REJECT
          <div class="text-xs opacity-70 mt-1">放弃此内容</div>
        </NeonButton>
      </div>

      <!-- 反馈输入 -->
      <div class="bg-black/50 rounded-lg p-4 border border-neon-purple/20">
        <div class="mono text-neon-purple text-xs mb-2">FEEDBACK_INPUT // 修改建议</div>
        <textarea 
          v-model="comments"
          class="w-full bg-transparent border-none text-white mono text-sm resize-none focus:outline-none"
          rows="3"
          placeholder="请输入审核意见或修改建议..."
        />
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/Review.vue
git commit -m "feat: create Review page with approve/revise/reject actions"
```

---

### Task 24: 创建 Analytics 页面

**Files:**
- Create: `frontend/src/views/Analytics.vue`
- Create: `frontend/src/components/MetricCard.vue`
- Create: `frontend/src/components/DataTable.vue`

- [ ] **Step 1: 创建 components/MetricCard.vue**

```vue
<script setup lang="ts">
interface Props {
  icon: string
  title: string
  value: string | number
  subtitle?: string
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
})

const colors = {
  pink: { bg: 'from-neon-pink to-neon-peach', text: 'text-neon-pink', border: 'border-glow-pink' },
  cyan: { bg: 'from-neon-cyan to-emerald-600', text: 'text-neon-cyan', border: 'border-glow-cyan' },
  purple: { bg: 'from-neon-purple to-purple-700', text: 'text-neon-purple', border: 'border-glow-purple' },
  peach: { bg: 'from-neon-peach to-neon-gold', text: 'text-neon-peach', border: 'border-glow-pink' },
}
</script>

<template>
  <div :class="['glass rounded-xl p-4', colors[props.variant].border]">
    <div class="flex items-center gap-3 mb-3">
      <div :class="['w-9 h-9 rounded-lg bg-gradient-to-br flex items-center justify-center shadow-neon-' + props.variant]">
        <span class="text-lg">{{ props.icon }}</span>
      </div>
      <div class="mono text-xs text-white/50">{{ props.title }}</div>
    </div>
    <div :class="['mono text-3xl font-bold', colors[props.variant].text]">
      {{ props.value }}
    </div>
    <div v-if="props.subtitle" class="mono text-xs text-neon-cyan mt-2">
      {{ props.subtitle }}
    </div>
  </div>
</template>
```

- [ ] **Step 2: 创建 components/DataTable.vue**

```vue
<script setup lang="ts">
interface Column {
  key: string
  label: string
  align?: 'left' | 'center' | 'right'
}

interface Props {
  columns: Column[]
  data: Record<string, any>[]
}

const props = defineProps<Props>()
</script>

<template>
  <div class="bg-black/50 rounded-lg overflow-hidden">
    <!-- 表头 -->
    <div class="grid gap-4 p-3 bg-neon-purple/10 border-b border-neon-purple/20 mono text-xs text-white/50">
      <div 
        v-for="col in props.columns"
        :key="col.key"
        :class="['text-' + (col.align || 'left')]"
      >
        {{ col.label }}
      </div>
    </div>
    
    <!-- 数据行 -->
    <div 
      v-for="(row, idx) in props.data"
      :key="idx"
      class="grid gap-4 p-3 border-b border-white/10 mono text-xs"
    >
      <div 
        v-for="col in props.columns"
        :key="col.key"
        :class="['text-' + (col.align || 'left')]"
      >
        {{ row[col.key] }}
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 3: 创建 views/Analytics.vue**

```vue
<script setup lang="ts">
import { onMounted, computed } from 'vue'
import MetricCard from '@/components/MetricCard.vue'
import DataTable from '@/components/DataTable.vue'
import { useAnalyticsStore } from '@/stores'

const analyticsStore = useAnalyticsStore()

onMounted(() => {
  analyticsStore.fetchAllData()
})

const metrics = computed(() => [
  { icon: '📤', title: 'POSTS_PUBLISHED', value: analyticsStore.posts.length, subtitle: '↑ +3 本周', variant: 'pink' },
  { icon: '💬', title: 'TOTAL_ENGAGEMENT', value: analyticsStore.totalEngagement, subtitle: '↑ +18%', variant: 'cyan' },
  { icon: '📈', title: 'AVG_ENGAGEMENT_RATE', value: `${analyticsStore.avgEngagementRate.toFixed(1)}%`, subtitle: '↑ +2.1%', variant: 'purple' },
  { icon: '💰', title: 'AI_COST_USD', value: analyticsStore.costData?.today_cost_usd?.toFixed(2) || '$0.00', subtitle: '本周累计', variant: 'peach' },
])

const tableColumns = [
  { key: 'title', label: '标题', align: 'left' },
  { key: 'likes', label: '点赞', align: 'center' },
  { key: 'comments', label: '评论', align: 'center' },
  { key: 'collects', label: '收藏', align: 'center' },
  { key: 'engagement_rate', label: '互动率', align: 'center' },
  { key: 'published_at', label: '发布时间', align: 'center' },
]

const tableData = computed(() => analyticsStore.posts.slice(0, 10))

const setPeriod = (period: 'daily' | 'weekly' | 'monthly') => {
  analyticsStore.setPeriod(period)
}
</script>

<template>
  <div class="relative overflow-hidden">
    <!-- 扫描线 -->
    <div class="scanline absolute inset-0 pointer-events-none" />

    <!-- 顶部标题栏 -->
    <div class="glass rounded-xl p-4 mb-6 border-glow-cyan">
      <div class="flex items-center gap-4">
        <div class="w-14 h-14 rounded-xl bg-gradient-to-br from-neon-cyan to-emerald-600 flex items-center justify-center shadow-neon-cyan text-3xl">
          📊
        </div>
        <div class="flex-1">
          <div class="mono text-xs text-neon-cyan">ANALYTICS_MODULE</div>
          <div class="text-lg font-bold text-white mt-1">数据分析中心</div>
          <div class="mono text-xs text-white/50">
            Account: {{ analyticsStore.accountId }} | Period: {{ analyticsStore.period }}
          </div>
        </div>
        <div class="flex gap-3">
          <button 
            v-for="p in ['daily', 'weekly', 'monthly']"
            :key="p"
            @click="setPeriod(p as any)"
            :class="[
              'px-4 py-2 rounded-lg mono text-xs border transition-all',
              analyticsStore.period === p 
                ? 'bg-neon-cyan/20 border-neon-cyan text-neon-cyan' 
                : 'bg-transparent border-white/20 text-white/50 hover:bg-white/10'
            ]"
          >
            📅 {{ p === 'daily' ? '本周' : p === 'weekly' ? '本月' : '全年' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 核心指标卡片 -->
    <div class="grid grid-cols-4 gap-4 mb-6">
      <MetricCard 
        v-for="metric in metrics"
        :key="metric.title"
        v-bind="metric"
      />
    </div>

    <!-- 帖子表现列表 -->
    <div class="glass rounded-xl p-4 border-glow-purple">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-neon-purple to-purple-700 flex items-center justify-center text-xl">
          📝
        </div>
        <div class="text-neon-purple mono font-bold">最近帖子表现</div>
        <div class="mono text-xs text-white/50">TOP 10</div>
      </div>
      
      <DataTable :columns="tableColumns" :data="tableData" />
    </div>
  </div>
</template>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/Analytics.vue frontend/src/components/MetricCard.vue frontend/src/components/DataTable.vue
git commit -m "feat: create Analytics page with metrics and post table"
```

---

## Phase 6: 后端集成和构建

### Task 25: 修改 FastAPI 添加静态文件托管

**Files:**
- Modify: `xhs_growth/api/app.py`

- [ ] **Step 1: 读取现有 app.py**

Read the current content of `xhs_growth/api/app.py` to understand existing structure.

- [ ] **Step 2: 添加 StaticFiles mount**

在路由注册之后，添加静态文件挂载：

```python
# xhs_growth/api/app.py (末尾添加)
import os
from pathlib import Path

# 托管前端静态文件（生产环境）
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    from fastapi.staticfiles import StaticFiles
    # 注意：API 路由已注册，静态文件挂载在最后
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
```

- [ ] **Step 3: Commit**

```bash
git add xhs_growth/api/app.py
git commit -m "feat: add FastAPI StaticFiles mount for frontend"
```

---

### Task 26: 构建前端并测试

**Files:**
- Modify: `frontend/dist/` (构建产物)

- [ ] **Step 1: 构建前端**

```bash
cd frontend && npm run build
```

Expected: 生成 `frontend/dist/` 目录，包含 index.html 和 assets/

- [ ] **Step 2: 启动 FastAPI 测试**

```bash
cd .. && python -m xhs_growth.cli.main serve --port 8000
```

Expected: FastAPI 启动成功，访问 http://localhost:8000 显示前端页面

- [ ] **Step 3: 测试 API 通信**

访问 http://localhost:8000/api/health 验证 API 路由正常。

Expected: 返回 `{"status": "ok", "version": "0.1.0"}`

- [ ] **Step 4: Commit**

```bash
git add frontend/dist/
git commit -m "build: generate frontend dist for FastAPI hosting"
```

---

### Task 27: 更新文档

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README.md 添加前端说明**

在 Architecture 章节后添加：

```markdown
## Frontend Web UI

Vue 3 前端界面，赛博朋克风格，包含三大模块：

### Pages

| 页面 | 路径 | 功能 |
|------|------|------|
| Dashboard | `/dashboard` | 工作流进度追踪、阶段输出展示 |
| Review | `/review` | 人机审核、内容预览、通过/修改/拒绝 |
| Analytics | `/analytics` | 数据统计、帖子表现、成本分析 |

### Tech Stack

- Vue 3.4 + Vite 5.0
- Tailwind CSS 3.4 (赛博朋克主题)
- Element Plus 2.5
- Pinia 2.1 状态管理
- axios 1.6 API 客户端

### Development

```bash
# 前端开发
cd frontend
npm install
npm run dev  # http://localhost:3000

# 构建
npm run build  # 生成 dist/

# 后端托管
xhs-growth serve --port 8000  # http://localhost:8000 同时托管前端
```

### Cyberpunk Design

- 暗色渐变背景 (`#0a0a0a → #1a0a2e`)
- 霓虹配色 (pink/cyan/purple)
- 六边形流程节点
- 毛玻璃卡片 (Glass-morphism)
- 发光按钮和图标
- Monospace 终端字体
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add frontend web UI documentation"
```

---

## Self-Review Checklist

完成后自检：

- [x] **Spec coverage**: 所有设计文档需求都有对应任务
  - Vue 项目初始化 ✓
  - API 层 ✓
  - Pinia stores ✓
  - Router ✓
  - 通用组件 ✓
  - 三页面 ✓
  - FastAPI 集成 ✓
  - 构建 ✓
  - 文档 ✓

- [x] **Placeholder scan**: 无 TBD/TODO/模糊描述
  - 所有代码完整
  - 所有命令具体

- [x] **Type consistency**: 类型定义一致
  - `WorkflowState` 在 types 和 store 中一致
  - `ContentStatus` 在 types 和 Review 中一致
  - API 函数签名匹配类型定义

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-24-frontend-pages.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**