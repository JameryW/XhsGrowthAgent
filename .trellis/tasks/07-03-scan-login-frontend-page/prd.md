# 扫码登录前端页面

## Goal

为小红书账号扫码登录提供 web 前端页，替代当前只能在 host 上跑 `xhs-growth login <account_id>` CLI 的体验。运营在浏览器完成"发起登录→扫码→登录态写 profile"全流程，无需 SSH host。

## Requirements

* 前端页：账号列表中点"扫码登录"按钮发起某账号登录
* 后端 endpoint：`POST /accounts/{id}/login/qr` 启动 headless Chrome 开 www 登录页，拦截 `qrcode/create` 返回 `qr_id` + `url`
* 后端 endpoint：`GET /accounts/{id}/login/qr/status` 轮询 `qrcode/status` 的 `codeStatus`（0=待扫/1=已扫/2=已确认），登录成功后 cookie 写入 `account.chrome_profile_path`
* 前端用 `qrcode` JS 库把 `url` 渲染成矢量二维码显示
* 前端 SSE/轮询 status，扫码确认后提示完成
* 登录态写入 profile，launcher 常驻 CDP Chrome 复用（无需再扫码）

## Acceptance Criteria

* [x] 前端发起扫码 → 显示二维码（PR2 QrLoginModal，vue-tsc+build 过）
* [x] 手机扫码确认 → 前端收到"登录成功"（PR2 status 轮询 confirmed 分支，单测覆盖）
* [x] 登录态写入该账号 `chrome_profile_path`（PR1 launch_persistent_context 自动持久化，单测覆盖）
* [ ] publisher 复用该 profile 能正常进入发布页（不跳登录）—— **待实测**（cookie 跨子域，需部署+真扫码）
* [x] 超时/失败有清晰错误提示（PR1 LoginError→503 + PR2 error UI + 4min 超时）

## 实现状态（PR1+PR2 已 commit）

- PR1 `8b0a29c2`：后端 service + 3 endpoint + 36 测
- PR2 `6578e63c`：前端 API + QrLoginModal + 面板按钮 + i18n + qrcode 依赖
- 校验全绿：ruff + mypy + pytest 1139 过 + vue-tsc + vite build

## 待人工验证清单（部署后跑）

容器需重新部署含 PR#179 迁移（accounts.chrome_profile_path 列）+ PR1 代码的镜像，然后：

1. 跑 `verify_qr_login_e2e.py <account_id>`（容器内）—— 全链路 + cookie 跨子域自动判定
2. 若 creator publish 跳登录 → cookie 跨子域失败 → 走 Xvfb 降级（creator 页 headed 扫码）或改 publisher 用 www 域
3. web 端 Settings→账号→扫码登录，真机扫码走通 UI

## Definition of Done

* Tests：endpoint 单测（mock playwright）+ 前端组件测
* Lint / typecheck / CI green
* 容器内 chromium 已就绪（现状确认），无需额外装 Xvfb

## Technical Approach

**路径 B'（spike 已验证可行）**：
1. 后端 headless Chrome（chromium 已在容器）开 `https://www.xiaohongshu.com/explore`，登录浮层自动触发 `qrcode/create`
2. `page.on("response")` 拦截 `qrcode/create` → 返回 `{qr_id, url}` 给前端
3. 前端 `qrcode` 库渲染 `url` 为二维码
4. 后端轮询 `qrcode/status`（或前端 SSE 拉后端转发），`codeStatus` 2=确认 → 登录态 cookie 写入 profile
5. stealth 注入复用 publisher 现有 `playwright-stealth` 基础设施

**为什么不是 creator 页**：creator.xiaohongshu.com/login 只有短信/密码登录 tab，无二维码 UI（spike 实测）。www 站登录浮层才有二维码。cookie 域 `.xiaohongshu.com` 同根域，creator 子域理论可复用——实现阶段实测确认。

## Decision (ADR-lite)

**Context**: 容器无 display，CLI login 在 host 跑 headed Chrome 不可复用于 web。需纯 web 方案让用户扫码。
**Decision**: 路径 B'——headless Chrome + 拦截 qrcode/create 接口取 url + 前端自渲染二维码 + 轮询 status。不走 Xvfb（无需），不走截图（url 是字符串非图）。
**Consequences**: 依赖 xhs www 站登录接口稳定性（接口变更需跟）；headless 下 shield 拦截风险（spike 未见，但需降级预案：被拦则走 Xvfb+headed）。cookie 跨子域复用需实测。

## In Scope（扩展 MVP）

* 二维码过期自动刷新：qr 有有效期，status 返回失效码 → 后端自动重拉 `qrcode/create` 推新 url，前端二维码无感刷新
* 多账号并发扫码：每账号独立 headless Chrome + 独立 profile，并行互不干扰（复用 chrome_launcher 多 profile 模型）。前端每账号行各自独立按钮+状态

## Out of Scope

* 短信/密码登录（仅扫码）
* 已扫码未确认的远程撤回（用户手机侧操作即可）

## Research References

* [`research/xhs-creator-login-qr.md`](research/xhs-creator-login-qr.md) — creator 页无二维码 UI；www 页 qrcode/create 接口 headless 下 200 可用；路径 B' 验证可行

## Technical Notes

* CLI 旧实现: backend/cli/main.py:457-580（host headed Chrome，作废弃参考）
* Launcher: backend/services/chrome_launcher.py（ensure_chrome/stop_chrome/status_all，复用 profile）
* stealth 基础设施: backend/services/xhs_publisher.py:139-152（playwright-stealth + webdriver 隐藏 fallback）
* 账号 DB: backend/db/accounts.py（AccountRow.chrome_profile_path / cdp_port）
* 前端账号面板: frontend/src/components/settings/XhsAccountsPanel.vue（加扫码按钮入口）
* 前端 API: frontend/src/api/accounts.ts（加 login/qr + status 调用）
* 路由 `/login` 已占（系统登录），扫码页放 Settings tab 内或 `/settings` 子路由
