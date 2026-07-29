# Chrome 运行时资源审计

2026-07-29 检查结果：3 个绑定账号均有一个主 Chrome 与一个 socat 转发器；renderer、GPU、utility、zygote 和 crashpad 是 Chromium 的正常子进程，不是重复 launcher。

三个 profile 合计约 1.3GB。两个大 profile 的 `Default/Cache` + `Code Cache` 分别约 319MB 和 332MB；另有每 profile 约 59MB `component_crx_cache` 与 49MB `optimization_guide_model_store`。这些目录不承载 Cookies、Local Storage 或 IndexedDB。

运行中的 profile 均被 cleanup dry-run 明确跳过，未删除任何数据。优化仅对下次 Chrome 启动生效：默认关闭 crash reporter；停止 profile 后的显式 cleanup 可回收扩展后的安全缓存 allowlist。
