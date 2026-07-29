# Chrome profile 后台页面资源诊断与安全回收

## 目标

降低长期运行 profile 中无用后台页面带来的 renderer 占用，同时绝不影响登录态、活跃 CDP 操作或业务页面。

## 范围

- 对每个账号的公开 CDP 端点只读枚举 page target，显示页面总数与可安全关闭的空白页数量。
- 仅将 `about:blank` 与 `chrome://newtab/` 这类无业务内容的 page target 视为候选；任何非 page、业务 URL、Chrome 设置页或无法识别的 target 都必须跳过。
- 仅当同一 profile 至少有两个 page target 时才允许候选关闭，始终保留至少一个 page，绝不关闭最后标签页。
- 提供显式、按账号选择的应用操作；默认 dry-run，且检测到活跃或无法确认的 CDP 连接时 fail closed，不关闭任何页面。
- 实际关闭仅走该账号已经绑定的公开 CDP 端点，并报告逐页结果；不启动第二个浏览器、不操作 Cookies/Local Storage，也不重启 Chrome。
- 覆盖 target 枚举、候选过滤、活跃连接保护、dry-run 与 apply 的单测；更新部署和浏览器安全规范。

## 验收

- 默认命令没有任何页面关闭副作用。
- 所有关闭行为均需显式 `--apply`，且只会影响已验证的空白 page target。
- 任何端点错误或连接状态不明均保守跳过；在线 CDP 和登录态不受影响。
- 定向测试、静态检查和完整单测通过。
