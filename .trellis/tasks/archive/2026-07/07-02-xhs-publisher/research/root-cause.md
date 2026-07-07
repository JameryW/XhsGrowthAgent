# 完整根因（端到端实测确认 2026-07-02）

## 三个并存 bug（不止选择器）

### Bug 1：从未切到"上传图文"tab
创作者发布页默认停在"上传视频"tab，其 file input `accept=".mp4,.mov,..."` 不含 image。
原代码直接 `query_selector("input[type=file][accept*=image]")` 必 miss → else 分支
`.upload-area, .image-upload-btn` 现网不存在 → 30s 超时。
修复：上传前用 JS click 切到可见的"上传图文"tab（offsetParent 非 null 过滤隐藏副本），
幂等（已在图文 tab 则跳过，避免重复点 toggle 回视频）。

### Bug 2：wait_for_function 的 JS 用了 arguments[0]
原代码：
```python
await page.wait_for_function(
    "document.querySelectorAll('.image-item').length >= arguments[0]",
    arg=len(valid_paths), timeout=60000,
)
```
Playwright 把 `arg` 作为**函数首个形参**注入，不是 `arguments` 对象。箭头函数不绑定 `arguments`，
所以 `arguments[0]` 恒抛 ReferenceError → wait_for_function 把异常当未满足持续重试 → 60s 超时。
（之前的 ponytail 注释只修了一半：`args=`→`arg=`，但 JS 侧 `arguments[0]` 从没对过。）
修复：JS 改 `(n) => document.querySelectorAll('.item-picture, .image-item').length >= n`。

### Bug 3：上传成功指示选择器 .image-item 现网不存在
上传成功后页面进入编辑态，图片以 `.item-picture` 容器呈现（`.img-list` 下），`.image-item` 不存在。
修复：等待选择器改 `.item-picture, .image-item`（后者兜底）。

### 附带：wait_for_selector 等 hidden input
图片 file input 是 hidden 元素，`wait_for_selector` 默认等 visible 会超时。
修复：切 tab 后等 input 用 `state="attached"` 只等 DOM 挂载。

## 端到端验证
真实 cookie + 真实图片（PIL 生成 200x200 jpg）+ 真实发布页：
- 切 tab 成功，找到图片 input，set_input_files 2 张图
- wait_for_function 正确等到 2 个 .item-picture 出现
- **未点发布按钮**（仅验证上传链路，不产生公开内容）

## 容器部署关键发现
- 后端代码在容器内有两份：`/app/backend`（uvicorn cwd，服务实际用这份）和
  `/usr/local/lib/python3.11/site-packages/backend`（pip 安装的旧版副本）
- 一次性验证脚本须 `sys.path.insert(0,'/app')` 否则误用 site-packages 旧版
- 改 /app 文件后须 `find /app -name "*.pyc" -delete` 否则 .pyc 缓存致 inspect 与运行时不一致
- **/app 改动不进镜像**，重新部署（deploy.sh）才固化；当前服务已 hot 生效（cp + 删 pyc）
