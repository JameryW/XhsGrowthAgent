# XHS Growth Agent Frontend

Vue 3 前端，采用赛博朋克设计主题。

## 技术栈

- **Vue 3.4** + Composition API
- **Vite 5.0** - 构建工具
- **Tailwind CSS 3.4** - 样式框架
- **Pinia 2.1** - 状态管理
- **Vue Router 4.3** - 路由

## 开发

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev
# 访问 http://localhost:3000

# 构建生产版本
npm run build

# 预览生产构建
npm run preview
```

## 目录结构

```
frontend/
  src/
    api/          # API 客户端
      client.ts   # 基础客户端配置
      review.ts   # Review API
      workflow.ts # Workflow API
    components/   # 可复用组件
      ContentCard.vue
      NeonButton.vue
      WorkflowNode.vue
    router/       # 路由配置
    stores/       # Pinia 状态管理
      review.ts   # Review 状态
      workflow.ts # Workflow 状态
    styles/       # 全局样式
    types/        # TypeScript 类型定义
      review.ts   # Review 类型
      workflow.ts # Workflow 类型
    views/        # 页面组件
      Analytics.vue  # 数据分析页
      Dashboard.vue  # 仪表盘
      Home.vue       # 首页
      Review.vue     # 人工审核页
```

## 页面说明

| 页面 | 路径 | 功能 |
|-----|------|-----|
| 首页 | `/` | 项目介绍和入口 |
| 仪表盘 | `/dashboard` | 工作流进度展示 |
| 审核 | `/review` | 人工审核内容 |
| 分析 | `/analytics` | 数据分析报告 |

## API 类型同步

前端类型从后端 OpenAPI 规范自动生成:

```bash
# 从根目录运行
./scripts/generate_types.sh
```

生成的类型文件:
- `frontend/src/types/review.ts`
- `frontend/src/types/workflow.ts`

## 设计主题

赛博朋克风格:
- **霓虹色彩**: cyan (#00FFFF), magenta (#FF00FF)
- **深色背景**: #0a0a0f, #1a1a2e
- **发光效果**: neon glow shadows
- **网格背景**: CSS grid patterns

## 测试

```bash
# 单元测试
npm run test

# E2E 测试
npm run test:e2e
```