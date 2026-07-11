# free-drafts-status-filter

## Goal

`/drafts` 当前硬上限 100 篇且无筛选——草稿多了旧的无声消失（truncated 仅提示存在更老，但拿不到），也无法按发布/评估状态或标题定位。加 status filter + title search，让用户在已取回的 capped 100 篇内快速定位草稿。post-filter 零额外成本（asearch 已返回全量页面）。

## What I already know

- `GET /free/drafts/{account_id}` (`backend/api/routes/free.py:284`) 用 `store.asearch(_draft_ns, query="", limit=100)`，返回 `{account_id, drafts[], count, truncated}`。
- drafts[] 每条带 `draft_id, title, hashtags, created_at, updated_at, last_evaluation{overall_score,decision}, published`。
- `truncated` = `len(items) >= 100` 启发式（BaseStore 无 portable total-count）。
- TUI `handleDrafts` (`frontend/src/views/AgentTUI.vue:1038`) GET 后渲染 title 行 + 评估/已发布徽章 + updated_at。
- spec `.trellis/spec/backend/free-creation.md:30` 行有 response 契约 + "Count + truncation" 子节。
- asearch 的 `filter=` dict 是 exact field match；`published` 布尔可 exact match，但 `evaluated` 需判 `last_evaluation` 是否存在（非字段值匹配），title search 需 substring（非 exact）——三者都 post-filter 更一致直接。

## Requirements

- `GET /drafts/{account_id}` 接受可选 query params：
  - `status`: `all`（默认）| `published` | `unpublished` | `evaluated` | `unevaluated`
  - `q`: title 子串（case-insensitive contains，空串 = 不过滤）
- 过滤在 asearch 返回的 capped 100 集合上 post-filter（零额外 store 调用）。
- `count` = 过滤后 drafts[] 长度（语义：返回给客户端的条数）。
- `truncated` 仍按原 100-cap 判定（不变：提示"store 里有更老的"）。
- 无效 `status` 值 → 400 ValidationError（白名单校验，fail-fast，不静默回退 all）。
- TUI `/drafts [status] [query...]`：第一个 token 若属 status 关键词集合则作 status，否则整体作 query；`/drafts` 无参 = all。title 行显示当前 filter（如 `Free Drafts — acct (5, published):`）。
- i18n key 新增（中英）：drafts filter 标题格式 + 无效 status 提示。
- spec 同步：response 契约加 `status`/`q` query param + 过滤语义子节。

## Acceptance Criteria

- [ ] `GET /drafts/x?status=published` 仅返回 `published=True` 草稿
- [ ] `GET /drafts/x?status=unpublished` 仅返回 `published=False`/缺省
- [ ] `GET /drafts/x?status=evaluated` 仅返回 `last_evaluation` 非空
- [ ] `GET /drafts/x?status=unevaluated` 仅返回 `last_evaluation` 缺省/None
- [ ] `GET /drafts/x?q=美食` 返回 title 含"美食"（case-insensitive）
- [ ] `status` + `q` 可组合（AND）
- [ ] `GET /drafts/x?status=bogus` → 400
- [ ] `count` = 过滤后长度；`truncated` 不受 filter 影响
- [ ] TUI `/drafts published`、`/drafts 美食`、`/drafts published 美食` 均正确
- [ ] 无效 status TUI 报错（红字）
- [ ] 现有 `/drafts`（无参）行为不变
- [ ] mypy backend 绿 + ruff check/format 绿 + pytest 全量绿

## Definition of Done

- 后端 route + 2+ 新测试
- 前端 TUI + i18n 中英
- spec 同步
- pre-push 三连（ruff format --check + 全量 mypy backend + 全量 pytest）绿

## Technical Approach

**Post-filter on capped page**（非 asearch `filter=`）：
- asearch 已返回 limit=100 全量页面；在 Python 端按 status/q 过滤。
- 不增加 store 调用，不依赖 BaseStore 的 `filter=` 对布尔/嵌套对象的语义。
- `truncated` 语义不变（"store 里可能还有更老的"），独立于 status filter——即便 filter 后 count=0，truncated 仍可能 True（说明 store 里有更老的但不属当前 filter... 实际上 truncated 是 pre-filter 判定，语义上是"总集合可能 >100"，保留原义即可）。

**TUI arg 解析**：
```
/drafts                        → status=all, q=""
/drafts published              → status=published, q=""
/drafts 美食                    → status=all, q="美食"   (首个 token 非 status 关键词 → 全体作 q)
/drafts published 美食          → status=published, q="美食"
```
status 关键词集合 = {published, unpublished, evaluated, unevaluated}。首个 token 命中集合 → status，剩余 join 作 q；否则全体作 q。

## Out of Scope

- 真正分页（offset/page）——BaseStore 无 portable total-count，offset 语义无法正确实现；truncated 已暴露上限。留 YAGNI。
- 按 score/decision 二级 filter——`last_evaluation` 已在列表徽章显示，按值过滤收益低。
- 按 created_at/updated_at 范围 filter——无时间 picker UI，YAGNI。
- analytics 历史趋势 / 批量删除 / analytics 刷新——伪命题或 YAGNI（见 brainstorm 分类）。

## Technical Notes

- 后端文件：`backend/api/routes/free.py` `list_drafts`（284-340）
- 前端文件：`frontend/src/views/AgentTUI.vue` `handleDrafts`（1038-1100）+ SLASH_COMMANDS/帮助文本
- spec：`.trellis/spec/backend/free-creation.md` route 表（30 行）+ "Count + truncation" 子节后新增 "Status filter + title search" 子节
- i18n：`frontend/src/i18n/`（中英 locale，en 懒加载）
- 测试：`tests/` 下 free route 测试文件（grep 定位）
- 本机 vite build 必 OOM——前端 gate 用 vue-tsc typecheck，build 留 CI（[[vite-build-oom-low-ram-box]]）
- pre-push 三连（[[pre-push-run-format-and-full-mypy]] [[pre-push-run-full-pytest-not-just-changed]]）
- 从 main 新建分支提独立 PR（[[separate-pr-per-feature]]）
