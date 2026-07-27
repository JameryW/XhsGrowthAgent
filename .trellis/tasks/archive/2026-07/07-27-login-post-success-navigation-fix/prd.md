# 登录成功后页面跳转问题修复

## Goal

修复两条登录链路的"登录成功后页面没有跳转"：
A) XHS 扫码确认后 host Chrome 登录 tab 直接消失（confirmed 即 stop() 关页）——改为保留 tab 停在 creator 首页；
B) 控制台登录成功后路由守卫静默回退 /login（initialize() 的 validateToken 失败会 clearAuth 抹掉新 token）——修守卫 + 加固 + redirect 防开放重定向。

## Requirements

### 链路 A：XHS 扫码登录保留已登录页面

* `get_status()` confirmed 分支（xhs_login.py:670-687）：warm creator 后**不再** `self.stop()` 关页；改为释放 playwright/CDP 连接但保留 host Chrome tab（停在 creator home）。
* `start()` 已登录短路分支（:514-542，_wait_for_existing_login 命中）同样保留 tab，行为一致。
* confirmed 后从 `_sessions` 字典 pop 自己（不滞留内存；下次登录尝试能新建会话）。
* 模式区分：connect_over_cdp（主路径）→ 断连接留 tab；raw CDP → 关 ws 不发 Target.closeTarget 留 tab；launch_persistent_context 兜底（风控罕见路径）→ 维持原 stop() 行为（断开即杀进程，留不住）。注释说明。
* 前端 QrLoginModal.vue：删除 confirmed 后三处显式 `stopQrLogin` 调用（:121, :186, :222）——否则会关掉刚保留的 tab。cleanup() 已有 `status !== 'confirmed'` 守卫，不动。

### 链路 B：控制台登录守卫静默回退

* `stores/auth.ts login()`：成功后置 `isInitialized.value = true`——刚登录的 token 无需再 validateToken 往返，守卫不再触发 initialize()。
* `stores/auth.ts initialize()`：传输错误（NETWORK_ERROR）不再 clearAuth——仅在服务端明确 invalid（含 401）时清除。瞬时网络抖动不再踢出已登录用户。
* `views/Login.vue`：`redirect` 查询参数白名单校验——必须以单个 `/` 开头（拒 `//`、`\`、绝对 URL），防开放重定向。非法值回落 `/dashboard`。

## Acceptance Criteria

* [ ] 扫码确认成功后，host Chrome 中该账号的 tab 保留并停在 creator.xiaohongshu.com/new/home（CDP 模式）
* [ ] 关闭 QR modal（confirmed 后）不触发 stopQrLogin，tab 不被关
* [ ] 未确认时关闭 modal 仍正常 stop 清理（回归）
* [ ] 同账号再次点登录：session 已 pop，能正常开新 QR 流程（profile 有效则短路 confirmed）
* [ ] 控制台登录成功后直达 /dashboard，无 validateToken 往返（network tab 可验）
* [ ] 登录成功瞬间断网/后端重启，刷新页面不被踢回 /login（token 保留）
* [ ] `?redirect=//evil.com` / `?redirect=https://x` 登录后落 /dashboard 而非外站
* [ ] 既有测试绿 + 新增/调整用例覆盖 confirmed 不关页、initialize 错误分类、redirect 校验
* [ ] push 前三连：ruff format --check + ruff check . + 全量 mypy backend + 全量 pytest；前端 vue-tsc typecheck（本机 build OOM，build 留 CI）

## Definition of Done

* 行为变化的注释同步更新（xhs_login.py 496-498 / 684-686 旧注释改写）
* 单 PR，从 main 切分支（记忆：separate-pr-per-feature）

## Decision (ADR-lite)

**Context**: confirmed 即关页是有意的资源回收设计（注释 684-686），但与操作员期望（看到已登录页面）冲突；CDP 模式下 host Chrome 本就常驻（launcher 管），留一个 tab 成本≈0。
**Decision**: CDP/raw-CDP 模式留 tab + 断连接 + pop session；persistent 兜底维持关页。前端配合去掉 post-confirmed stop。
**Consequences**: host Chrome 会累积已登录 tab（操作员手动关或下次登录复用同 profile 不冲突）；`stop_all_sessions` 进程退出时不再关这些已脱管 tab——可接受（host Chrome 常驻，tab 即登录态可视化）。

## Out of Scope

* xhs 自家 explore 页确认后不自动刷新（xhs 前端行为，不可控，无需修）
* 多账号并发登录的 tab 管理 UI
* validateToken 后端语义改动

## Technical Notes

* 会话注册表：`_sessions: dict[account_id, XhsLoginSession]`（xhs_login.py:1470）；stop_session pop+stop，stop() 仅关资源不 pop
* 前端 stop 调用点：QrLoginModal.vue:121/186/222（confirmed 后，删）+ cleanup():247（未 confirmed，留）
* client.ts 错误分类：传输错误 code='NETWORK_ERROR'；HTTP 错误带服务端 code（401 → AUTH 类 code，待确认后端 validate 路由）
* redirect 当前无校验（Login.vue:42），window.location.assign 路径存在开放重定向面
* 测试：backend tests/ 搜 xhs_login 相关；frontend 检查 vitest 存在性，无则 vue-tsc gate + 手工验
