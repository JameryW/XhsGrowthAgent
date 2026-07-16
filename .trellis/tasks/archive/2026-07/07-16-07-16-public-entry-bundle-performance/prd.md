# 公开入口包体优化

## 背景

首页和回放页是公开沉浸式入口，但 `App.vue` 通过 stores barrel 引入认证、实时、快捷键等依赖。即便已把工作区导航组件异步化，公共入口仍可能携带登录后才需要的 store 模块，增加下载和解析时间。

## 目标

- 公开首页/回放首屏只加载 App 实际使用的 store 模块，不因 barrel re-export 拉入无关工作区 store。
- 保持认证工作区、快捷键、实时连接、Toast 和 ErrorBoundary 行为不变。
- 用构建产物体积和全量测试确认拆分没有引入路由/插件初始化回归。

## 方案

1. `App.vue` 将 stores barrel import 改为按模块直接导入 `realtime`、`onboarding`、`shortcuts`、`auth`。
2. 仅在公共入口不需要时继续保持现有工作区组件的异步加载策略，不改变可见 loading/error 状态。
3. 对比构建产物入口 chunk，若拆分未带来收益则回滚无效改动。

## 验收标准

- 首页/回放可正常渲染，公开路由不建立 WebSocket；受保护工作区仍建立连接并可使用快捷键/引导。
- `npm run type-check`、`npm run build`、全量 Vitest 通过。
- 入口 chunk 体积不增加；无新增运行时 warning。

## 非目标

- 不改变 stores 的公共导出 API，不修改后端接口。
- 不删除用户进入工作区后仍需要的模块或功能。
