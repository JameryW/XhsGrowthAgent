# Chrome 生命周期与进程资源优化

本任务优化每账号常驻 Chrome 的生命周期、重复启动、登录回退和 profile 缓存，保留 headed real-Chrome/CDP 约束。
## 交付范围

- 每 profile OS flock 与 PID/profile 归属校验，防并发重复启动和误杀 PID 复用进程。
- `--account-id` 选择性 start/status/stop，`reap` 空闲回收，`cleanup` dry-run/allowlist 缓存清理。
- 服务注册表严格复用 CDP；缺 endpoint 时 fail-closed，禁止再启动 Playwright persistent browser。
- headed/Xvfb 仅在 start 时产生副作用；status/stop/maintenance 保持只读或定向操作。

## 验收

- 相关服务测试 116 passed；launcher 增量安全测试 41 passed。
- Ruff lint/format、严格 mypy、py_compile、shell syntax、CLI help 均通过。
- 2026-07-29 运行时核对：3 个账号各一套 Chrome+socat，status 全部 alive。
