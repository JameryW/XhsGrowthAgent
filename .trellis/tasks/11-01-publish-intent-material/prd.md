# 主链迁移 P1 第一切片：principal + 发布内容材料（票 5ba）

> 目标（对应 `docs/publish-action-protocol.md`「主链迁移控制面：阶段方案」P1）：
> 让主链发布开始携带**意图形状的数据**，同时不动执行器——这样 P3 换执行器时有东西可交。
> 本票还解决了 P1 里的一个错误假设：`ActionIntent` 不是主链能直接构造的对象。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 主链 actor 只能是 `publish_options["account_id"]`；`state["account_id"]` 只是工作流标签 | `backend/agents/publisher.py` 的发布路径注释（S5c） |
| 空 account = 部署本体（凭证解析器读部署自己的声明，不发明账号） | `services/xhs_credentials.py` 对空 account 的口径 |
| 发布内容可外置为 artifact + sha256 | `backend/state/artifacts.py` 的 `put_artifact` / `make_ref`（ref 内含 content_hash/size） |
| `ActionIntentRequest` 需要 `decision_id`；`ActionIntent` 还需要 `creator_id`/`audience_id` | `backend/creator_agent/models.py` |
| `DecisionRecord` 是 creator_agent 概念（audience、model_revision、ranked candidates） | `models.py` 的 `DecisionRecord` 字段；`advisor.py` 的构造点 |
| 主链没有上述任何身份 | 发布链路只读 publish_options/state；无 DecisionRecord 生产者 |

**结论**：P1 必须拆成 P1a（可派生的部分，本票）与 P1b（身份模型裁定后才能构造控制面对象）。

## 2. 本票交付（P1a）

1. 新模块 `backend/services/publish_intent.py`（纯派生，无副作用决策）：
   - `resolve_publish_principal(publish_options)` → `PublishPrincipal(kind="account"|"deployment", account_id)`；
   - `publish_content_body(state)`：发布实际提交的 title/body/hashtags/image_paths 的规范形状；
   - `write_publish_content_artifact(...)`：写 `artifact://publish_content/<publish_id>`（best-effort）；
   - `publish_intent_material(...)`：principal + artifact_ref + content_hash 的材料包。
2. `backend/agents/publisher.py`：
   - 用 `resolve_publish_principal` 取代裸取 `publish_options.get("account_id")`（同一行为，显式分类）；
   - PREPARED 记录新增 `principal_kind` / `principal_account_id` / `artifact_ref` / `content_hash`
     （artifact 写失败则字段为空，绝不改变发布行为）。
3. 文档：在 P1 段落记录 P1a 已落地 + **P1b 的身份模型前置**（A 泛化控制面 / B 主链自有意图 + 适配层），
   并说明 `mainline_action_intent_producers` 保持 0 是诚实度量，不为凑数字构造对象。
4. 测试：principal 分类矩阵（含空白/缺省/非字符串）、内容形状与哈希稳定性、artifact 内容与 ref 一致、
   存储失败 → 空材料、PREPARED 记录两个主体两种情况（account / deployment）。

## 3. 不做

- 不构造 `ActionIntent(Request)`，不写 decision 记录，不切执行器（P1b/P3）。
- 不改 publish 行为/状态机/幂等键；artifact 写入失败不影响发布。

## 4. 验收

- [x] 主链 PREPARED 记录带 principal 与内容材料；account 与 deployment 两类都有测试
- [x] 执行器与 publish_result 行为逐项不变（既有 run_publish 测试全绿）
- [x] `mainline_action_intent_producers` claim 保持 0（未构造控制面对象）
- [x] ruff/format、定向测试绿
