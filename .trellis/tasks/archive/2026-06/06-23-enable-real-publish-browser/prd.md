# 打通真实发布（浏览器路径）

## Goal

让审批通过选「真实发布」时能真正把笔记发到小红书平台，而非 mock。
当前 `XHS_USE_BROWSER=false` + 容器无 chromium，publisher.py:36 强制走 mock。

## What I already know

- publisher 链路：`backend/agents/publisher.py` → `use_browser=False` 时 mock（:36）；
  `use_browser=True` 时走 `XHSClient(use_browser=True)` → playwright chromium
- cookie 来源 OK：审批传 `account_id`，publisher 走 `get_account_cookie()` 从 DB 拿（账号 JameryW 的 XHS_COOKIE 已 set）。不依赖 env `XHS_COOKIE`
- 三处缺口：
  1. `XHS_USE_BROWSER` 未注入容器（deploy.sh 后端启动段无此 -e）
  2. Dockerfile `pip install .` 未装 `[browser]` extra（pyproject 有 `browser=["playwright>=1.49"]`）
  3. 容器无 chromium 二进制（未 `playwright install chromium` + 系统依赖）
- `XHS_USE_BROWSER` 不在 system_config `SYSTEM_KEYS` 白名单 → 纯走 env，改 .env + deploy.sh -e 即可生效（不受 DB 覆盖，区别于 XHS_EMBED_MODEL）
- settings: `XHSPlatformSettings.use_browser: bool = False`（env_prefix XHS_，读 XHS_USE_BROWSER）
- headless 默认 True（settings.py:41），服务器无头合适

## Requirements

- Dockerfile 装 playwright python 包 + chromium 浏览器 + 系统依赖
- deploy.sh 后端启动段注入 `XHS_USE_BROWSER`
- `.env` 设 `XHS_USE_BROWSER=true`
- 重建镜像 + 重新部署
- 验证：health 显示 use_browser=true；审批选真实发布能触发真实浏览器发布（cookie 失效则返回 auth_failed 而非 mock）

## Acceptance Criteria

- [ ] 容器内 `python -c "from playwright.async_api import async_playwright"` 成功
- [ ] 容器内 chromium 可启动（`playwright install chromium` 已装）
- [ ] `/api/system/health` 的 `xhs_platform.use_browser = true`
- [ ] 审批选真实发布 → 后端走 XHSClient 浏览器路径（日志出现 playwright 操作），非 mock_published
- [ ] cookie 失效时返回 auth_failed（而非静默 mock）

## Definition of Done

- 镜像重建成功，部署通过 health 检查
- Dockerfile 改动不破坏现有功能（embedding seed、entrypoint 等不受影响）
- deploy.sh 向后兼容（XHS_USE_BROWSER 缺省仍可 mock 模式运行）

## Decided

- chromium 安装：`pip install ".[browser]"` + `playwright install --with-deps chromium`（装进镜像层，接受体积增大）
- headless 保持 True（settings 默认，无需额外配置）

## Out of Scope

- 浏览器反检测增强（当前已有 disable-blink-features）
- 发布失败的重试/告警机制
- cookie 自动续期

## Technical Notes

- 改动文件：`Dockerfile`、`scripts/deploy.sh`、`.env`
- pyproject 已声明 browser extra，Dockerfile 改 `pip install ".[browser]"`
- chromium 装到镜像层（非运行时下载），避免每次启动联网
- 参考记忆 [[deploy-use-script]]、[[container-env-completeness]]、[[system-config-overrides-environ]]
