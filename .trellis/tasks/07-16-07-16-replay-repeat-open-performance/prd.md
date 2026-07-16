# 回放重复打开性能优化

## 背景

回放页已将实时状态和 checkpoint 历史请求并行，但用户从首页反复打开同一案例时仍会重新下载完整历史快照。历史快照包含多个阶段的大字段，网络慢时重复打开仍会看到骨架屏。

## 目标

- 在同一浏览器会话内重复打开同一回放时，先显示短期缓存的状态和 checkpoint，再后台刷新。
- 缓存命中不改变实时刷新、checkpoint 分页、404 和错误提示语义。
- 限制缓存体积、TTL 与版本，避免跨会话持久化和无限增长。

## 方案

1. 在 workflow store 的 replay history action 中增加版本化 `sessionStorage` 快照（按 threadId 分 key，30 秒 TTL），命中后先 hydrate 状态、checkpoint 和当前选中项，再发起后台 history 请求。
2. `WorkflowReplay` 将成功的 live status 写入同一会话快照；命中快照时立即解除 live skeleton，但仍保留后台请求和失败提示。
3. history 刷新成功后覆盖快照并清理不存在的 checkpoint；缓存解析失败、过期或 storage 不可用时回退现有请求流程。

## 验收标准

- 同一案例第二次打开时，在 history/status 请求返回前可看到上次的 pipeline、checkpoint 和详情。
- 后台刷新成功后页面使用最新数据；刷新失败保留缓存并显示可重试提示。
- 404 工作流不复用其他 thread 的缓存；缓存 key、版本、TTL 均可验证。
- 不影响 `loadMoreCheckpoints` 游标分页和 replay mode 退出清理。
- `npm run type-check`、`npm run build`、全量 Vitest 通过。

## 非目标

- 不修改后端 checkpoint 响应协议或减少用户主动加载的历史分页。
- 不把回放快照写入 localStorage、URL 或服务端。
