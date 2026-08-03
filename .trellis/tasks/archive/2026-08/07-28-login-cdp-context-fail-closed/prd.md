# 登录 CDP 缺失上下文时安全失败

## 背景

扫码登录服务在连接已有 Chrome CDP 后，如果返回的 browser 没有 context，会调用 `browser.new_context()` 创建隔离上下文。该上下文不一定绑定账号的持久 profile，可能导致二维码登录态写入错误位置，并使登录状态探测与后续发布使用不同会话。

## 目标

1. CDP 登录只复用已有 browser context，不创建新的隔离 context。
2. 没有可用 context 时立即返回明确的 `LoginError`，提示启动绑定账号 Chrome。
3. 保留 raw CDP 路径和 CLI 中明确的人工一次性登录能力。
4. 增加回归测试，保证缺少 context 时不会调用 `new_context()`。

## 非目标

- 不修改扫码二维码协议、验证码处理或 Creator Center/主站登录分流。
- 不删除 CLI 的 headed 一次性登录入口。
- 不改变已有 context 内创建短生命周期登录 tab 的行为。

## 验收标准

- CDP browser 无 context 时抛出可操作的 `LoginError`，且不调用 `browser.new_context`。
- 正常 CDP 登录、raw CDP 登录和已有测试保持通过。
- ruff、mypy、相关登录测试通过。
