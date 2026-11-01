# P3a：主链发布执行载荷接入共享 `PublishRequest`（票 5be）

> 上下文：P3 要把主链/retry/free 三条 `run_publish` 直调接到控制面执行器。
> 切换前必须消灭「两份载荷字段表」：主链今天在 `run_publish` 里手写
> `xhs.publish` 的 payload，控制面执行器则用 `creator_agent.execution.build_publish_payload`。
> 本票让两者共用同一份定义（P3 的**前置切片**），不改变执行入口。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 控制面 dispatcher 已在生产路径 | `creator_agent/execution.py`：`gateway_publish_dispatcher` → Gateway `xhs.publish` |
| 主链也经 Gateway，但自建 payload 字典 | `backend/agents/publisher.py` 的 `run_publish`（`is_private`/`scheduled_time`/`cdp_endpoint` 手写） |
| 主链 payload 的这三项是控制面 intent 里没有的 workflow 事实 | 同文件 `_normalize_scheduled_time` / `_resolve_cdp_endpoint` / `plan` |
| 共享 request 只有控制面需要的 6 个字段 | `PublishRequest`（account/thread/idempotency/artifact/content_hash/content） |
| 三条直调点 | `publisher.py`（node）、`api/routes/_wf_actions.py`（retry）、`api/routes/free.py`（free） |

## 2. 决定（locked）

1. `PublishRequest` 增加三个**带默认值**的主链侧事实：`private: bool | None = None`、
   `scheduled_time: str = ""`、`cdp_endpoint: str = ""`。控制面请求保持默认。
2. `build_publish_payload`：`cdp_endpoint` 取 `request.cdp_endpoint or 参数`；`private`
   非 None 才输出 `is_private`；`scheduled_time` 非空才输出 —— 控制面载荷键集合逐字段不变。
3. `gateway_publish_dispatcher`：request 自带 endpoint 时优先使用、不再调用 resolver
   （避免同账号解析两次/漂移）；账户为空时行为不变。
4. `run_publish` 改为构造 `PublishRequest` + `build_publish_payload` 得到 payload，
   仍调用 `runtime.tools.invoke`（执行入口本阶段不变）。
5. **claim 不变**（直调仍 3）；本票只统一请求/载荷定义，P3b 才换执行入口。

## 3. 要求

1. `backend/creator_agent/execution.py`：request 字段 + payload 条件键 + dispatcher endpoint 优先级。
2. `backend/agents/publisher.py`：共用 builder，删除手写 payload 字典（保留内容/封面/endpoint 解析）。
3. 测试：
   - 控制面 payload 键集合不变；主链 request 三个事实出现在 payload；
   - request endpoint 优先、resolver 不被调用；
   - 主链路载荷来自共享 builder（title/body/images/account/idempotency/is_private/endpoint，
     空 `scheduled_time` 省略，工具默认值相同）。
4. 文档：`docs/publish-action-protocol.md` P3 段落记录 P3a 落地与 P3b 剩余范围；claim 仍 3。
5. 验证：定向 + 全量 + ruff 绿。

## 4. 结果（2026-11-01）

- [x] 共享 request/payload；控制面键集合不变（测试）
- [x] 主链复用 builder，主链侧事实留在 request 上
- [x] endpoint 优先级测试（resolver 不被调用）
- [x] claim 仍 3（本票不动执行入口）；全量见 notes

## 5. 不做什么

- 不切三条直调（P3b）、不动 `EffectLedger` 六态/幂等语义、不改公开 API。
