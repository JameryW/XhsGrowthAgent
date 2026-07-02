# 端到端验证发现：_fill_content 选择器也失效（未修，新 bug）

## 验证结果（publish-retry 能力本身 OK）
- `POST /api/workflow/publish-retry/{thread_id}` 端点工作：返回 `status=retrying`
- 后台任务执行 `run_publish` → 写回 `publish_result` 到 checkpoint + emit 事件
- 上传链路（已修的 _upload_images）**成功**：publish-retry 日志显示过了 `_upload_images`，失败发生在 `_fill_content`

## 新 bug（超出本任务范围，未修）
`backend/services/xhs_publisher.py` 的 `_fill_content`（line ~340）填标题/正文时：
- 首选 `input[placeholder*=标题], .title-input` 未命中（现网改版）
- 备用 `page.type("input", title, delay=50)` → `Page.type: Timeout 30000ms`（input 选择器太宽泛，命中不可编辑元素或无 input）
- 正文同理 `textarea[placeholder*=正文], .content-input` + 备用 `page.type("textarea", body)`

现网发布页编辑态（上传图片后）的标题/正文输入框真实 DOM 需另探（需 cookie + playwright dump，类似 _upload_images 的探针过程）。

## 范围决策
本 PR 只做"失败手动重试发布能力"（端点 + run_publish 提取 + 前端 + 测试）。_fill_content 选择器修复是独立的发布链路 DOM 适配问题，按 [[separate-pr-per-feature]] 单独成 PR，不混入。
