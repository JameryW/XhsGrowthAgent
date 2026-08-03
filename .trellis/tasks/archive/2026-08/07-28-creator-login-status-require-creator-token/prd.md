# creator-login-status-require-creator-token

## 背景

设置页「已登录」基于 cookie 启发式。此前把 `web_session` + `id_token`（主站 SSO 对）也算 logged_in，导致：

- UI 绿色「已登录」
- 创作者中心 API 仍 HTTP 401（缺 `access-token-creator.xiaohongshu.com`）
- 定时同步失败，用户困惑

前端 / preflight 已预留 `www_only` / `missing_creator_token` 文案，但后端未产出该 reason。

## 目标

1. **仅**存在 `access-token-creator.xiaohongshu.com` 时 `status=logged_in`。
2. `web_session` + `id_token` 无 creator token → `logged_out` + `reason=www_only`。
3. 设置页显示「主站已登录，创作者中心未登录（请重新扫码）」；preflight 同步前拦截并给出明确错误。
4. 单测更新；不改同步爬取主路径（HTTP 401 仍为权威）。

## 非目标

- 不做实时 creator API probe（CDP 导航成本高）。
- 不强制改 QR 弱回退（页面文案检测）。
