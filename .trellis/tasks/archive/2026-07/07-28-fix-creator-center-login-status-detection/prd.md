# 创作者中心登录状态探针修复

## 背景

设置页调用账号登录状态接口时，后端目前只根据
`access-token-creator.xiaohongshu.com` Cookie 判定创作者中心是否登录。
当前绑定 Chrome 的创作者中心页面已经打开并显示账号数据，但该 Cookie 不在
Cookie 列表中，接口因此返回 `logged_out / www_only`，前端持续显示“创作者中心未登录”。

## 目标

在不放宽“仅有主站 Cookie 不能算创作者中心登录”的安全规则前提下，识别已经由
创作者中心自身页面验证成功的登录态。

## 范围

- 修改 `backend/services/xhs_login.py` 的只读登录状态探针。
- 通过现有 CDP 浏览器中的创作者中心页面状态确认登录，不主动导航、创建页面或关闭常驻 Chrome。
- 同时覆盖 raw CDP（容器连接宿主 Chrome）和 Playwright CDP 回退路径。
- 保留 Creator access token、`www_only`、过期 Cookie 等现有判断语义。
- 增加单元测试，覆盖无 Creator Cookie 但创作者中心页面已登录、页面为登录壳、以及现有 Cookie 规则回归。
- 更新后端规范，记录页面证据与 Cookie 证据的判定边界。

## 验收标准

1. `id_token + web_session` 且现有创作者中心页面显示已登录业务界面时，登录状态接口返回 `logged_in`。
2. `id_token + web_session` 且只有登录壳、无创作者中心业务界面时，仍返回 `logged_out / www_only`。
3. `access-token-creator.xiaohongshu.com` 仍直接返回 `logged_in / strong_cookie`。
4. 探针不导航已有页面、不创建新 Tab、不关闭宿主 Chrome，也不记录 Cookie 值或页面隐私正文。
5. raw CDP 和 Playwright 回退路径均有覆盖，相关 pytest、ruff 和类型检查通过。

## 技术方案

增加一个只读 Creator Center 页面状态脚本：要求页面位于
`creator.xiaohongshu.com`，不处于登录路径或登录壳，并命中至少两个稳定业务界面
标记（例如“发布笔记”“数据看板”“笔记管理”“粉丝”）。

raw CDP 路径使用 `Target.getTargets` 找到现有 Creator Center page，临时 attach 后
执行 `Runtime.evaluate`，完成后立即 detach；Playwright 路径遍历已有 context/page
并执行同一个状态脚本。页面证据只作为没有强 Creator Cookie 时的补充证据，最终返回
稳定的 `creator_page_ready` reason 和 signal。
