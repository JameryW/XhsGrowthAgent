# XHS 发布页 DOM 回归探针

## Goal

XHS 发布页 DOM 会变，发布器选择器失效是 silent failure（wait_for_function 60s 超时才发现）。建 Playwright DOM 探针：只验上传页结构和输入框存在，不点发布。作为发布器（xhs_publisher.py）改动的必跑检查，DOM 漂移早发现。

## What I already know

- `backend/services/xhs_publisher.py` 发布页选择器（来自代码）：
  - 图文 tab：`div.creator-tab`（innerText 含"上传图文"），`offsetParent !== null`
  - 图片上传 input：`input[type=file][accept*=jpg]`, `input[type=file][accept*=png]`, `input[type=file][multiple]`
  - 标题：`input[placeholder*=标题]`, `.title-input`, `input.d-text[type=text]`
  - 正文：`.tiptap.ProseMirror`, `[contenteditable=true]`, `textarea[placeholder*=正文]`, `.content-input`
  - 发布按钮：`.publish-page-publish-btn button.bg-red`, `xhs-publish-btn`
  - 就绪选择器 `_PUBLISH_READY_SELECTORS`（`backend/services/xhs_publisher.py` 顶部）
- 登录态：cookie 注入或 CDP（见 [[xhs-scan-login-qr-www-not-creator]] memory：扫码走 www，cookie 跨子域复用 creator 待实测）
- 发布页 URL：`creator.xiaohongshu.com/publish/publish`
- 现有发布测试 `tests/unit/services/test_xhs_publisher.py` 用 AsyncMock Page，不碰真实 DOM
- pyproject 有 `[browser]` extra（playwright），CI test job 不跑 browser（需真实网络+cookie）

## Requirements

- 探针脚本：连真实 Chrome（CDP 优先，fallback launch），导航到 creator 发布页，断言关键选择器存在：
  - 图文 tab 容器 `div.creator-tab`
  - 图片上传 input（accept 含 jpg/png 或 multiple）
  - 标题输入框
  - 正文编辑区（contenteditable 或 textarea）
  - 发布按钮容器（`.publish-page-publish-btn` 或 `xhs-publish-btn`）
- **不点发布、不上传图片、不填内容**——纯结构验证
- 输出：每个选择器 pass/fail + DOM 快照（HTML 片段）便于诊断漂移
- 退出码：任一关键选择器 fail → 非 0
- 运行方式：独立脚本（`scripts/xhs_dom_probe.py`），不在常规 pytest 跑（需网络+登录态）；可选 pytest marker `@pytest.mark.browser` 供手动触发
- 配置：CDP endpoint / cookie 从环境变量读（复用 `XHS_CDP_ENDPOINT`、`XHS_COOKIE` 或 Settings）

## Acceptance Criteria

- [ ] `scripts/xhs_dom_probe.py` 能跑（需 CDP/cookie 环境，无环境时 skip 并提示）
- [ ] 断言上述 5 类关键选择器，逐个报告 pass/fail
- [ ] fail 时打印实际页面 HTML 片段辅助诊断
- [ ] 退出码反映 pass/fail
- [ ] 不触发任何发布/上传/填写动作
- [ ] 有单元测试覆盖探针的断言逻辑（用 mock page，不依赖网络）

## Out of Scope

- 真实发布端到端测试（已有 xhs_publisher 单测 + 手动验证）
- 定时巡检/cron（先手动/CI 触发）
- 视觉回归（截图对比）—— 只结构断言
- 视频上传 tab 验证（只验图文路径）

## Technical Approach

- 脚本入口 `scripts/xhs_dom_probe.py`：argparse（--cdp / --cookie / --headless），复用 `XHSPublisher._ensure_browser`/`_ensure_page`/`_goto_creator_page` 拿 page
- 断言函数 `probe_publish_page(page) -> list[Finding]`：每个选择器 try query_selector/locator.count，记 pass/fail + 失败时 `await page.content()` 截片段
- 单测 `tests/unit/services/test_dom_probe.py`：mock page，验证断言逻辑（选择器命中=pass，miss=fail+HTML 片段）
- pytest marker：探针主函数可 `@pytest.mark.browser` 包，conftest 默认 skip browser mark（`-m "not browser"`）

## Implementation Plan

- PR（本 task）：`scripts/xhs_dom_probe.py` + `backend/services/xhs_dom_probe.py`（断言逻辑抽出来可测）+ `tests/unit/services/test_dom_probe.py` + pytest marker skip browser

## Technical Notes

- 文件：`scripts/xhs_dom_probe.py`、`backend/services/xhs_dom_probe.py`、`tests/unit/services/test_dom_probe.py`、`tests/conftest.py`（browser marker skip）、`pyproject.toml`（marker 注册）
- 约束：不点发布/不上传/不填内容；无 CDP/cookie 环境 graceful skip；不依赖网络的单测覆盖断言逻辑
- 风险：CDP/cookie 环境本地可能没有——脚本要 graceful skip，CI 也跑不动（只跑单测部分）
