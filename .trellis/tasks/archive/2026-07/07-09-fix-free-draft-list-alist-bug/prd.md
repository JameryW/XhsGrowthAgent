# Fix: free draft list alist bug

## Goal

`GET /api/free/drafts/{account_id}` 在真实 AsyncPostgresStore 下返回空列表。根因:`store.alist` 方法在 AsyncPostgresStore(及 BaseStore ABC)**不存在** — mock 测试手动设了 alist AsyncMock 漏掉。真实 store 调 `store.alist` 抛 AttributeError,被 try/except 吞,返回空。

运行时验证发现(E2E curl):create 2 草稿成功,list 返回 count:0。aget/update/delete 正常。

## Root cause

- `AsyncPostgresStore` 有 `aget/aput/adelete/asearch/alist_namespaces`,**无 `alist`**
- BaseStore ABC 也无 alist
- free.py `list_drafts` 用 `store.alist(namespace_prefix=ns, limit=)` → 真实 store AttributeError
- system.py:173 也用 store.alist(同样 bug,但只影响 health 计数,被 try/except 吞,非阻断)

## Fix

`list_drafts` 改用 `store.asearch(namespace, query='', limit=100)`(验证过:空 query 返回全部 items)。

## Requirements

- free.py `list_drafts`:`store.alist(namespace_prefix=ns, limit=)` → `store.asearch(ns, query='', limit=100)`
- mock_store fixture 改 alist mock → asearch mock
- 补测试:list 真返回 seeded 草稿(已有测试,改 mock 后应仍 pass)

## Acceptance Criteria

- [ ] free.py list_drafts 用 asearch
- [ ] mock_store fixture 改 asearch
- [ ] pytest 全绿
- [ ] 真实 Postgres store E2E 验证 list 返回 seeded 草稿
- [ ] mypy/ruff green

## Out of Scope

- system.py:173 的 alist bug(非本任务,单独处理)
