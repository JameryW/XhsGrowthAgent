# P4 分支 B 预备：executor 接受 caller-supplied publish request（票 5br）

> B3 接线的必要前置：mainline 入口持有"最终内容"（含无素材图时生成的文字封面），
> 而 executor 默认从 artifact 重读正文——直接用 executor 会丢掉封面。本票给 executor
> 开一个**受约束**的 caller-supplied request seam，让主链把已解析的请求交进来。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 主链在 dispatch 前才生成文字封面并加入 image_paths | `backend/agents/publisher.py` `_run_publish_attempt` |
| artifact 正文来自 `publish_content_body(state)`，不含生成封面 | `backend/services/publish_intent.py` |
| executor 从 artifact 读正文并校验 content_hash | `CreatorAdvisor._execute_publish` |
| 主链已有共享 `PublishRequest`（P3，票 5be） | `_run_publish_attempt` 构造处 |

## 2. 决定（locked）

1. `execute_action(..., *, force=False, request: PublishRequest | None = None)`；
   `_execute_publish(..., request=...)`。
2. 传 request 时：先做 entitlement（凭据）检查，然后**逐字段绑定校验**：
   `account_id` / `thread_id` / `artifact_ref` / `content_hash` / `idempotency_key`
   必须与不可变 intent 一致；不一致 → `ActionPublishRequestNotBoundError(action_id, field)`，
   **无 Gateway 调用、无 receipt**。
3. 完整 publish judgers 仍在 Gateway 之前运行，投影源改为 request.content 的 body 形态
   （title/body/hashtags/image_paths），不是跳过检查。
4. 未传 request 时行为完全不变（artifact 读取 + hash 校验），旧路径与全部既有测试不动。
5. request 的 `content` 允许携带主链执行期事实（如生成的封面路径）；绑定的是 intent 的
   `content_hash`（审批内容），不是重算后的执行内容——文档记录该边界。

## 3. 测试

- `test_a_bound_request_is_dispatched_instead_of_the_artifact_body`：artifact 指向
  `/tmp/a.png`，supplied request 指向 `/tmp/generated-cover.png`；断言 dispatcher 收到后者。
- `test_a_request_that_does_not_bind_is_refused_before_the_gateway`：account 不符 →
  typed error、dispatcher 0 次、无 receipt。

## 4. 结果（2026-11-01）

- [x] seam + 绑定校验 + judgers 投影
- [x] 2 个新用例；creator_agent 233 passed
- [x] 全量结果见 notes

## 5. 不做什么

- 不改 mainline dispatch（B3 接线下一票）；不把 request 暴露到 HTTP API；不跳过凭据检查。
