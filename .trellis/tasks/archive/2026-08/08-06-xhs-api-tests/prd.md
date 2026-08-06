# 为 services/xhs_api.py 补单元测试

## 背景

`backend/services/xhs_api.py` 3 class 9 method 0 单测（grep 确认）。
纯函数 builder，XHS API 逆向产物——参数名/常量是风控关键点，回归会破坏 API 调用。
被 xhs_client + creator_stats/client 消费。

## 测试范围

### XHSApiEndpoints
- `full_url(endpoint)` — 默认 BASE_URL 拼接
- `full_url(endpoint, base=CREATOR_URL)` — 自定义 base
- 端点常量存在性（HOMEFEED/SEARCH_NOTE/COMMENTS_LIST/NOTE_DETAIL/SEARCH_USER/USER_INFO/USER_NOTES/DM_LIST）

### XHSApiHeaders
- `build()` — 无 cookie 不含 Cookie 头
- `build(cookie="a1=x")` — 含 Cookie
- `build(extra={...})` — extra 覆盖
- `build()` 不修改 DEFAULT_HEADERS（每次返回 copy）

### XHSApiParams
- `homefeed_params(category="")` — sort_type=1, search_channel_id=""
- `homefeed_params(category="x")` — sort_type=0
- `search_params(keyword, page, sort_type)` — 字段 + 默认 page_size=20
- `comments_params(note_id, cursor)` — image_scenes 固定值
- `search_users_params(keyword, page)` — page_size=20
- `user_info_params(user_id)` — 单字段
- `user_notes_params(user_id, cursor, num)` — num 透传

## AC

1. 新增 `tests/unit/services/test_xhs_api.py`
2. 覆盖上述 3 class 全 public method
3. ruff + mypy + 全量 pytest 全绿

## 风险

无。纯新增测试，不改生产代码。
