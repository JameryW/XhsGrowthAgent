# P1b-2：主链 decision 身份 + origin=mainline intent 生产者（票 5bc）

> 目标：让主链的**真实发布**消费一个**持久的、审批产生的** decision 身份，构造并落库
> `origin=mainline` 的 `ActionIntent`。执行仍走 `run_publish`（P3 才换执行器）。
> 这是 5au 计划 P1 的最后一块；落地后 `mainline_action_intent_producers` 由 0 变 1。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| review 审批端点已有 `updates["publish_options"]` 写入并 resume | `backend/api/routes/review.py` 的 `submit_review` |
| 审批是唯一的人类发布授权点；dry-run 不执行 | 同文件：`pub_opts = decision.publish_options or PublishOptions(dry_run=True)` |
| `ActionIntent` 现支持 `origin=mainline` 且要求 creator/audience 为空 | 票 5bb（`models.py`） |
| `ActionIntent` 的 publish payload 需要 artifact_ref + 64 位 content_hash + thread | `_validate_publish_payload` |
| 发布内容材料已有 `publish_content_body` / `content_hash` / `artifact://publish_content/<publish_id>` | 票 5ba（`services/publish_intent.py`） |
| 仓库 `DurableCreatorAgentRepository.create_action` 按 (account, idempotency_key) 幂等 | `backend/db/creator_agent.py`，存储 payload_json（无需迁移） |

## 2. 决定（locked）

1. **decision 身份来自审批，不由内容派生**：批准真实发布时生成
   `decision_id = "mainline:<uuid>"`，连同 `thread_id`、`account_id`、`content_hash`
   （审批时的内容哈希，绑定"批准了哪份内容"；不使用时间窗会漂移的 publish_id）、
   `approved_by`（认证用户 id）、`approved_at`，写入 `state["publish_decision"]`。
   dry-run 审批不产生身份。
2. **消费而非发明**：`run_publish` 在 Effect 账本 claim 成功后调用
   `record_mainline_publish_intent`；仅当
   - principal 是具名账号（部署本体不构造：`ActionIntent` 是 account-scoped 的），
   - `publish_decision` 存在且 `decision_id` 非空，
   - 账号一致、content_hash 一致、thread 非空，
   - 发布内容材料（artifact_ref + content_hash）非空，
   才构造 `ActionIntent(origin=MAINLINE, creator_id="", audience_id="", status=CONFIRMED,
   resolved_at=approved_at, idempotency_key=publish_id)` 并落库。
3. **best-effort 且旁路**：任何不匹配/存储失败都返回 None + 日志，绝不影响发布；
   重试时仓库按 idempotency_key 返回同一行。
4. **claim 同步**：`action_intent_construction_sites` 1→2，
   `mainline_action_intent_producers` 0→1；直调仍 3（P3 才变）。
5. 不为部署本体发明账号 id、不伪造 creator/audience、不在 dry-run 产生意图。

## 3. 要求

1. `backend/state/schema.py`：新增 `publish_decision: dict[str, Any]`。
2. `backend/api/routes/review.py`：`_mainline_publish_decision(...)` + 批准真实发布时写入。
3. `backend/services/publish_intent.py`：`record_mainline_publish_intent(...)`（纯消费 + 校验 + 落库）。
4. `backend/agents/publisher.py`：claim 成功后调用 producer（旁路、best-effort）。
5. 测试：
   - service：绑定成功（字段/仓库可读/幂等重试同一行）、哈希不一致/账号不一致/thread 空/
     无决策/空材料/部署主体/存储失败 → 全部 None；
   - run_publish：有 decision → 落一条 mainline intent；无 decision → 不落；
   - review API：真实发布审批写 `publish_decision`（含 by/at/hash/thread/account），dry-run 不写。
6. 文档：`docs/publish-action-protocol.md` 的残留/起点表/plan P1b-2/claim 表同步。
7. 验证：定向 + 全量 + doc claim 重算 + ruff 绿。

## 4. 结果（2026-11-01）

- [x] 审批写入 decision 身份；dry-run 不写
- [x] producer 消费身份构造并落库 origin=mainline intent（幂等、best-effort）
- [x] claim：construction sites 2、producers 1；直调 3 不变
- [x] 定向 125 passed（run_publish+intent+api_routes）；doc gates 绿；全量见 task.json notes

## 5. 不做什么

- 不切执行器（P3）：publish 仍由 `run_publish` 执行；intent 只是审计/交接。
- 不改 `ActionIntentRequest`/公开 API/DB 列；不给部署本体造账号。
