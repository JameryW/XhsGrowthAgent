# 删除死前端组件

## 背景

前端 4 个 .vue 组件 0 引用（grep + 宽 grep + 自动注册检查确认）：

- `src/components/HealthCheckPanel.vue` (566L) — 系统健康检查 panel，无 view 引用
- `src/components/OfflineIndicator.vue` (50L) — 离线指示器
- `src/components/RetryIndicator.vue` (113L) — 重试指示器
- `src/components/LoadingOverlay.vue` (66L) — 加载遮罩

## 确认依据

- `grep -r <name> src/` 排除组件自身 → 0 命中（main.css 注释提及 LoadingOverlay 名称非引用）
- 无 `unplugin-vue-components` / vite glob 自动注册
- 4 组件无互相引用，依赖活组件（AppIcon/NeonButton/stores）

## AC

1. 删 4 .vue 文件
2. `npm run type-check`（vue-tsc）全绿
3. `npm run test`（vitest）全绿
4. vite build 留 CI（本机 OOM，记忆 vite-build-oom-low-ram-box）

## 风险

低。0 引用。type-check + vitest 作 gate。
