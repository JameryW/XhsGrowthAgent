# Research: XHS Creator 扫码登录前端化技术方案

- **Query**: 研究小红书 creator 登录页二维码登录机制，为 web 前端页扫码登录提供技术方案（容器内无 Xvfb/无 DISPLAY）
- **Scope**: external（web 调研）+ internal（现有 CLI login / chrome_launcher 代码）
- **Date**: 2026-07-03

## TL;DR（核心结论）

creator.xiaohongshu.com/login 的二维码**不是 page 内 canvas/img 渲染的图片**，而是前端 JS 调 `POST /api/sns/web/v1/login/qrcode/create` 拿到 `{ qr_id, code, url }` 后、用 `url` 字段在客户端**自己渲染**二维码（`<canvas>`/`<img>`，由 xhs 前端 JS 库画）。登录态用 `GET /api/sns/web/v1/login/qrcode/status?qr_id=..&code=..` 轮询，返回 `codeStatus`（0=待扫 / 1=已扫待确认 / 2=已确认登录），确认后 `login_info` 含 `session`/`secure_session`/`user_id`，关键 cookie 为 `a1`/`webId`/`web_session`/`web_session_sec`。

**推荐方案：路径 B'（headless Chrome + 拦截 qrcode/create 响应）**——不需要 Xvfb，不需要截二维码元素图，直接用 Playwright headless 打开登录页、拦截 `qrcode/create` 的 XHR 响应取出 `url`，前端用 `qrcode` 库自己画二维码；后端轮询 `qrcode/status` 或让 headless 页面继续轮询、把状态推前端。这比截二维码元素图更干净（不依赖二维码 DOM 选择器、headless 下二维码是否渲染无关紧要）。备选路径 A（Xvfb + headed）仅当 headless 被 xhs shield 拦截时才需要。

## Findings

### 1. creator 登录页二维码形态

#### 1.1 页面是 Vue SPA，二维码由前端 JS 渲染

抓 `https://creator.xiaohongshu.com/login` 的 HTML shell，JS bundle 来自 `fe-static.xhscdn.com/formula-static/ugc/public/resource/js/`，含 `library-vue`、`library-element-plus`、`library-axios`、`library-cropper` 等。对 `project-publish-components.d5a2db4e.js` chunk grep，确认 creator 登录页**直接复用 www 站的登录接口**：

```
"/api/qrcode/userinfo"
"/api/sns/web/v1/login/check_code"
"/api/sns/web/v1/login/logout"
"/api/sns/web/v1/login/qrcode/create"     ← 创建二维码
"/api/sns/web/v1/login/qrcode/status"     ← 轮询登录状态
"/api/sns/web/v2/login/code"
"/api/sns/web/v2/login/send_code"
```

另在 `4763.406f9eb8.js` 出现 `"/api/cas/customer/web/qr-code"`（CAS/SSO 通道，非主登录路径）。

#### 1.2 qrcode/create 响应结构（关键）

`POST /api/sns/web/v1/login/qrcode/create` 返回标准 envelope `{ success, code, data: { ... } }`，`data` 含：

| 字段 | 说明 |
|---|---|
| `qr_id` | 二维码 ID，用于 status 轮询 |
| `code` | 校验码，用于 status 轮询 query |
| `url` | **二维码编码的 URL 字符串**（不是 base64 图片！） |

> 证据：reverse-engineered CLI 源码 `qr_data = client.create_qr_login(); qr_id = qr_data["qr_id"]; code = qr_data["code"]; qr_url = qr_data["url"]`，随后用 `qrcode` 库把 `qr_url` 渲染成终端二维码。说明接口只给 URL 字符串，二维码图像完全由客户端生成。

**含义**：前端页可以用 `qrcode` (npm) 库直接拿 `url` 自己画二维码，**无需截图二维码 DOM 元素**。

#### 1.3 qrcode/status 轮询与登录感知

`GET /api/sns/web/v1/login/qrcode/status?qr_id=<id>&code=<code>` 返回 `data`：

| 字段 | 值 |
|---|---|
| `codeStatus` | `0`=待扫, `1`=已扫待确认, `2`=已确认 |
| `userId` | `codeStatus==2` 时返回确认登录的用户 ID |
| `login_info` | 确认后含 `session` / `secure_session` / `user_id` |
| `codeStatus` 响应码 461/471 | 触发风控验证（`verifytype`/`verifyuuid`） |

轮询参数（来自 CLI 源码常量）：
- `POLL_INTERVAL_S = 2.0`（每 2 秒一次）
- `POLL_TIMEOUT_S = 240`（4 分钟超时）
- 连续 3 次轮询失败才 raise

登录成功后还需调 `POST /api/qrcode/userinfo` 完成 session 切换（`complete_qr_login`），最终关键 cookie：
`a1`（52 hex + 时间戳）、`webId`（32 hex）、`web_session`、`web_session_sec`、`id_token`、`xsecappid` 等。

#### 1.4 DOM 层面（deepwiki 文档，针对 www 站，creator 复用同套）

| 元素 | 选择器 |
|---|---|
| 登录按钮 | `.login-btn` / `//button[normalize-space(.)="登录"]` |
| 二维码图片 | `.login-container .qrcode-img`（首选）/ `.qr-img img`（fallback）|
| 登录成功指示 | `.user-info` / `//a[normalize-space(.)="我"]` |
| 登录 cookie | `xhs_sso`, `webId`, `xsec_token` |

> 注：creator 端 DOM 选择器可能微调，但**走 API 拦截路径不依赖这些选择器**，仅作 fallback。

### 2. 两条实现路径对比

#### 路径 A：容器内 headed Chrome + Xvfb 虚拟显示

- **做法**：装 `xvfb`，`Xvfb :99 -screen 0 1280x720x24 &`，`export DISPLAY=:99`，Playwright `launch_persistent_context(headless=False)`，`page.goto(login_url)`，然后 `page.locator('.qrcode-img').screenshot()` 截二维码元素图推前端（base64）。
- **优点**：复刻现有 CLI login 逻辑（`backend/cli/main.py:546` 的 `launch_persistent_context(headless=False)`），只多一层 Xvfb；二维码是"真"页面元素截图，所见即所得；登录态直接写 `user_data_dir` profile，与现有 `chrome_launcher` 的 CDP 常驻 Chrome 复用 profile 完全一致。
- **缺点**：
  - 需在 backend 容器装 `xvfb`（Dockerfile 加 `RUN apt-get install -y xvfb`，镜像变大）。
  - 依赖二维码 DOM 选择器（`.qrcode-img`），xhs 改版会断。
  - 截图是位图，前端无法重绘/缩放，只能原样显示。
  - headed Chrome 资源占用比 headless 高。
  - `--disable-blink-features=AutomationControlled` 在 headed 下仍可能被 xhs shield 识别（现有 publisher 用 playwright-stealth 注入反检测，见 `backend/services/xhs_publisher.py:139`）。

#### 路径 B：headless Chrome + 截二维码元素

- **做法**：`launch_persistent_context(headless=True)`（或 `--headless=new`），`page.goto(login_url)`，等 `.qrcode-img` 出现，`element.screenshot()` 推前端。
- **可行性问题**：headless 下 xhs 前端 JS **是否正常发起 `qrcode/create` 并渲染二维码**？理论上 headless Chrome 能跑 Vue SPA + axios，二维码 canvas 应能渲染。但 xhs shield 对 headless 检测更严（`navigator.webdriver`、CDP 特征），可能直接拦登录页或返回风控 461/471。现有 publisher 跑 headless 走 `connect_over_cdp` 连**真实 Chrome**（非 playwright 自带 chromium），就是为了规避这点（`xhs_publisher.py:103-108`）。
- **登录态检测**：轮询 `qrcode/status` 或监听 page URL 跳转（登录成功 creator 跳 `/publish/publish` 或 `/`）。
- **缺点**：同样依赖 DOM 选择器；headless 被拦风险高。

#### 路径 B'（推荐）：headless Chrome + 拦截 qrcode/create 响应 + 前端自渲染

- **做法**：
  1. 后端起 headless Chrome（playwright `launch_persistent_context(headless=True, user_data_dir=<account profile>)`，带 `--disable-blink-features=AutomationControlled`，必要时注 playwright-stealth）。
  2. `page.on("response", handler)` 注册监听器，匹配 `qrcode/create` 的 POST 响应，解析 JSON envelope 取 `data.url` / `data.qr_id` / `data.code`。
  3. `page.goto("https://creator.xiaohongshu.com/login")`，等 `qrcode/create` 响应到达。
  4. 把 `url`（二维码编码的 URL 字符串）经 SSE/WebSocket 推前端；前端用 `qrcode` npm 库自己画二维码（矢量、可缩放、不依赖截图）。
  5. 登录态感知二选一：
     - **(a) 让 headless 页面自己轮询**：`page.on("response")` 同时匹配 `qrcode/status` 的 GET 响应，读 `codeStatus`，确认后取 `login_info`，推状态给前端；登录态 cookie 已写 `user_data_dir`，关闭 headless Chrome 即可，常驻 CDP Chrome 复用。
     - **(b) 后端直接调 status 接口**：拿 `qr_id`/`code` 后后端用 httpx 直调 `qrcode/status`（需带同 `a1`/`webId` cookie + xhs 签名头，签名算法见 xhs API 客户端实现，较复杂）。**推荐 (a)**，让 headless 页面当"代理"，省去签名实现。
- **优点**：
  - 不依赖二维码 DOM 选择器，只依赖 XHR 接口路径（更稳定）。
  - 前端拿 `url` 自渲染二维码，矢量清晰、可调尺寸。
  - 不需 Xvfb（headless 无需 DISPLAY）。
  - 登录态写 `user_data_dir`，与现有 `chrome_launcher` CDP 多 profile 架构无缝衔接（profile 路径即 `account.chrome_profile_path`）。
  - 状态轮询让 headless 页做，绕开 xhs API 签名复杂度。
- **缺点/风险**：
  - headless 仍可能被 xhs shield 拦。**缓解**：用真实 Chrome 二进制（非 playwright bundled chromium）+ `--disable-blink-features=AutomationControlled` + playwright-stealth；若仍被拦，降级路径 A（Xvfb + headed）。
  - 需处理 `qrcode/create` 响应的 envelope（`{success, data}`）和 461/471 风控分支。
  - profile 锁竞争：现有 `chrome_launcher` 已用 pidfile + port probe 防多开（`chrome_launcher.py:320`），login 流程需复用同套锁逻辑，避免 login Chrome 与常驻 CDP Chrome 抢同一 `user_data_dir`。

### 3. 业界类似项目模式

| 项目 | 做法 |
|---|---|
| `a-RunShine/sunshine-skills` xhs_cli | **双后端**：(1) Camoufox（headless=False 真实浏览器）打开登录页，`page.on("response")` 拦截 `qrcode/create` 取 `url`，用 `qrcode` 库在终端画二维码；`page.expect_response` 等 `qrcode/status` 完成后导出 cookie。(2) 纯 HTTP：`httpx` 直调 `qrcode/create` + `qrcode/status`，需自己生成 `a1`/`webId` cookie + xhs 签名。**两路都拿 `url` 自渲染，不截图**。 |
| `luyike221/xiaohongshu-mcp-python` LoginManager | Playwright 打开登录页，`page.locator('.login-container .qrcode-img')` 定位二维码元素，`wait_for_login()` 轮询登录状态（用 `check_login_status()` 多层检测：登录按钮存在性 / mask 层 / user-info 元素 / cookie 存在性）。**走 DOM 截图 + 状态轮询**。配置 `QR_CODE_URL=/api/sns/web/v1/login/qrcode/create`、`QR_STATUS_URL=/api/sns/web/v1/login/qrcode/status`。 |
| apifox 第三方文档 `s.apifox.cn/.../api-139011476` | 暴露 creator 侧 `POST /login/get_login_qrcode`（body `{guid}`），标记"开发中"——是第三方 API 聚合器封装，非官方公开 API，**不可直接依赖**。官方接口仍是 `/api/sns/web/v1/login/qrcode/create`。 |
| 自媒体多账号管理工具通用模式 | 后端跑 headless/headed 浏览器实例，二维码图（截图或 base64）经 WebSocket/SSE 推前端，前端展示；用户手机扫码后后端检测到 cookie/URL 跳转，存 cookie 或 profile，关闭浏览器。登录态检测三选一：URL 跳转 / 特定 cookie 出现 / status 接口轮询。 |

**共识**：业界主流是**拦截 `qrcode/create` 拿 `url` 让前端自渲染**（更稳定，不依赖 DOM），而非截图二维码元素。截图路径是 fallback。

### 4. 推荐方案及理由

**推荐路径 B'（headless Chrome + 拦截 qrcode/create 响应 + 前端自渲染二维码 + headless 页代轮询 status）**，理由：

1. **不依赖 DOM 选择器**：xhs 前端改版二维码容器 class 不会断（只依赖 `/api/sns/web/v1/login/qrcode/create` 接口路径，接口比 DOM 稳定）。
2. **不需 Xvfb**：headless 无 DISPLAY 依赖，backend 容器零改动（不必加 xvfb 层）。
3. **前端矢量二维码**：拿 `url` 用 `qrcode` npm 库画，清晰可缩放，UX 优于位图截图。
4. **复用现有架构**：`user_data_dir = account.chrome_profile_path`，登录态写入后常驻 CDP Chrome（`chrome_launcher` 管理）直接复用，与 `feat/cdp-multi-profile` 分支的多 profile 设计一致。
5. **绕开 xhs API 签名**：让 headless 页面自己轮询 `qrcode/status`（页面已带正确 cookie + 签名头），后端只透传状态，不必实现 xhs 的 `x-s`/`x-t` 签名算法。
6. **降级路径清晰**：若 headless 被 shield 拦（461/471 或页面不发 `qrcode/create`），降级路径 A（装 Xvfb + headed + playwright-stealth），逻辑只换 `headless=False` + DISPLAY。

**实现要点**：
- 复用 `backend/cli/main.py:546` 的 `launch_persistent_context` 模式，改 `headless=True`，加 playwright-stealth（参照 `xhs_publisher.py:139` 的 `Stealth().apply_stealth_async(context)`）。
- `page.on("response", handler)` 匹配 `qrcode/create`（POST）取 `data.url`；匹配 `qrcode/status`（GET）取 `data.codeStatus`。
- 状态经现有 SSE/WebSocket（`backend/realtime/`）推前端，或新增 `/api/login/qr-stream/{account_id}` SSE 端点。
- profile 锁复用 `chrome_launcher` 的 pidfile + port probe 逻辑，确保 login Chrome 不与常驻 CDP Chrome 抢同 profile。
- 登录成功后 `context.cookies()` 导出 `a1`/`webId`/`web_session`/`web_session_sec`，存 DB 或直接靠 `user_data_dir` 持久化（现有设计靠 profile，无需单独存 cookie）。

## External References

- [creator 登录页 HTML](https://creator.xiaohongshu.com/login) — Vue SPA shell，JS bundle 在 `fe-static.xhscdn.com/formula-static/ugc/public/resource/js/`，确认复用 www 站登录接口
- [a-RunShine/sunshine-skills xhs_cli/qr_login.py](https://github.com/a-RunShine/sunshine-skills/blob/master/xiaohongshu-cli/xhs_cli/qr_login.py) — 双后端（Camoufox 浏览器拦截 + 纯 HTTP）完整实现，`qrcode/create` 响应 `{qr_id, code, url}`，`qrcode/status` 返回 `codeStatus` 0/1/2
- [luyike221/xiaohongshu-mcp-python LoginManager](https://deepwiki.com/luyike221/xiaohongshu-mcp-python/7.2-loginmanager-qr-code-authentication) — DOM 截图 + 状态轮询方案，选择器 `.login-container .qrcode-img` / `.qr-img img`，登录成功指示 `.user-info`
- [apifox creator API 文档](https://s.apifox.cn/apidoc/shared-c41cf343-9eca-4060-868e-76b159406a8b/api-139011476) — 第三方聚合的 `POST /login/get_login_qrcode`（body `{guid}`），标记"开发中"，非官方接口，仅供参考
- [Playwright element screenshot](https://playwright.dev/docs/screenshots) — `page.locator('.header').screenshot({path})` 单元素截图 API

## Related Internal Code

- `backend/cli/main.py:452-584` — 现有 CLI `login` 命令：`launch_persistent_context(headless=False)` 打开 creator 登录页，`page.wait_for_event("close")` 等用户关窗，登录态写 `account.chrome_profile_path`
- `backend/services/chrome_launcher.py:241-258` — `_build_launch_cmd`：`--user-data-dir=<profile> --remote-debugging-port=<port>` + `_DEFAULT_FLAGS`（`--no-first-run`/`--disable-dev-shm-usage`/`--remote-debugging-address=0.0.0.0`），`--headless=new` 可选
- `backend/services/xhs_publisher.py:79-150` — publisher 的 Chrome 启动：`connect_over_cdp`（连常驻真实 Chrome）或 `launch_persistent_context(headless=self.headless)` + playwright-stealth `Stealth().apply_stealth_async(context)`
- `backend/services/xhs_api.py:17` — `CREATOR_URL = "https://creator.xiaohongshu.com"`
- `backend/services/xhs_publisher.py:73-74` — `CREATOR_URL = ".../publish/publish"`、`LOGIN_URL = "https://creator.xiaohongshu.com/login"`
- `backend/realtime/` — 现有 SSE/WebSocket 推送基础设施，可复用于推二维码 url + 登录状态

## Caveats / Not Found

- **headless 下 xhs shield 是否放行登录页未实测**：调研基于代码静态分析与业界项目，未在容器内实跑 headless Chrome 验证 `qrcode/create` 是否正常发出。若被拦（461/471 或无 XHR），需降级路径 A（Xvfb + headed + stealth）。建议实现阶段先做 5 分钟 spike：headless 打开登录页，`page.on("response")` 看 `qrcode/create` 是否到达。
- **creator 端 DOM 选择器未实测**：deepwiki 的 `.login-container .qrcode-img` / `.qr-img img` 针对 www 站，creator 端可能微调。走路径 B'（拦截 API）不依赖选择器，仅作 fallback 时才需确认。
- **xhs API 签名算法**：纯 HTTP 直调 `qrcode/create`/`status` 需 `x-s`/`x-t`/`x-s-common` 签名头（xhs shield 要求），sunshine-skills 的 `XhsClient` 实现了签名但本仓库未实现。路径 B'(a) 让 headless 页代发请求可绕开，但若要后端独立轮询 status（路径 B'(b)）则需移植签名——不推荐。
- **`qrcode/create` 的完整 envelope 字段**：调研确认 `data` 含 `qr_id`/`code`/`url`，但未确认是否有 `expire_seconds`（二维码过期时间）等附加字段。实现时按实际响应字段处理，建议加 30s~60s 过期后重新 `goto` 登录页刷新二维码。
- **多账号并发登录**：现有 `chrome_launcher` 每账号独立 profile + cdp_port，login 流程若多账号并发扫码，需确保每账号 headless Chrome 用独立 `user_data_dir` + 独立临时 remote-debugging-port（避免端口冲突），登录完成后关闭再由 `chrome_launcher` 起常驻 CDP Chrome。

---

## Spike 验证结果（2026-07-03，容器内 headless 实测）

### creator.xiaohongshu.com/login
- **无二维码 UI**。页面只有"短信登录"+"密码登录"tab，无可点的二维码/扫码入口。
- 不触发 `qrcode/create` XHR。研究 agent 推断的 creator 复用 www 接口——接口存在但 creator 登录页 UI 未暴露二维码 tab。
- → creator 页走二维码方案不可行（无 UI 触发点）。

### www.xiaohongshu.com/explore
- 进入即弹登录浮层，**自动触发 `POST /api/sns/web/v1/login/qrcode/create`，返回 200**。
- 响应：`{data:{qr_id, code, url, multi_flag}, code:0, success:true}`
- `data.url` 是二维码编码内容（`https://www.xiaohongshu.com/mobile/login?qrId=...`），前端用 `qrcode` JS 库渲染矢量二维码即可，无需截图。
- headless Chrome（无 Xvfb）下未被 shield 拦截，`qrcode/create` 正常 200。
- → **路径 B' 可行**：headless Chrome 开 www 登录页 → `page.on("response")` 拦截 `qrcode/create` 取 `url` 推前端 → 轮询 `qrcode/status` 的 `codeStatus`（0/1/2）。

### 待实现阶段验证
- www 扫码登录态 cookie（`a1`/`webId`/`web_session`/`web_session_sec`）域是 `.xiaohongshu.com`，creator.xiaohongshu.com 是子域→**理论上同根域 cookie 可共享**，creator 发布应能复用。需实测确认。
- `qrcode/status` 轮询节奏与 `codeStatus` 语义待实测（研究为 0=待扫/1=已扫/2=已确认）。
- profile 持久化：www 登录态写入 `account.chrome_profile_path`，launcher 常驻 CDP Chrome 复用——需确认 www cookie 与 creator cookie 都进同一 user-data-dir。

---

## 部署后实测（2026-07-03）：persistent_context 被 shield 拦

部署 PR1+PR2 后真机实测 `POST /accounts/{id}/login/qr`：
- endpoint 跑通（账号校验、profile 创建、Chrome 启动都 OK）
- 但 30s 未收到 qrcode/create → 503

复现对比（容器内）：
- `launch` + `new_context`（spike 原方式）：**成功**，qrcode/create 200，8s 内拿到 qr url
- `launch_persistent_context`（service 方式）：**被拦**，页面标题"安全限制"，goto 超时
- `launch_persistent_context` + 设 UA + locale：goto 30s 超时

### 根因
`launch_persistent_context` 触发 xhs shield 反自动化拦截。可能因素：
- 空 user_data_dir 首启指纹异常
- persistent context 模式 CDP 暴露特征
- 容器未装 playwright-stealth（pyproject 未声明），service fallback 手动 webdriver 隐藏不够

### 待验证解法
1. **装 playwright-stealth**（加 [browser] extra + 重新部署）——stealth 完整反检测或可绕过 persistent_context 拦截。未验证。
2. **改 service 用 launch+new_context**：登录成功后 `context.cookies()` 导出 cookie，写入 persistent profile（另一 persistent_context `add_cookies`）或存账号 credentials（XHS_COOKIE）。cookie 迁移性待验证。
3. **persistent_context 预热**：先访问非 xhs 页暖 fingerprint。未验证。

### 现状
- launch+new_context 拿 qr 可行（spike 多次验证）
- persistent_context 持久化登录态被拦——service 当前架构阻塞
- cookie 跨 context 迁移未验证
