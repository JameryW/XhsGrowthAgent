# 触达策略表的管理写路径（票 5ax）

> B 类裁定（用户 2026-10-31 拍板：实现）。目标：`XhsOutreachPolicy`
> （mode / daily_proactive_cap）从“只能直接写库”变成**有校验、有 API、有测试的管理写路径**，
> 并收口 `docs/tool-gateway-engagement-migration.md` §9.5-③ 的诚实边界。

## 1. 现状（已核实）

- 读侧：`backend/services/xhs_outreach_policy.py` 的 `_read_stored` 从 `account_credentials`
  读 `XHS_OUTREACH_MODE` / `XHS_OUTREACH_DAILY_PROACTIVE_CAP`（`list_credentials` → `.value` 解密），
  再按「账号行 → 部署 env → 安全默认」解析，失败安全。
- 写侧：`backend/db/accounts.py` 有 `upsert_credential(account_id, key_name, value)`（加密写入；
  票 5n 的扫码登录在用）。**没有任何 API/服务函数写这两把键** —— 文档明说“账号行策略需直接写
  `account_credentials`”。
- API 先例：`backend/api/routes/system.py` 已有 cooldown policy 的 GET/PUT/DELETE
  （`get_cooldown_policy` / `set_cooldown_policy` / `clear_cooldown_policy`），本票照此形状。
- 预检：`tests/unit/services/test_xhs_outreach_policy.py` 之类已覆盖读侧优先级（实现前先看）。

## 2. 要求

1. **服务层写路径**（`backend/services/xhs_outreach_policy.py` 追加，保持模块单一职责）：
   - `set_outreach_policy(account_id, *, mode: str | None = None, daily_proactive_cap: int | None = None)`：
     校验 mode ∈ `OUTREACH_MODES`、cap 为非负 int；只写显式给定的键（`upsert_credential`）；
     返回解析后的 `XhsOutreachPolicy`（写后读回，证明生效）。
   - `clear_outreach_policy(account_id)`：删除该账号的两把策略键（需要 `delete_credential`；
     若 DB 层没有，新增一个最小函数并加测试）；返回删除后的有效策略。
   - 无 pool / DB 不可用：**明确报错**（管理写不能静默 best-effort），错误类型用现有 API 错误风格。
2. **API**（`backend/api/routes/system.py`，与 cooldown policy 同层）：
   - `GET /system/outreach-policy/{account_id}`：`effective` + `overrides`（读侧解析结果）；
   - `PUT /system/outreach-policy/{account_id}`：body 含 `mode` / `daily_proactive_cap`（可空）；
   - `DELETE /system/outreach-policy/{account_id}`：清除账号行，回落部署默认。
   响应沿用 `success(...)` 信封；错误用 `APIError` 家族（ValidationError 等）。
3. **测试**：写入后读回生效；非法 mode/cap 拒绝；账号行覆盖 env（优先级）；`get` 显示 overrides；
   `delete` 后回落；API 层用 TestClient + mocked DB（不要真连 PG）。
4. **文档**：`docs/tool-gateway-engagement-migration.md` §9.5-③ 改为「已落地（票 5ax）」并写
   API 形状；§9.5-⑤ 的 ③ 同步；若 §7.2 有“没有管理界面”表述一并改。
5. 不新增依赖；`ruff`/`format` 绿；定向测试绿；不要跑全量。

## 3. 验收

- [x] 三条 API 有测试（成功 + 校验失败 + 回落）；DB 用 mock，不连 PG
- [x] 账号行优先级与失败安全不变（现有读侧测试不回归）
- [x] 文档不再把“无写路径”记为开放边界（§9.5-② ③ 已改为 landed，含 API 形状与 503 语义）
- [x] 服务层写/清函数有校验与读回；无 pool 明确报错（`OutreachPolicyStoreUnavailableError` → 503），不做静默 best-effort
- [x] `delete_credential` 幂等；清除后回落部署默认；ruff/format 绿

## 4. 登记残余（不阻塞）

- 两个 upsert 是两条独立语句（无事务）：极端崩溃可能留下只写了一半的覆盖；读侧逐字段解析所以每个已写字段仍诚实，但无 all-or-nothing 保证。
- 写入不校验账号存在性：未知账号会以 DB FK 错误暴露（500），与 cooldown policy 现状一致，可后续收紧为 404。
