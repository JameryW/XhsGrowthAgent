# PRD: 扫码登录 Xvfb headed 降级——绕过 471 风控

## 背景

B 段实测暴露：headless Chrome 扫码登录，手机确认后 `qrcode/status` 返回 HTTP 471（空 data，无 code_status=2）。471 = xhs 安全验证。手机端确认无验证提示 → 471 是 headless Chrome 被风控识别（非账号问题）。

同一实测已修两个真 bug（本 task 前置）：
1. `code_status` 字段名（xhs www 返回下划线，原代码解析驼峰 `codeStatus` → 永远 waiting）。
2. headless 下 xhs 前端 JS 不自动轮询 status → 后端改 `page.evaluate(fetch)` 主动轮询。

修后 scanned 正确检测。但 471 阻止 confirmed。

## 决策

降级路径 A（research 第 80-88 行）：装 Xvfb + `launch_persistent_context(headless=False)`。headed Chrome 风控指纹弱于 headless，避 471。

## 需求

### R1: Dockerfile 装 Xvfb
apt 层加 `xvfb`。

### R2: entrypoint 启 Xvfb + 设 DISPLAY
`scripts/container-entrypoint.sh` 启 `Xvfb :99 -screen 0 1280x720x24`，`export DISPLAY=:99`，再 exec 主进程。

### R3: service 改 headed
`backend/services/xhs_login.py` `launch_persistent_context(headless=False)`。headless 模式保留为 env 可选（`XHS_LOGIN_HEADLESS=1` 强制 headless，默认 headed）——便于回退验证。

### R4: 主动轮询保留
R3 headed 后 xhs 前端 JS 可能自动轮询 status（headed 下 canvas 渲染正常）。但主动 `page.evaluate(fetch)` 轮询保留作兜底——无害（页面 JS 轮询 + 后端轮询都更新 _code_status，幂等）。

## 验收

- 重新部署后，`POST /accounts/{id}/login/qr` 用 headed Chrome。
- 手机扫码确认后 `code_status=2`（非 471）。
- profile cookie 含有效 `web_session`（www 首页判定已登录）。
- 既有 `test_xhs_login.py` 单测仍绿（headless 默认值改动需同步 fixture）。

## 不做

- profile 共享挂载（容器内 profile vs host CDP Chrome）——下一 task。
- creator 跨子域复用验证——登录成功后再验。
