# Chrome profile 内存健康观测与告警

## 目标

在不重启在线 Chrome、不触碰登录态、也不改变账号 CDP 隔离的前提下，为每个 profile 的资源状态提供可操作的内存观测，帮助识别长期运行后的异常增长。

## 范围

- `status` 在现有 CDP 连通性和 `safe_cache` 外，显示该 profile Chrome 进程树的进程数量与 RSS 合计。
- 仅接受已由 launcher 写入的 pidfile 且仍匹配该 profile 的浏览器进程；缺失或不可信时显示 `unknown`，绝不猜测或操作进程。
- 支持可选内存告警阈值；默认关闭。超过阈值只标注状态，不自动重启、回收、清理或改变 Chrome 参数。
- 覆盖正常、未知 pid、进程树聚合和阈值告警的单测；更新部署与浏览器安全规范。

## 验收

- 所有 Chrome 进程统计均为只读，错误时 fail closed。
- 当前在线 profile 保持在线，登录态与 CDP 端口不受影响。
- 定向单测、静态检查及完整单测通过。
