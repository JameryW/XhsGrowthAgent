# Chrome 运行时资源与缓存优化

在保留 headed real-Chrome、每账号独立 CDP profile 和登录数据的前提下，减少每个 Chrome 实例的无业务 crash-reporting 进程，并扩大安全缓存清理 allowlist；清理必须默认 dry-run、运行中 profile fail-closed，且不能触碰 Cookies、Local Storage、IndexedDB 等登录/站点状态。

验收标准：

- 新启动的 Chrome 默认不启动 crash reporter；设置显式环境变量后可恢复诊断进程。
- cleanup 能识别实际存在的 Chrome 缓存目录，仍保护登录数据与符号链接。
- 现有 launcher、登录、发布和完整 unit 测试保持通过。
