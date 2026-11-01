# 触达策略写路径残余：原子写入 + 未知账号 404（票 5ay）

> 来源：票 5ax 的 PRD「登记残余」两条（当时明确记为可后续收紧）：
> ① `set_outreach_policy` 两条 upsert 无事务；② 未知账号写入以 DB FK 错误（500）暴露。
> 本票把两个残余都收掉。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 两条 upsert 是独立语句 | `set_outreach_policy` 里两次 `await upsert_credential(...)`；崩溃可留下只写一半的覆盖 |
| 账号库只有单键写 | `backend/db/accounts.py` 只有 `upsert_credential` 与 `delete_credential` |
| 未知账号不校验 | 写入不查 `accounts` 表，FK 错误直接冒到 500 |
| 表里已有可用 `get_account` | `backend/db/accounts.get_account(account_id) -> AccountRow | None` |

## 2. 决定（locked）

1. `upsert_credential` 保持公开 API 不变，内部委托给新的
   `upsert_credentials(account_id, values: Mapping[str, str])`；多键写在同一连接上下文里执行
   （psycopg_pool 的连接上下文 = 一个事务），**要么全落、要么全不落**。
2. `set_outreach_policy` 写前校验账号存在：不存在 → `OutreachPolicyAccountNotFoundError`
   （API 映射 `AccountNotFoundError` → 404）。理由：不存在的账号策略行对任何读者都不可见，
   报告成功等于声称一次不会生效的暂停。
3. `clear_outreach_policy` 保持**幂等**（未知账号也返回成功/回落默认）：清空一个不存在的
   覆盖不需要错误；404 只属于"写入一个不可见的策略"。
4. 读侧语义不变（仍然失败安全）。

## 3. 要求

1. `backend/db/accounts.py`：新增 `upsert_credentials`；`upsert_credential` 委托。
2. `backend/services/xhs_outreach_policy.py`：新增 `OutreachPolicyAccountNotFoundError`；
   `set_outreach_policy` 校验账号 + 单次批量写。
3. `backend/api/routes/system.py`：PUT 映射 404（`ERROR_ACCOUNT_NOT_FOUND`）。
4. 测试：单次多键写（记录调用次数/映射）、未知账号拒绝且不落行、API 404 信封；
   更新既有 mock seam（`upsert_credentials` / `get_account`）。
5. 文档：`docs/tool-gateway-engagement-migration.md` §9.5-③ 补原子写与 404；
   `account_credentials_inserts` claim 不变（仍是同一处 INSERT 文本）。

## 4. 结果（2026-11-01）

- [x] 多键单事务写入；`upsert_credential` 兼容委托
- [x] 未知账号 404；清空保持幂等
- [x] 定向测试：services+api+db+tools runtime 子集绿（新增用例通过）
- [x] 文档门禁（scripts 97 passed）与 ruff/format 绿
