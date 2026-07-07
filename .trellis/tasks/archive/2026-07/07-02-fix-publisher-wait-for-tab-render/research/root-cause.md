# 根因：_upload_images 切 tab 前没等 tab 渲染

## 现象
真实发布失败：`_upload_images` line 325 备用分支 `wait_for_selector(".item-picture")` 60s 超时。
日志：`发布失败: Page.wait_for_selector: Timeout 60000ms ... waiting for .item-picture, .image-item`。

## 根因
创作者发布页是 SPA，`div.creator-tab`（"上传图文"等 tab）**异步渲染**。

`_wait_for_publish_ready` 的 `_PUBLISH_READY_SELECTORS` 含 `input[type=file]`——
导航后视频 tab 的 file input（accept=.mp4）先渲染出来，ready 检查命中它就返回 True。
但此时 `div.creator-tab` **还没渲染**（creator-tab 数=0）。

`_upload_images` 随即：
1. `already_img` 检查（找图片 input）→ False（只有视频 input）
2. 切 tab 的 JS `querySelectorAll('div.creator-tab')` → 空数组 → `find` 返回 undefined → `clicked idx=-1`（没切）
3. `wait_for_selector("[accept*=jpg]")` 10s 超时（还是视频 tab，没图片 input）
4. `upload_input` query → False（首选 miss）
5. 走 else 分支 → `page.click(".upload-c...")` + `wait_for_selector(".item-picture")` 60s 超时

## 诊断证据（实测）
- `_check_login: True`，URL 是发布页
- `_wait_for_publish_ready: True`（命中视频 input）
- 此时 `creator-tab 数: 0`，file inputs: 1（视频 accept=.mp4）
- **sleep 5s 后** `creator-tab 数: 9`（含"上传图文"），切 tab idx=2 成功，`upload_input (首选)=True`

## 修复
`_upload_images` 切 tab 前，先等 `div.creator-tab` 渲染出来：
```python
if not already_img:
    # tab 是 SPA 异步渲染，_wait_for_publish_ready 命中视频 input 就返回了，
    # 但 creator-tab 此时可能还没渲染——等它出现再切
    try:
        await page.wait_for_selector("div.creator-tab", state="attached", timeout=10000)
    except Exception:
        pass
    # 然后切 tab（现有逻辑）
```

## 范围
仅 `_upload_images` 加一行 wait_for_selector(div.creator-tab)。不改 ready 检查、不改路由。
