# 把 xhs:outreach 挂进 capability 的 auth_scope（票 5av）

> B 类裁定（用户 2026-10-31 拍板：挂）。目标：`xhs:outreach` 从“只存在于
> `XhsCredential.scopes` 的第三档”变成 Gateway 真正检查的资格，不再只是文档里的档位。

## 1. 现状（已核实）

- `XhsCredential.scopes`：`xhs:read`（cookie）、`xhs:write`（cookie ∨ profile_bound）、
  以及仅当 `outreach.allows_proactive` 时追加 `xhs:outreach`
  （`backend/services/xhs_credentials.py`）。
- `backend/tools/runtime/catalog.py`：`xhs.comment_reply` / `xhs.dm_send` 都只声明
  `auth_scope=("xhs:write",)`，注释明说「声明 outreach 前必须 Gateway 真有调用方传
  granted_scopes」。
- 调用面：`backend/services/xhs_engagement.py` 的 `reply_comment` / `send_dm` **直接调
  tool**，不经 Gateway；全仓 engagement 能力没有任何传 `granted_scopes` 的调用点。
- 文档：`docs/tool-gateway-engagement-migration.md` §3.1 / §9.5-② 把「未挂」记为诚实边界；
  `docs/publish-action-protocol.md` 的 scope 表也有 `xhs:outreach` 行。

## 2. 决定（locked）

1. **不拆能力**（不新增 `xhs.dm_send_proactive` 之类）。保持一个动作一个 capability。
2. **语义收紧并写清**：`xhs:outreach` = 「该账号的触达策略允许触达」（机制 ∧ 策略，
   `outreach.allows_engagement`，即 mode≠nobody），不再只表示冷启动。据此：
   - `XhsCredential.scopes` 在 `allows_engagement` 时授予 `xhs:outreach`（而非仅 `allows_proactive`）；
   - `xhs.comment_reply` / `xhs.dm_send` 的 `auth_scope=("xhs:write", "xhs:outreach")`；
   - 冷启动的“目标是否允许”仍由服务层 `check_dm_target_allowed` + 人工确认负责，
     scope 只表达「账号被允许触达」。
3. **让 Gateway 检查真实发生**：`XhsEngagement.reply_comment/send_dm` 的发送调用改走
   `shared_gateway().invoke(capability, payload, thread_id=..., granted_scopes=...)`，
   scopes 由 `services.xhs_credentials.granted_scopes(account_id)` 解析（可注入 seam 供测试）。
   若 payload 形状不匹配，按 tool 的 StructuredTool 入参加拿大式适配；不要绕过 Gateway。
4. 配额/账本/审批的既有顺序不变：先 `_precheck_engagement` / 策略检查，再 Gateway 调用。

## 3. 要求

1. 代码：`xhs_credentials.py`（scopes 条件 + docstring）、`catalog.py`（两条声明 + 注释改写）、
   `xhs_engagement.py`（Gateway 调用 + scopes 注入 seam）。
2. 测试（至少）：
   - `scopes`：mode=nobody/inbound_only/confirmed_anyone 三档的授予矩阵；
   - Gateway：去掉 `granted_scopes` → 调用被拒（violation）；带齐 → 通过；
   - 服务层：reply/comment 路径确实经过 Gateway（注入 fake gateway 断言 capability/thread_id）；
   - catalog 快照/声明一致性测试按新 scope 更新。
3. 文档：`docs/tool-gateway-engagement-migration.md` §3.1 末段、§9.5-② 改「已落地（票 5av）」并写清新语义；
   `docs/publish-action-protocol.md` 的 scope 行只做最小措辞同步（若需）；不要改动 claim 表数值
   （本票不改变 claim 计数的定义，若测试要求才改并说明）。
4. `ruff check` / `format` 绿；相关测试子集绿；不要跑全量。

## 4. 验收

- [x] `grep -rn "auth_scope=(\"xhs:write\", " backend/tools/runtime/catalog.py` 对这两条不再命中（两条均为 `("xhs:write", "xhs:outreach")`）
- [x] 无 `granted_scopes` 时 Gateway 拒绝 engagement 调用（`test_xhs_engagement_gateway.py` 有测试；服务路径缺 scope 在 claim 前返回 `blocked/permission_denied`）
- [x] 文档不再把「未挂」记为开放边界（§3.1.1 / §9.5-② 已改为 landed；`docs/tool-runtime.md` 两格同步）
- [x] 定向测试全绿（services 1061 passed / tools runtime 245 passed / api 652 passed / db 156 passed；docs anchors+citations 6 passed；ruff/format 绿）
- [x] 语义收紧记录在案：`xhs:outreach` = 机制 ∧ 策略（`allows_engagement`，mode ≠ nobody），冷启动的目标/预算仍由服务层判定
