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

---

## PoC 失败结论（2026-07-04）— 推翻原 R2/R3 决策

原决策"Chrome `--remote-debugging-address=0.0.0.0` 绑 0.0.0.0"已被实测推翻。socat/反代路也死。

### 实测事实

- Chrome 144（headless + headed）**强制 CDP 绑 127.0.0.1**，`--remote-debugging-address=0.0.0.0` 完全失效（headless + Xvfb headed 都验过）。
- `--remote-allow-origins=*` 只覆盖 Origin header，**不覆盖 Host header 校验**。容器经 socat 转发请求 Host=`host.containers.internal:<port>` ≠ Chrome 绑的 127.0.0.1 → HTTP 500。
- HTTP 反代重写 Host + body（nginx `sub_filter` 改 ws url）→ `/json/version` 200，ws url 重写正确，WS 握手 101 通（含 permessage-deflate 协商）。
- **WS frame 阶段卡死**：nginx `<ws connected>` 后无 frame 流（tcpdump 抓 9229 无 PSH frame）；python 自写 TCP 代理 WS 连接都没建。
- publisher 用同套 `connect_over_cdp(host.containers.internal:<port>)`，**同样会坏**——现有 publisher CDP 链路大概率从没真成功过。
- **关键修正**：playwright 1.60 `connect_over_cdp` **host 直连** 127.0.0.1:19225（不经任何反代）同样 `<ws connected>` 后卡死。问题**不在反代**，在 playwright 1.60 ↔ Chrome 144 CDP WS 协议不兼容——手动 WS 握手 101 通，但 playwright 发的首个 CDP frame Chrome 不回。CDP-aware 代理（方案 2）也救不了：代理透传 frame 照样卡。

### 推翻

- ~~R2: host Chrome `--remote-debugging-address=0.0.0.0` 绑 0.0.0.0~~ — Chrome 144 忽略该 flag。
- ~~socat 纯 TCP 转发~~ — HTTP 500（Host 校验）。
- ~~nginx/python 反代重写 Host + body~~ — WS frame 透传不工作（playwright CDP WS 密集双向 frame 与通用 HTTP 反代不兼容）。

### 仍待验证的可行路（brainstorm 候选）

1. **降 Chrome 到 143** — `<144` 版本 `--remote-debugging-address=0.0.0.0` 生效，无反代，容器直连。最省。需验证 143 真绑 0.0.0.0 + host 可装。
2. **CDP-aware 代理工具** — 自写理解 CDP WS 的代理，或 browserless chrome-proxy 类现成工具。重。**注：已证 playwright↔Chrome 144 协议不兼容，代理透传 frame 照样卡，此路大概率死。**
3. **backend 跑 host 非 container** — 架构大改，publisher/扫码 service 都改 host 跑。host 直连也卡，此路同死，除非配合方案 4。
4. **升 playwright 或降 Chrome 对齐 protocol** — 实测 playwright 1.60 ↔ Chrome 144 CDP WS 协议不兼容（host 直连也卡）。升 playwright 到支持 Chrome 144 的版本，或降 Chrome 到 playwright 1.60 支持的版本，可能直接解决。需查 playwright↔Chrome 版本兼容矩阵。

## Open Questions（重新 brainstorm）

- Q1: playwright 1.60 支持的 Chrome 版本上限？Chrome 144 是否超出？（research-first）
- Q2: 升 playwright 版本（容器内）是否解决 CDP WS 卡？还是降 Chrome 对齐 playwright 更省？
- Q3: Chrome 143 + `--remote-debugging-address=0.0.0.0` 是否生效（若降 Chrome 143 同时解决协议兼容 + loopback，一箭双雕）？

