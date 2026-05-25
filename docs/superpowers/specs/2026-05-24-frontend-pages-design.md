---
title: Frontend Pages Design
date: 2026-05-24
status: approved
type: feature-design
---

# Frontend Pages Design - XhsGrowthAgent Web UI

## Overview

为 XhsGrowthAgent 添加前端 Web UI，面向个人博主用户，提供工作流仪表盘、内容审核、数据分析三大模块。采用 Vue 3 + Element Plus + Tailwind CSS 技术栈，赛博朋克/小红书风格设计，同端口部署（FastAPI 托管静态文件）。

## Requirements Summary

### User Requirements

- **目标用户**: 个人博主，单账号使用
- **核心功能**:
  - 工作流仪表盘 - 实时追踪创作流程进度
  - 内容审核页面 - 人机交互审核生成的文案/视觉方案
  - 数据分析页面 - 查看帖子表现、增长报告、成本统计
- **技术偏好**: Vue 3 + Element Plus + Tailwind CSS
- **部署方式**: 同端口部署，FastAPI 托管静态文件
- **设计风格**: 赛博朋克风格 + 小红书风格融合（暗色渐变背景、霓虹配色、发光效果）

### Current State

- 后端 FastAPI 已有 `/api/workflow`, `/api/review`, `/api/analytics` 三个路由
- 无现有前端代码
- CLI 工具仅支持命令行操作

## Architecture Design

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Vue 3 SPA)                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌───────────────┐│
│  │  Dashboard      │  │  Review Page    │  │ Analytics     ││
│  │  (仪表盘)       │  │  (审核页)       │  │ (分析页)      ││
│  └─────────────────┘  └─────────────────┘  └───────────────┘│
│                              ↓                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                  API Client Layer                        ││
│  │  - axios/fetch 封装                                      ││
│  │  - Pinia 状态管理                                        ││
│  │  - 路由守卫                                              ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              ↓ HTTP/REST
┌─────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI)                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌───────────────┐│
│  │  /api/workflow  │  │  /api/review    │  │/api/analytics ││
│  │  (工作流控制)   │  │  (审核交互)     │  │(数据统计)     ││
│  └─────────────────┘  └─────────────────┘  └───────────────┘│
│                              ↓                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              LangGraph Workflow Engine                   ││
│  │  - StateGraph nodes                                      ││
│  │  - Memory checkpointer                                   ││
│  │  - Tool registry                                         ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    Static Files                              │
│  frontend/dist/ → FastAPI StaticFiles mount                 │
│  - index.html                                               │
│  - assets/*.js, *.css                                       │
└─────────────────────────────────────────────────────────────┘
```

### Design Principles

- **前后端分离**: Vue 项目独立开发，构建产物由 FastAPI 托管
- **单账号简化**: 不需要账号切换，简化用户认证流程
- **赛博朋克美学**: 暗色渐变背景、霓虹配色、发光效果、HUD 信息栏
- **实时状态更新**: WebSocket 或轮询实现工作流状态实时刷新
- **响应式设计**: 适配桌面和移动端

## Core Components

### 1. Vue Project Structure

**Location**: `frontend/`

```
frontend/
├── src/
│   ├── views/              # 页面组件
│   │   ├── Dashboard.vue   # 工作流仪表盘
│   │   ├── Review.vue      # 内容审核页面
│   │   └── Analytics.vue   # 数据分析页面
│   │   └── Home.vue        # 首页/路由入口
│   │
│   ├── components/         # 通用组件
│   │   ├── Navbar.vue      # 左侧导航栏
│   │   ├── StatusCard.vue  # 状态卡片
│   │   ├── WorkflowTimeline.vue  # 流程时间轴
│   │   ├── ContentPreview.vue    # 内容预览卡片
│   │   ├── ChartBar.vue    # 柱状图组件
│   │   ├── ChartPie.vue    # 饼图组件
│   │   └── NeonButton.vue  # 霓虹风格按钮
│   │
│   ├── api/                # API 调用层
│   │   ├── workflow.ts     # 工作流 API
│   │   ├── review.ts       # 审核 API
│   │   ├── analytics.ts    # 分析 API
│   │   └── client.ts       # axios 实例
│   │
│   ├── stores/             # Pinia 状态管理
│   │   ├── workflow.ts     # 工作流状态
│   │   ├── review.ts       # 审核状态
│   │   └── analytics.ts    # 分析数据
│   │
│   ├── styles/             # 样式文件
│   │   ├── cyberpunk.css   # 赛博朋克主题
│   │   ├── neon.css        # 发光效果
│   │   └── variables.css   # CSS 变量
│   │
│   ├── router/             # 路由配置
│   │   └── index.ts        # Vue Router
│   │
│   ├── App.vue             # 根组件
│   └── main.ts             # 入口文件
│
├── public/
│   └── favicon.ico
│
├── index.html
├── vite.config.ts          # Vite 配置
├── tailwind.config.js      # Tailwind 配置
├── package.json
└── tsconfig.json
```

### 2. API Client Layer

**Location**: `frontend/src/api/client.ts`

```typescript
import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
client.interceptors.request.use((config) => {
  // 可添加认证 token
  return config
})

// 响应拦截器
client.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('API Error:', error)
    throw error
  }
)

export default client
```

### 3. Workflow API

**Location**: `frontend/src/api/workflow.ts`

```typescript
import client from './client'

export interface WorkflowStartRequest {
  account_id: string
  phase: string
}

export interface WorkflowResponse {
  thread_id: string
  status: string
  phase: string
}

export interface WorkflowState {
  thread_id: string
  next: string[]
  values: Record<string, any>
}

// 启动工作流
export async function startWorkflow(req: WorkflowStartRequest): Promise<WorkflowResponse> {
  return client.post('/workflow/start', req)
}

// 获取工作流状态
export async function getWorkflowStatus(threadId: string): Promise<WorkflowState> {
  return client.get(`/workflow/status/${threadId}`)
}

// 暂停工作流
export async function pauseWorkflow(threadId: string): Promise<{ status: string }> {
  return client.post(`/workflow/pause/${threadId}`)
}

// 恢复工作流
export async function resumeWorkflow(threadId: string): Promise<WorkflowResponse> {
  return client.post(`/workflow/resume/${threadId}`)
}
```

### 4. Review API

**Location**: `frontend/src/api/review.ts`

```typescript
import client from './client'

export interface PendingReview {
  status: string
  content_plan: Record<string, any>
  copy_content: Record<string, any>
  visual_plan: Record<string, any>
}

export interface ReviewDecision {
  decision: 'approved' | 'needs_revision' | 'rejected'
  comments?: string
  revisions?: string[]
}

// 获取待审核内容
export async function getPendingReview(threadId: string): Promise<PendingReview> {
  return client.get(`/review/pending/${threadId}`)
}

// 提交审核决定
export async function submitReview(threadId: string, decision: ReviewDecision): Promise<{
  status: string
  next_phase: string
}> {
  return client.post(`/review/submit/${threadId}`, decision)
}
```

### 5. Analytics API

**Location**: `frontend/src/api/analytics.ts`

```typescript
import client from './client'

export interface GrowthReport {
  account_id: string
  period: string
  report: string
}

export interface PerformanceData {
  account_id: string
  posts: Array<{
    title: string
    likes: number
    comments: number
    collects: number
    engagement_rate: number
    published_at: string
  }>
}

export interface CostData {
  total_cost_usd: number
  today_cost_usd: number
  circuit_open: boolean
}

// 获取增长报告
export async function getGrowthReport(accountId: string, period: string = 'weekly'): Promise<GrowthReport> {
  return client.get(`/analytics/report/${accountId}`, { params: { period } })
}

// 获取帖子表现
export async function getPerformance(accountId: string, limit: number = 20): Promise<PerformanceData> {
  return client.get(`/analytics/performance/${accountId}`, { params: { limit } })
}

// 获取成本统计
export async function getCosts(): Promise<CostData> {
  return client.get('/analytics/costs')
}
```

### 6. Pinia Store (Workflow)

**Location**: `frontend/src/stores/workflow.ts`

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as workflowApi from '@/api/workflow'

export const useWorkflowStore = defineStore('workflow', () => {
  const currentThreadId = ref<string | null>(null)
  const workflowState = ref<workflowApi.WorkflowState | null>(null)
  const isLoading = ref(false)

  // 当前阶段
  const currentPhase = computed(() => workflowState.value?.values?.phase || 'idle')

  // 下一步节点
  const nextNodes = computed(() => workflowState.value?.next || [])

  // 启动工作流
  async function startWorkflow(accountId: string, phase: string = 'scouting') {
    isLoading.value = true
    try {
      const result = await workflowApi.startWorkflow({ account_id: accountId, phase })
      currentThreadId.value = result.thread_id
      return result
    } finally {
      isLoading.value = false
    }
  }

  // 刷新状态
  async function refreshStatus() {
    if (!currentThreadId.value) return
    isLoading.value = true
    try {
      workflowState.value = await workflowApi.getWorkflowStatus(currentThreadId.value)
    } finally {
      isLoading.value = false
    }
  }

  // 定时刷新（轮询）
  let pollInterval: number | null = null
  function startPolling(intervalMs: number = 5000) {
    pollInterval = window.setInterval(refreshStatus, intervalMs)
  }
  function stopPolling() {
    if (pollInterval) clearInterval(pollInterval)
    pollInterval = null
  }

  return {
    currentThreadId,
    workflowState,
    isLoading,
    currentPhase,
    nextNodes,
    startWorkflow,
    refreshStatus,
    pauseWorkflow,
    resumeWorkflow,
    startPolling,
    stopPolling,
  }
})
```

## Page Designs

### 1. Dashboard (工作流仪表盘)

**Location**: `frontend/src/views/Dashboard.vue`

**功能要点**:
- 流程进度可视化（六边形节点时间轴）
- 各阶段输出卡片（趋势发现、策略规划、文案创作、视觉设计）
- 实时状态更新（轮询 5秒）
- 操作按钮（暂停/恢复/查看日志）

**赛博朋克设计元素**:
- 暗色渐变背景 (`#0a0a0a → #1a0a2e → #0f1a2a`)
- HUD 信息栏（实时数据、状态徽章）
- 六边形节点 + 发光效果
- 毛玻璃卡片（Glass-morphism）
- 扫描线动画（横向移动）

### 2. Review (内容审核页面)

**Location**: `frontend/src/views/Review.vue`

**功能要点**:
- 内容预览（左侧文案、右侧视觉方案）
- 评分指标（吸引力指数、互动预估、风格热度）
- 三态操作（APPROVE/REVISE/REJECT）
- 反馈输入（修改建议文本框）
- 自动超时（300秒无操作自动通过）

**赛博朋克设计元素**:
- 审核状态栏（等待决定）
- 内容预览卡片（边框光带）
- 霓虹按钮（渐变背景 + 发光阴影）
- 评分指标网格（彩色数据）

### 3. Analytics (数据分析页面)

**Location**: `frontend/src/views/Analytics.vue`

**功能要点**:
- 核心指标卡片（发布量、互动量、互动率、成本）
- 增长趋势图（7日柱状图）
- 内容类型分布（玫瑰图）
- 帖子表现列表（TOP 10 表格）
- 时间筛选（本周/本月/全年）

**赛博朋克设计元素**:
- 指标卡片（霓虹边框 + 发光图标）
- 柱状图（渐变填充 + 发光）
- 饼图（霓虹配色 + 中心镂空）
- 数据表格（Monospace 字体 + 彩色列）

## Data Flow

### Workflow Status Update Flow

```
用户访问 Dashboard → Vue Router 加载 Dashboard.vue
                    ↓
              onMounted() 调用 workflowStore.refreshStatus()
                    ↓
              axios.get('/api/workflow/status/{thread_id}')
                    ↓
              FastAPI 调用 graph.aget_state(config)
                    ↓
              返回 LangGraph 状态（phase, next, values）
                    ↓
              Pinia store 更新 workflowState
                    ↓
              Vue 组件响应式渲染
                    ↓
              startPolling(5000) 开始轮询
```

### Review Submission Flow

```
用户点击 APPROVE → Review.vue 触发 submitReview()
                 ↓
           构造 ReviewDecision { decision: 'approved', comments: '' }
                 ↓
           axios.post('/api/review/submit/{thread_id}', decision)
                 ↓
           FastAPI 调用 graph.ainvoke(Command(resume=decision), config)
                 ↓
           LangGraph 从 review_gate 恢复执行
                 ↓
           返回新状态（next_phase: 'publishing'）
                 ↓
           前端跳转到 Dashboard 或显示成功提示
```

### Analytics Data Fetch Flow

```
用户访问 Analytics → Vue Router 加载 Analytics.vue
                    ↓
              onMounted() 并行调用三个 API
                    ↓
              axios.get('/analytics/report/{account_id}')
              axios.get('/analytics/performance/{account_id}')
              axios.get('/analytics/costs')
                    ↓
              FastAPI 从 Memory Store 或数据库读取
                    ↓
              返回 JSON 数据
                    ↓
              Pinia store 更新 analytics 数据
                    ↓
              Vue 组件渲染图表（ECharts 或自定义 CSS 图表）
```

## Technical Details

### Vue 3 + Vite 配置

**Location**: `frontend/vite.config.ts`

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

### Tailwind CSS 配置

**Location**: `frontend/tailwind.config.js`

```javascript
module.exports = {
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // 霓虹配色
        neon: {
          pink: '#FE2C55',      // 小红书粉色
          cyan: '#4ECDC4',      // 青色
          purple: '#667eea',    // 紫色
          peach: '#FFE4E1',     // 柔粉色
        },
        // 暗色背景
        dark: {
          bg: '#0a0a0a',
          panel: '#1a0a2e',
          card: '#0f1a2a',
        },
      },
      fontFamily: {
        mono: ['Monaco', 'Consolas', 'monospace'],
      },
      boxShadow: {
        'neon-pink': '0 0 20px rgba(254,44,85,0.5), 0 0 40px rgba(254,44,85,0.3)',
        'neon-cyan': '0 0 20px rgba(78,205,196,0.5), 0 0 40px rgba(78,205,196,0.3)',
        'neon-purple': '0 0 20px rgba(102,126,234,0.5), 0 0 40px rgba(102,126,234,0.3)',
      },
    },
  },
  plugins: [],
}
```

### FastAPI Static Files Mount

**Location**: `xhs_growth/api/app.py` (修改)

```python
from fastapi.staticfiles import StaticFiles

# ... existing code ...

# 托管前端静态文件
import os
dist_dir = os.path.join(os.path.dirname(__file__), '../../frontend/dist')
if os.path.exists(dist_dir):
    app.mount('/', StaticFiles(directory=dist_dir, html=True), name='static')
```

**注意**: 需要确保 API 路由优先于静态文件挂载，否则 `/api/*` 会被静态文件拦截。

## File Structure (Complete)

```
XhsGrowthAgent/
├── frontend/                    # Vue 前端项目（新增）
│   ├── src/
│   │   ├── views/              # 页面组件
│   │   │   ├── Dashboard.vue
│   │   │   ├── Review.vue
│   │   │   ├── Analytics.vue
│   │   │   └── Home.vue
│   │   ├── components/         # 通用组件
│   │   ├── api/                # API 调用
│   │   ├── stores/             # Pinia 状态
│   │   ├── styles/             # 样式
│   │   ├── router/             # 路由
│   │   ├── App.vue
│   │   └── main.ts
│   ├── dist/                    # 构建产物（FastAPI 托管）
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── package.json
│   └── tsconfig.json
│
├── xhs_growth/                  # 后端 Python（现有）
│   ├── api/
│   │   ├── app.py              # 修改：添加 StaticFiles mount
│   │   ├── routes/
│   │   │   ├── workflow.py
│   │   │   ├── review.py
│   │   │   └── analytics.py
│   │   └── __init__.py
│   ├── ...
│
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-24-frontend-pages-design.md  # 本文档
│
├── pyproject.toml              # Python 依赖（现有）
├── package.json                # Node 依赖（新增）
└── README.md                   # 更新：添加前端说明
```

## Dependencies

### New Dependencies (frontend/package.json)

```json
{
  "name": "xhs-growth-frontend",
  "version": "0.1.0",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.3.0",
    "pinia": "^2.1.0",
    "axios": "^1.6.0",
    "element-plus": "^2.5.0",
    "echarts": "^5.5.0"          # 可选：数据可视化
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "typescript": "^5.3.0",
    "vue-tsc": "^2.0.0",
    "vite": "^5.0.0",
    "tailwindcss": "^3.4.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0"
  }
}
```

### Existing Dependencies (Python)

无新增 Python 依赖，FastAPI StaticFiles 已内置。

## Implementation Plan

### Phase 1: 项目初始化

**时间**: 1天

1. 创建 `frontend/` 目录
2. 初始化 Vue 3 + Vite 项目
3. 配置 Tailwind CSS
4. 配置 Element Plus
5. 创建路由结构
6. 创建 Pinia stores
7. 创建 API client layer

### Phase 2: 组件开发

**时间**: 3天

1. Navbar.vue - 左侧导航栏
2. NeonButton.vue - 霓虹风格按钮
3. StatusCard.vue - 状态卡片
4. WorkflowTimeline.vue - 六边形时间轴
5. ContentPreview.vue - 内容预览卡片
6. ChartBar.vue - 柱状图组件
7. ChartPie.vue - 饼图组件

### Phase 3: 页面开发

**时间**: 4天

1. Dashboard.vue - 工作流仪表盘（赛博朋克风格）
2. Review.vue - 内容审核页面
3. Analytics.vue - 数据分析页面
4. Home.vue - 首页/路由入口

### Phase 4: 后端集成

**时间**: 1天

1. 修改 FastAPI app.py - 添加 StaticFiles mount
2. 确保 API 路由优先级
3. 测试前后端通信

### Phase 5: 构建部署

**时间**: 1天

1. 执行 `npm run build` 生成 dist/
2. 测试 FastAPI 托管静态文件
3. 验证同端口访问（http://localhost:8000）

### Phase 6: 测试验收

**时间**: 2天

1. 功能测试 - 三页面核心功能
2. 集成测试 - 前后端交互
3. 视觉测试 - 赛博朋克风格效果
4. 性能测试 - 轮询刷新性能
5. 跨浏览器测试 - Chrome/Safari/Firefox

**总计**: 约 12 天

## Testing Strategy

### Frontend Unit Tests

**Location**: `frontend/src/__tests__/`

使用 Vitest + Vue Test Utils：

- API client 测试 - axios 封装
- Pinia store 测试 - 状态管理逻辑
- 组件测试 - 霓虹按钮、卡片组件

### Integration Tests

**Location**: `frontend/tests/integration/`

使用 Cypress 或 Playwright：

- Dashboard 工作流状态刷新
- Review 审核提交流程
- Analytics 数据加载

### Visual Tests

**Location**: `frontend/tests/visual/`

手动测试或 Storybook：

- 赛博朋克视觉效果
- 发光效果渲染
- 动画流畅度

## Success Criteria

### Feature Success

- ✅ Dashboard 实时显示工作流进度和各阶段输出
- ✅ Review 支持三态审核操作（通过/修改/拒绝）
- ✅ Analytics 显示核心指标、趋势图表、帖子列表
- ✅ 同端口部署成功（FastAPI 托管静态文件）

### Quality Success

- ✅ 赛博朋克视觉效果一致（暗色背景、霓虹配色、发光效果）
- ✅ API 通信正常（axios/fetch 封装）
- ✅ 状态管理正确（Pinia stores）
- ✅ 路由跳转流畅（Vue Router）
- ✅ 跨浏览器兼容（Chrome/Safari/Firefox）

### Performance Success

- ✅ 首屏加载时间 < 2秒
- ✅ 轮询刷新不影响交互性能
- ✅ 图表渲染流畅（无卡顿）

## Risks and Mitigation

### Risk 1: 前后端路由冲突

**Mitigation**: 确保 FastAPI API 路由优先于 StaticFiles mount，使用 `app.include_router()` 先于 `app.mount()`。

### Risk 2: 跨域问题

**Mitigation**: Vite 开发模式使用 proxy，生产模式同端口部署无跨域问题。

### Risk 3: 轮询性能影响

**Mitigation**: 使用 5秒间隔轮询，避免高频请求；后续可升级为 WebSocket。

### Risk 4: 赛博朋克动画性能

**Mitigation**: 使用 CSS transform 和 opacity 动画，避免 layout 和 paint；使用 `will-change` 优化。

## Future Enhancements

- WebSocket 实时通信替代轮询
- 多账号支持（账号切换）
- 内容编辑器（在线编辑文案）
- 图片上传（上传自定义图片）
- 深色/浅色主题切换
- 移动端适配优化
- PWA 支持（离线访问）

---

**设计文档版本**: v1.0
**编写日期**: 2026-05-24
**状态**: 已批准，待实现