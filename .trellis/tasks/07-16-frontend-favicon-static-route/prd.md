# PRD: 修复网页 favicon 不显示

## 背景

网页入口在 `frontend/index.html` 中请求 `/favicon.svg`，但后端 SPA fallback
只把 `/assets/*` 当作静态文件处理，导致 `/favicon.svg` 实际返回
`index.html`（`text/html`），浏览器无法将其识别为图标。

## 目标

- 让 `/favicon.svg` 返回构建产物中的真实 SVG，并带正确的 MIME 类型。
- 保持现有 API 路由、SPA fallback 和带 hash 的 assets 缓存策略不变。
- 增加回归测试，覆盖 favicon 内容类型和 SVG 响应。

## 验收标准

- `GET /favicon.svg` 在构建产物存在时返回 `200`、`image/svg+xml` 和 SVG 内容。
- favicon 构建产物缺失时返回 `404`，不返回 SPA HTML。
- 后端测试、类型检查、构建通过。
- 部署后线上 favicon 请求不再返回 `text/html`，服务健康检查通过。
