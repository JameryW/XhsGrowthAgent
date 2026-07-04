# PRD: 扫码登录改 connect_over_cdp 连 host 真实 Chrome——避 471 风控

## 背景

B 段实测：playwright bundled chromium（不论 headless/headed+Xvfb）扫码登录，确认后 `qrcode/status` 返回 471 风控，登录态未建立。publisher 用 `connect_over_cdp` 连 host 真实 Chrome 正是为规避此问题（真实 Chrome 指纹≠bundled chromium）。扫码登录应复用同套。

已修前置（已部署）：
- `code_status` 字段名 bug（xhs 返回下划线）。
- headless 下 status 不轮询 → 后端主动 `page.evaluate(fetch)` 轮询。
- `run_publish` CDP 模式跳 cookie 必需检查。

## 决策

扫码 service 从 `launch_persistent_context`（playwright bundled chromium）改为 `connect_over_cdp`（host 真实 Chrome，launcher 管理）。真实 Chrome 不被 shield 识别 → 避 471。同 profile 后续 CDP 发布复用 → profile 共享 gap 自然消解（都在 host）。

## 需求

### R1: launcher host DB 连修复
`backend/models/router.py:19` `load_dotenv(override=True)` import 时用 .env 的 POSTGRES_URI（postgres-xhs 容器网络名）覆盖 os.environ，导致 host launcher 连不上 DB。
- 修：chrome-profiles.sh（或 launcher CLI）host 跑时，强制 POSTGRES_URI 指向 localhost:5432。具体：launcher CLI 启动时若检测 host（非容器），覆盖 POSTGRES_URI 为 localhost，或在 router load_dotenv 后重设。
- 备选：router `override=True` 改 `override=False`（不覆盖已设的 os.environ）——让 shell export 生效。评估全局影响。

### R2: host Chrome 启动 + 绑 0.0.0.0
launcher `start_all` 对 active+有 profile 绑定的账号启 host Chrome（`--remote-debugging-address=0.0.0.0`）。需确认 host Chrome 真绑 0.0.0.0（之前手动启绑了 127.0.0.1，参数未生效——launcher 是否成功待验）。

### R3: profile 路径统一 host
账号 `chrome_profile_path` 用 host 路径（`/test/xhs/.chrome-profiles/<id>`）。host launcher + 容器 backend 都用此路径——但容器内不见 host 路径，需挂载 OR backend 不直接访问 profile 文件（connect_over_cdp 模式不需 profile 文件，只连 CDP endpoint）。
- connect_over_cdp 模式下 backend 不碰 profile 文件 → 无需挂载。profile 路径仅 host launcher 用。

### R4: 扫码 service 改 connect_over_cdp
`XhsLoginSession`：
- 不再 `launch_persistent_context(user_data_dir=profile)`。
- 改 `connect_over_cdp(account_cdp_endpoint)` 连 host Chrome。
- 在 host Chrome 的 page 上 goto explore + 拦 qrcode/create + 主动轮询 status（page.evaluate fetch 保留）。
- 不关 Chrome（launcher 管 lifecycle），只 close 自己的 page/context connection。

### R5: 扫码前 ensure Chrome
扫码 start 时，若 host Chrome 未启，提示用户先跑 `chrome-profiles.sh start`，或 backend 触发 ensure。当前假设用户先启（文档说明）。

## 验收

- host 跑 `chrome-profiles.sh start` 启麦当劳账号 Chrome（绑 0.0.0.0:9224）。
- 容器 backend `connect_over_cdp(host:9224)` 通。
- 扫码确认后 `code_status=2`（非 471）。
- profile cookie 含有效 web_session，www 首页判定已登录。
- 既有 `test_xhs_login.py` 单测同步改（mock connect_over_cdp 替代 launch_persistent_context）。

## 不做

- creator 跨子域复用验证（登录成功后再验，可能需 www→creator SSO 跳转）。
- Xvfb 回退（connect_over_cdp 模式不需容器内 Chrome，Xvfb 改动可回退——本 task 评估后清理）。
