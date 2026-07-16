# 首页与回放页继续加载优化

## 背景

首页进入回放时，回放页会先请求工作流实时状态，再串行请求 checkpoint 历史；两次接口延迟叠加。回放页还静态加载所有阶段结果组件，即使首屏只展示一个 checkpoint，也会把非当前阶段的代码带入首屏 chunk。

## 目标

- 回放页实时状态与 checkpoint 历史并行获取，减少成功路径的网络等待。
- 结果面板按当前选中的 agent 懒加载，降低回放页首屏 JavaScript 体积。
- 保留现有错误态、404 语义、重试、URL checkpoint 同步和无障碍 loading 状态。

## 方案

1. `WorkflowReplay.vue` 在设置 threadId 后并行启动状态请求与 `enterReplayMode`，统一等待结果；工作流不存在时仍退出回放模式，其他状态错误继续允许历史回放展示。
2. 使用 `defineAsyncComponent` 拆分 Trend/Plan/Creative/Visual/Publish/Analytics/Ripple 结果组件，仅在对应结果出现时加载。
3. 为异步结果组件保留统一的局部加载 fallback，避免网络慢时详情区域跳动或空白。

## 验收标准

- 正常回放加载不再出现“状态请求完成后才开始历史请求”的串行瀑布。
- 回放首屏保留 pipeline、checkpoint 骨架和错误提示；选中结果后对应面板可正常显示。
- 404 工作流仍展示 not found 状态；状态接口失败但历史可用时仍可浏览回放。
- `npm run type-check`、`npm run build`、全量 Vitest 通过。

## 非目标

- 不修改后端接口、checkpoint 数据结构或鉴权策略。
- 不改变首页已有的会话缓存与公开路由优化。
