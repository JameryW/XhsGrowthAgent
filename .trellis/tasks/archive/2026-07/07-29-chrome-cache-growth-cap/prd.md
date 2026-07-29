# Chrome 缓存增长上限与资源可观测性

为每个新启动的 headed Chrome 设置可配置的 HTTP 磁盘缓存提示上限，默认 128MB，减缓多 profile 的 `Default/Cache` 持续膨胀。环境变量 `XHS_CHROME_DISK_CACHE_SIZE_MB=0` 必须能显式保留 Chrome 默认值。

约束：不影响登录态、CDP endpoint、账号 profile 隔离或当前运行的浏览器；无效环境变量不得阻断启动，应记录警告并回退默认值。

验收标准：

- launcher 命令默认带字节单位的 `--disk-cache-size`。
- 关闭、覆盖和非法配置均有单元测试。
- 部署文档、浏览器安全规范和完整 unit 测试通过。
