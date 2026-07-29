# Chrome 优化审计

当前 launcher 是每个活动账号一个 headed real Chrome，并通过独立 CDP 端口复用 profile。优化必须保留账号隔离、CDP 和 XHS 风控约束。
## 结论

常驻架构本身不是重复启动：当前 3 个账号各自拥有一个主 Chrome 和一个 socat 转发器，Chrome 的 renderer/GPU/utility 子进程属于正常多进程模型。主要优化点是生命周期按需化、跨进程锁、严格 CDP、空闲回收和安全缓存清理；运行中的 profile 不自动清理。
