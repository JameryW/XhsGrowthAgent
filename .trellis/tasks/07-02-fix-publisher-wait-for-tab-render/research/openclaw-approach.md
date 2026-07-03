# Research: openclaw / 开源小红书发布工具的反爬绕过方案

- **Query**: 调研 openclaw（开源小红书工具/类似项目）的实现，重点看它怎么解决"小红书发布被反爬拦截"的问题
- **Scope**: external（GitHub 仓库源码 + README）+ internal（对比本地 XhsGrowthAgent publisher）
- **Date**: 2026-07-03

## TL;DR（核心结论）

1. **"openclaw" 本身不是一个仓库**，而是一个 AI agent 运行时/平台（类似 Claude Code / Codex），多个 "Skill" 仓库为其编写。最相关的发布实现是 **`white0dew/XiaohongshuSkills`（★3114）**，其 README 第一行就写"支持 OpenClaw、Codex、CC 等"。
2. **它的反爬绕过核心只有一句话：不启动带 stealth 的 playwright 浏览器，而是连接一个用户手动扫码登录过的真实 Chrome 实例（CDP `--remote-debugging-port` + 持久 `--user-data-dir`）。**
3. 发布提交不是用 JS `.click()`（XHS 的 Vue/closed-shadow DOM 会吞掉 JS click），而是用 **CDP `Input.dispatchMouseEvent` 在按钮中心坐标发真实 `mousePressed`+`mouseReleased`**。
4. **不逆向 XHS 的 `x-s`/`x-t`/`x-s-common`/`shield` 签名算法，不直接调 `note/create` API**。全流程走浏览器真实交互，让 XHS 自家 JS 自己生成签名、自己发提交请求。
5. 登录态 = Chrome profile 里的真实 cookie/storage（扫码登录一次后持久化），不是手动 set cookie 字符串。
6. 人感模拟靠：随机 timing jitter（`_sleep(base, jitter)`）、逐字 type 带 random delay、headless 用 `--headless=new`（新版 headless，指纹接近有头）。

这与 XhsGrowthAgent 当前方案（playwright `launch` 新浏览器 + stealth init script + 手动 `add_cookies` cookie 字符串）**根本不同**——正是后者触发 XHS 的 shield/sec 深度拦截（playwright 浏览器指纹 + cookie 注入态 = 典型自动化特征）。

---

## Findings

### 1. openclaw 是什么

- **openclaw = AI agent 运行时平台**（类似 Claude Code、Codex 的"Skill"宿主），不是单一发布工具。
- 多个仓库为其编写小红书 Skill，GitHub 搜索 `openclaw xiaohongshu` 命中 124 个仓库，其中发布相关且星数最高的：

| 仓库 | ★ | 角色 | 方案 |
|---|---|---|---|
| `white0dew/XiaohongshuSkills` | 3114 | **主力发布 Skill**，README 首提 OpenClaw | CDP 连真实 Chrome |
| `Xiangyu-Cas/xiaohongshu-ops-skill` | 2023 | 运营助手（选题/复盘/复刻） | 基于 openclaw |
| `BetaStreetOmnis/xhs_ai_publisher` | 2004 | PyQt 桌面 + FastAPI | （README 404，未深入） |
| `Youhai020616/xiaohongshu` | 23 | MCP + CDP 双引擎 | 同样 CDP 连真实 Chrome |
| `zangqilong198812/openclaw-xiaohongshu-publish-skill` | 5 | RedNote publish skill for openclaw | "User Chrome to publish" |
| `iamzifei/red-publisher-skill` | 9 | Claude Skill publish on Red | Python |

**本调研聚焦 `white0dew/XiaohongshuSkills`**——它是星数最高、README/源码最完整、且明确针对发布（写）场景的实现。其 `scripts/cdp_publish.py`（192KB）是核心。

### 2. 它的发布方案（逐条对照调研要点）

#### (a) 是否用 CDP 连接真实浏览器（connect_over_cdp）而非启动新浏览器？—— 是，且更进一步

它**不用 playwright**，直接用裸 `requests` + `websockets` 库跟 Chrome 的 CDP HTTP/WS 端点对话：

- `chrome_launcher.py` 用 `subprocess.Popen` 启动**真实系统 Chrome**（`get_chrome_path()` 找 `google-chrome`/`chrome.exe`），关键启动参数：

```python
cmd = [
    chrome_path,
    f"--remote-debugging-port={port}",        # CDP 端口（默认 9222）
    f"--user-data-dir={user_data_dir}",       # 持久 profile（登录态/指纹/缓存全在这）
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--disable-background-media-suspend",
]
if headless:
    cmd.append("--headless=new")              # 新版 headless，指纹≈有头
```

- `_get_targets()`：`GET http://127.0.0.1:9222/json` 拿所有 tab。
- `_find_or_create_tab()`：`PUT http://127.0.0.1:9222/json/new?<creator_url>` 新建 tab，取回 `webSocketDebuggerUrl`。
- `connect()`：`ws_client.connect(ws_url)` 连上 tab 的 WS。
- `_send(method, params)`：手写 CDP JSON-RPC over WS，`id` 递增匹配响应。

**关键差异**：playwright 的 `connect_over_cdp` 也能连真实 Chrome，但 XiaohongshuSkills 连 playwright 都不用——直接 CDP 原语，最贴近"真实用户"。

#### (b) 是否直接调 XHS 内部 API（note/create）？怎么生成签名？—— 否，完全不碰

全仓库源码 grep `x-s`/`x-t`/`x-s-common`/`xhsSign`/`getSign`/`encrypt`/`note/create`/`edith.xhs` —— **0 命中**（仅一处 `search/recommend` API 抓推荐词，非发布）。

它走的是"让 XHS 自己的 JS 发请求"：填好表单 → CDP 真实点击发布按钮 → XHS 前端 JS 自己算签名、自己 `fetch('/api/sns/web/v1/note/create')`。自动化只负责"像人一样操作 DOM"，签名/风控完全交给 XHS 自家运行时——这是它能绕过 shield/sec 的根本原因。

#### (c) 是否用浏览器扩展注入？—— 否

无扩展、无油猴脚本、无 init script 注入。唯一注入是 `Runtime.evaluate` 执行**查询/定位 DOM 的 JS**（拿 rect、点 tab、读 placeholder），不注入任何"伪装"代码。

#### (d) 是否逆向 XHS 的 shield/sec 签名算法？—— 否

同 (b)，零逆向。README 明确不提签名，只提"适配 2026 年 2-3 月创作者中心 DOM 改版"——维护的是**选择器**，不是签名。

#### (e) cookie/登录态怎么处理？—— Chrome profile 持久化 + 扫码登录

- 登录：`python cdp_publish.py login` → 弹出有头 Chrome 窗口 → 用户扫码 → 登录态写入 `--user-data-dir` 指定的 profile 目录（`account_manager.get_profile_dir(account)`，每账号隔离）。
- 后续发布：复用同一 profile，Chrome 启动即已登录，**不手动 set cookie 字符串**。
- 登录检测：`check_login` 看是否被重定向到 `/login`，结果本地缓存 12h（`LOGIN_CACHE_FILE`，`_get_cached_login_status`），减少反复跳转校验。
- 二维码导出：`get-login-qrcode` 返回 Base64，便于远程前端扫码。

这与 XhsGrowthAgent 的 `_set_cookies`（把 cookie 字符串 split 后 `context.add_cookies`）形成鲜明对比——后者是"裸 cookie 注入"，XHS shield 能识别这种无完整 storage/session 的注入态。

### 3. 关键代码片段（发布提交那步）

**点击发布按钮**（`cdp_publish.py:3978 _click_publish`）：

```python
def _click_publish(self, scheduled: bool = False):
    """Click the publish button using CDP mouse events."""
    self._sleep(ACTION_INTERVAL, minimum_seconds=0.25)
    self._wait_for_publish_button_ready(timeout_seconds=20.0)
    rect = self._get_publish_button_rect()          # JS 拿按钮 boundingRect
    if not rect:
        raise CDPError("Could not find publish button. ...")
    cx = rect["x"] + rect["width"] / 2
    cy = rect["y"] + rect["height"] / 2
    self._click_mouse(cx, cy)                        # CDP 真实鼠标事件
    self._sleep(5, minimum_seconds=2.0)
    note_link = self._evaluate("""...查 a[href*=explore] 或 24-hex noteId...""")
    return note_link
```

**底层 `_click_mouse`**（`cdp_publish.py:3926`）——这是绕过 closed shadow DOM 的关键：

```python
def _click_mouse(self, x: float, y: float):
    """Perform a real left-click via CDP at the given coordinates."""
    for event_type in ("mousePressed", "mouseReleased"):
        self._send("Input.dispatchMouseEvent", {
            "type": event_type,
            "x": float(x),
            "y": float(y),
            "button": "left",
            "clickCount": 1,
        })
        time.sleep(0.05)
```

注释点明动机（`_click_element_by_cdp` `cdp_publish.py:3944`）：

> Modern web frameworks (Vue/React) often ignore JS .click() calls.
> Dispatching real mouse events via CDP always works.

**对比 XhsGrowthAgent**（`backend/services/xhs_publisher.py:454 _click_publish`）：我们用 `page.mouse.click(box x+85%, y mid)`——也是坐标点击，但**在 playwright 启动的、被 shield 标记的浏览器里**，所以 XHS 前端 JS 拿到点击事件后**拒绝发 note/create**（90 个动态请求 0 个提交）。问题不在点击方式，在浏览器本身不被信任。

**文件上传**用 CDP `DOM.setFileInputFiles`（`cdp_publish.py:3596`），不是 playwright 的 `set_input_files`：

```python
self._send("DOM.setFileInputFiles", {
    "nodeId": node_id,
    "files": [file_path],
})
```

**正文填写**：TipTap/ProseMirror contenteditable，逐字 type 带 jitter（`publish_pipeline.py:195` 的 hash/char delay 算法）。

**tab 切换**（`_click_tab` `cdp_publish.py`）：先轮询 `document.querySelectorAll('div.creator-tab').length > 0` 等 React 渲染（15s deadline），再用 JS `.click()` 点 tab 文本匹配——tab 是普通 DOM 不是 shadow，JS click 有效。**这正好对上 XhsGrowthAgent 这个 task 的根因**（PRD: creator-tab 异步渲染，`_wait_for_publish_ready` 命中视频 input 就返回，tab 还没渲染）。

### 4. 人感/反检测细节（除 CDP 外）

| 手段 | 实现 | 文件:行 |
|---|---|---|
| timing jitter | `_sleep(base, jitter)` 随机 ±25% | `cdp_publish.py` `_sleep` |
| 逐字打字 + 随机延迟 | hash 180ms±/char 45-95ms± | `publish_pipeline.py:195` |
| headless 指纹 | `--headless=new`（新版，非旧 `--headless`） | `chrome_launcher.py` |
| 后台节流禁用 | `--disable-background-timer-throttling` 等 4 个 | `chrome_launcher.py` |
| 真实 Chrome binary | 系统 Chrome，非 playwright bundle 的 chromium | `get_chrome_path` |
| 持久 profile | `--user-data-dir` 每账号隔离 | `get_user_data_dir` |
| 无 stealth 注入 | 不覆盖 navigator.webdriver 等 | （全文无 playwright_stealth） |

注意：README 仍警告"存在被风控、限流、封号风险，建议先在测试号验证、控频率"。CDP 方案**降低**而非**消除**风险。

### 5. 可借鉴性评估（针对 XhsGrowthAgent：python + playwright + FastAPI）

#### 高价值、改动小
- **改用 `connect_over_cdp` 连接一个常驻真实 Chrome**（而非 `playwright.chromium.launch`）。playwright 原生支持 `playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")`，可保留现有 playwright API，只换浏览器来源。这是**最小改动、最大收益**的一步。
- Chrome 由独立进程管理（`scripts/deploy.sh` 同级起一个 `chrome --remote-debugging-port=9222 --user-data-dir=...`），首次扫码登录后 profile 持久化。
- `_set_cookies` 改为"只在 profile 未登录时 fallback"，正常路径不手动注 cookie。

#### 中等改动
- `_click_publish` 改用 CDP `Input.dispatchMouseEvent`（playwright 的 `page.mouse.click` 底层就是 CDP，但若改用裸 CDP client 可彻底脱离 playwright 浏览器指纹）。或保留 playwright 但确保连的是真实 Chrome。
- 把 `playwright_stealth` 整套反检测**移除**——连真实 Chrome 后，stealth init script 反而是"自动化特征"（在已合法的浏览器里注入伪装脚本 = 自我标红）。README 注释也提到 stealth 默认 Win32/en-US 与真实 Linux UA 冲突反而像自动化。

#### 低优先/不借鉴
- 不借鉴"裸 websockets 手写 CDP JSON-RPC"——playwright `connect_over_cdp` 已封装好，手写收益低、维护成本高。
- 不借鉴"逆向 x-s 签名直调 API"——他们都没做，我们更不该碰（维护成本极高，XHS 改签名就崩）。
- `--headless=new` 在 Linux Chrome 上可用，但 XhsGrowthAgent 部署在 podman 里，需装真实 `google-chrome`（非 chromium），且 headless 仍比有头易被风控——建议有头 + Xvfb。

#### 对当前 task（fix-publisher-wait-for-tab-render）的直接启示
本 task PRD 修的"`_upload_images` 切 tab 前等 `div.creator-tab` 渲染"——XiaohongshuSkills 的 `_click_tab` **正是这么做的**（轮询 `querySelectorAll(tab).length > 0`，15s deadline）。我们的修复方向（`wait_for_selector("div.creator-tab", state="attached")`）与之一致，是正确且足够的**短期修复**。但**根因不在 tab 等待，在浏览器不被 XHS 信任**——长期须改 CDP 连真实 Chrome，否则 tab 修好了，发布提交那步依然 0 个 note/create 请求。

---

## Caveats / Not Found

- **`BetaStreetOmnis/xhs_ai_publisher`（★2004）未深入**：默认分支 main 的 README 返回 404，可能用了别的文档路径或未公开 README。其描述提"login-state r..."（截断），疑似有 login-state retention 机制，但未读到源码，不确定是否走 CDP。如需对比可后续单独 fetch 其 `src/`。
- **`openclaw` 平台本身未找到官方仓库**：搜索结果全是"for OpenClaw"的 Skill 仓库，未找到 openclaw 运行时本体。推测是类似 Claude Code 的闭源/半开源 agent runtime。不影响本次调研结论（我们关心的是发布 Skill 的实现，不是宿主）。
- **未验证 XiaohongshuSkills 在 Linux/podman 的可运行性**：README 注明"目前仅测试 Windows"，`get_chrome_path` 含 Linux 候选路径但未官方支持。借鉴到 XhsGrowthAgent（Linux 容器）需自行验证 `google-chrome` + `--remote-debugging-port` + `--user-data-dir` 在 podman 内的行为（注意 `--no-sandbox` 在容器内通常必需，但他们未加——可能因 Windows 不需要）。
- **未读到 `references/publish-workflow.md`**：GitHub contents API 返回空（可能该路径不存在或需子目录），故无法引用其官方工作流文档原文。核心机制已从 `cdp_publish.py` 源码直接确认，不依赖该文档。
- **x-s 签名"0 命中"是基于单文件 `cdp_publish.py` 的 grep**：该仓库其他文件（`feed_explorer.py` 等）可能含只读场景的签名/cookie 处理，但发布链路（`_click_publish`/`publish`）确在 `cdp_publish.py` 内，结论成立。

## External References

- [white0dew/XiaohongshuSkills](https://github.com/white0dew/XiaohongshuSkills) — 主力发布 Skill，CDP 连真实 Chrome，★3114，README 首提 OpenClaw。核心文件 `scripts/cdp_publish.py`、`scripts/chrome_launcher.py`、`scripts/publish_pipeline.py`。
- [Youhai020616/xiaohongshu](https://github.com/Youhai020616/xiaohongshu) — MCP + CDP 双引擎，同样连真实 Chrome profile，引用 stealth-cli/Camoufox 做反检测（与 XiaohongshuSkills 的"不注入 stealth"路线不同，可作为对比）。
- [zangqilong198812/openclaw-xiaohongshu-publish-skill](https://github.com/zangqilong198812/openclaw-xiaohongshu-publish-skill) — "User Chrome to publish RedNote post"，5★，思路一致但代码量小。
- [iamzifei/red-publisher-skill](https://github.com/iamzifei/red-publisher-skill) — Claude Skill，Python，9★，未深入源码。

## Related Specs / Local Files

- `backend/services/xhs_publisher.py` — 本地 publisher，`_ensure_browser`（launch 新 chromium + stealth）、`_set_cookies`（cookie 字符串注入）、`_click_publish`（坐标点击但浏览器不被信任）。与 XiaohongshuSkills 方案的根本差异点。
- `backend/tools/xhs/publisher.py` — tool wrapper，`_get_publisher` 实例化 `XHSPublisher`，改动若涉及构造参数（如加 cdp_endpoint）需同步这里。
- `.trellis/tasks/07-02-fix-publisher-wait-for-tab-render/research/root-cause.md`（task 内已有根因分析，本文件是"反爬方案"维度的补充调研）。
