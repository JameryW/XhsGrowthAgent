# 现网 DOM 实测结果（2026-07-02 探针）

## 发布页结构（creator.xiaohongshu.com/publish/publish）
- 默认停在"上传视频"tab，其 file input：`<input class="upload-input" type="file" accept=".mp4,.mov,.flv,.f4v,.mkv,.rm,.rmvb,.m4v,.mpg,.mpeg,.ts">` —— **accept 不含 "image"**
- tab 结构：`<div class="creator-tab"><span class="title">上传图文</span></div>`，页面上有 3 个同名"上传图文"tab，其中隐藏副本（`style="position:absolute;left:-9999px"` / `offsetParent=null`）会骗过 Playwright 的 `locator.first().click()`（报 "outside of viewport" 超时）
- 切到"上传图文"tab 后出现图片 file input：`<input class="upload-input" type="file" multiple accept=".jpg,.jpeg,.png,.webp">`
- 上传区容器：`.upload-c`、`.upload-wrapper`、`.upload-container`、`.drag-over`

## 根因（实锤）
1. 默认 tab 是视频，file input 的 accept 不含 image → `input[type=file][accept*=image]` 必 miss
2. else 分支 `.upload-area, .image-upload-btn` 现网不存在 → 30s 超时
3. 从未切到"上传图文"tab

## 修复（已实施 backend/services/xhs_publisher.py:_upload_images）
1. 上传前用 JS click 切到可见的"上传图文"tab（`offsetParent !== null` 过滤隐藏副本）
2. 首选选择器改 `.upload-input, input[type=file][accept*=jpg], [accept*=png], [multiple]`
3. 备用容器改 `.upload-c, .drag-over, .upload-area, .image-upload-btn`
4. 上传完成等待选择器加 `.upload-item` 兜底（待端到端验证确认实际指示元素）

## 待验证
- `.image-item` 上传成功指示元素是否命中（探针未真实上传图片，无法确认）
