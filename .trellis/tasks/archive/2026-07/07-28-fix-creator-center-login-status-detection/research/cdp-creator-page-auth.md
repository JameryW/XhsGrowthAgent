# CDP 创作者中心登录证据研究

## 已确认事实

- `GET /api/accounts/{account_id}/login/status` 最终调用
  `backend.services.xhs_login.inspect_profile_login_status`。
- raw CDP 路径当前只执行 `Storage.getCookies`，并要求
  `access-token-creator.xiaohongshu.com`。
- 现场绑定 Chrome 同时存在主站 `id_token`、`web_session` 和
  `creator.xiaohongshu.com/new/home` 页面；该页面能渲染账号名、发布笔记和数据看板。
- 现有 Creator Stats CDP transport 已使用 Creator Center 页面自身的 DOM/API 作为
  登录壳检测依据；本修复复用其“页面证据优先于主站菜单文案”的思路，但不导航页面。
- 使用当前绑定 Chrome 的真实 raw CDP 做只读回归后，页面证据返回
  `logged_in / creator_page_ready`；这确认当前账号的误判来自 Cookie-only 探针，而不是
  Creator Center 页面没有登录。

## 设计约束

- `www_only` 不能被 Cookie 规则直接改成已登录，否则会重新引入 Creator API 401 的误判。
- 登录状态探针是只读操作，不能为了确认登录而导航常驻 Tab、开新 Tab 或关闭宿主 Chrome。
- CDP 只返回布尔状态和稳定的标记名，不输出 Cookie 值或完整页面正文。
