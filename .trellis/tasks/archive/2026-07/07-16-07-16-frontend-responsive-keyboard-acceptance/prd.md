# 前端响应式与键盘验收收尾

## 目标

完成展示页、回放页及主业务路由的真实浏览器验收，补齐窄屏布局、焦点路径和动效降级问题。

## 范围

- `/` 展示页：筛选、列表、详情入口、空态与错误重试。
- `/replay/:threadId` 回放页：检查点切换、返回上下文、移动端抽屉。
- `/start`、`/dashboard`、`/review`、`/history`、`/analytics`、`/evaluation`：主动作、错误态和键盘可达性。
- 视口：320、390、768、1024、1440；检查页面级横向溢出与首屏信息层级。

## 验收标准

- 主要交互均可通过 Tab、Enter、Space、Escape 完成，焦点可见且返回路径稳定。
- 视口宽度不出现非预期页面级横向滚动，展示页和回放页首屏优先呈现业务证据。
- reduced-motion 下无持续装饰动画或大幅位移动效。
- 发现的问题完成修复并有自动化/浏览器证据。
- `npm run type-check`、`npm run test:run`、`npm run build`、`git diff --check` 通过。

## 验收记录（2026-07-16）

- 浏览器使用真实后端数据完成 Showcase → Replay：Showcase 列表含真实工作流；Tab 可依次到跳转链接、筛选器、排序和详情；Enter 可打开回放并保留 `from/status/mode/sort/checkpoint` 上下文。
- Showcase 在 320、390、768、1024、1440px 下 `document.documentElement.scrollWidth === innerWidth`，无页面级横向滚动；修复了 1024px 英雄区长文案造成的 flex 内部溢出。
- Replay 使用真实已完成工作流验证，390px 与 1440px 均渲染状态、步骤、产出摘要和回放信息，页面级横向滚动为 0；移动检查点切换按钮的 `aria-expanded` 可由 false 切换为 true。
- 新增 `VITE_BACKEND_PROXY_TARGET`，允许本地开发代理对接部署端口（默认仍为 `http://localhost:8000`）。
- 质量门禁：`npm run type-check`、`npm run test:run`（39 files / 530 tests）、`npm run build`、`git diff --check` 全部通过。
