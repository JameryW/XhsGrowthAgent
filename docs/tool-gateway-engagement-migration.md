# 互动能力迁入 Tool Gateway —— 规格草案（不接线）

**状态：spec only。** 本文不改变任何运行时行为，也不注册任何 capability。
落地顺序与前置条件见 §7，验收标准见 §8。

一句话结论：**现在不能接线。** 迁移本身是一小时的事，挡在前面的是三个已实测的
诚实性缺陷（§1）—— 先把一个会谎报成功的工具搬进 Gateway，等于给谎报装上统一的、
可追溯的外观。而且 `auth_scope` 挡不住 agent（§7.1 有实测依据），所以"先注册、
用 scope 兜住"这条路根本不成立。

---

## 1. 为什么迁：三个已实测的缺陷

不是"架构上更整齐"，是这三个缺陷现在就在生产路径上，且每一个都在
`docs/tool-runtime.md` 想消灭的那一类里 —— **归一化发生在第二个地方**。

### 1.1 DM 在没点发送的情况下报成功

`backend/services/xhs_engagement.py:413-418`：

```python
send_btn = await page.query_selector("text=发送, button.send-btn")
if send_btn:                      # 找不到按钮 → 跳过点击
    await self._paced(send_btn.click)
    await self._assert_safe_page(page)
note_dm_sent(self.account_id)     # 但配额照记
return {"success": True, "message_id": f"dm_{int(time.time())}"}
```

页面改版、按钮选择器失效、按钮被遮挡 —— 任何一种都会让这条链路**一条私信都没发出去，
却返回 `success: True`**，同时把当日配额扣掉一格。上层 `dm_handler` 再把它翻译成
`{"success": True, "reply_id": "dm_..."}`，回执看起来完全正常。

这不是边缘情况：`query_selector` 返回 `None` 本来就是"没找到"，被写成可选分支就等于
把"没找到"当成了"不需要"。

### 1.2 平台给出的结论被丢在工具层

`backend/services/xhs_engagement.py:198-204` 的 `_blocked_result` 明确带四个字段：

```python
{"success": False, "status": "blocked", "error_code": error_code, "error": message}
```

但 `backend/tools/xhs/engagement.py:98-105`（评论）与 `:154-161`（私信）只取三个：

```python
"success": result.get("success", False),
"reply_id": result.get("reply_id", ""),
"error": result.get("error", ""),
```

`status` 与 `error_code` 在这里被丢弃。后果是三种**语义完全不同**的结局，到了上层长得
一模一样：额度用尽（`error_code=quota`）、风控暂停（`risk_control`）、CDP 被别的功能
占着（`cdp_busy`）、页面没找到评论。前两种是终局（不该重试，重试还会烧额度），后两种
是暂时（等等可以）。现在它们都只是 `success: False` 加一句中文。

### 1.3 异常在工具层被归一化成业务字典

`backend/tools/xhs/engagement.py:107-113` 与 `:163-169`：

```python
except Exception as e:
    logger.error(f"回复评论失败: {e}")
    return {"comment_id": comment_id, "success": False, "error": str(e)}
```

Gateway 只能看到"一次成功返回的调用，值是 `success: False`"（`ok=True`）。于是
**传输失败与平台拒绝无法区分**，而 Gateway 的重试、超时、`degraded`、trace 全部建立在
`ok` / `error_kind` 上。这正是 `backend/tools/xhs/publisher.py` 已经拆掉的那层
（该文件 docstring：*"归一化只在 Gateway 一个归属地"*）。

边界要说清：全仓 `backend/tools/` 里还有四处 `except Exception`，但只有这一对是
**有副作用的写操作 + 吞掉平台判决**：

| 位置 | 形状 | 是否同一类问题 |
|---|---|---|
| `backend/tools/xhs/engagement.py:107-113` / `:163-169` | 返回业务字典，丢弃 `status`/`error_code` | **是**，且是写操作 |
| `backend/tools/ripple/integration.py:178-180` | `return {"error": str(e)}` | 是同一形状（S3c 修过它的孪生），但只读、无副作用 |
| `backend/tools/analysis/topic_scorer.py:176-180` | 返回基础评分兜底 | 不是：显式降级，产出的是真值 |
| `backend/tools/content/de_ai_taste.py:222-224` | 回退到算法路径 | 不是：同上 |
| `backend/tools/xhs/analytics.py:105-107` / `:122-124` | `except: pass` | 不是同一类：静默忽略可选数据，不影响返回值真假 |

### 1.4 顺带：`message_id` 不是身份，是时钟

`f"dm_{int(time.time())}"`（`backend/services/xhs_engagement.py:418`）。它不含平台任何回执，重复发送
与真实发送产生的是**同一形态**的 id，且同一秒内两次调用会撞。任何以它为幂等键或
对账依据的账本都会立刻失效。迁移时这条必须改成"平台回显，否则空"。

---

## 2. 现状与目标形态

| | 现在 | 迁移后 |
|---|---|---|
| 调用方式 | agent 直接持有 `@tool` 函数 | `gateway.invoke("xhs.comment_reply", payload)` |
| 超时 | 无（`XhsLoginSession` 那套不覆盖互动） | `_ENGAGEMENT_SAFETY_NET_S`，见 §6 |
| 重试 | 无（调用方自己 `try`） | `RetryPolicy(max_attempts=1)`，见 §3.3 |
| 权限 | 无声明 | `auth_scope`，但**不构成防线**，见 §7.1 |
| 归一化 | 工具层 + 服务层两处 | 只在 Gateway（工具抛，服务给结论） |
| 平台结论 | 丢弃 `status`/`error_code` | `DomainOutcome`，含全部判决字段 |
| 幂等 | 无 | 内容级键 + Effect 账本，见 §4 |
| 可观测 | 无 trace | Gateway trace 事件（`kind: "tool"`） |

---

## 3. 两个 capability 的 spec 草案

```python
_ENGAGEMENT_SAFETY_NET_S = 300.0        # 见 §6

ToolSpec(
    capability="xhs.comment_reply",
    summary="回复一条小红书评论（写操作）",
    side_effect=SideEffect.SIDE_EFFECTING,
    latency=LatencyClass.SLOW,
    cost=CostClass.CHEAP,
    pass_style=PassStyle.INVOKE,        # 两个都是 LangChain @tool
    retry_policy=RetryPolicy(),         # 1 次，见 §3.3
    timeout_s=_ENGAGEMENT_SAFETY_NET_S,
    auth_scope=("xhs:write",),          # 见 §3.1：不是不想细分，是分不出来
    max_concurrency=1,
)

ToolSpec(
    capability="xhs.dm_send",
    summary="发送一条小红书私信（写操作，冷启动外发风险最高）",
    side_effect=SideEffect.SIDE_EFFECTING,
    latency=LatencyClass.SLOW,
    cost=CostClass.CHEAP,
    pass_style=PassStyle.INVOKE,
    retry_policy=RetryPolicy(),         # 1 次：重试的代价是骚扰真人
    timeout_s=_ENGAGEMENT_SAFETY_NET_S,
    auth_scope=("xhs:write",),          # 同上
    max_concurrency=1,
)
```

### 3.1 为什么 auth_scope 只能是 `xhs:write`

第一版草案写的是 `xhs:engagement:write` / `xhs:dm:write`，看起来更细，实测后撤回了。
原因只有一个：**这个仓库里唯一的 scope 来源不能表达这种区分。**

`backend/services/xhs_credentials.py:130-145`：

```python
@property
def scopes(self) -> tuple[str, ...]:
    if not self.usable:
        return ()
    return (XHS_READ_SCOPE, XHS_WRITE_SCOPE)   # 读+写一起给，且是有意为之
```

即 scope 是**凭证可用性**推导出来的，"这个账号登录着"就同时拿到读与写。于是新造一个
`xhs:engagement:write` 只有两种结局：

- 不扩 `XhsCredential.scopes` → 没有任何调用方持有它 → scope 检查**永远拒**（fail-closed，
  等于把能力静默关掉）；
- 扩进去 → 任何有可用 cookie 的账号都持有它 → **零区分度**。

两者都不是防线，所以不写。真正的"评论回复/私信 与 发布 不是同一档权限"需要一张
**按账号的策略表**（谁被允许主动触达谁），那是一个独立的数据模型，不在本 spec 内 ——
见开放问题 §9.5。现在诚实的声明就是"需要写权限"，别再叠一层看起来更安全的空壳。

### 3.2 为什么 `max_concurrency=1`

服务层已经有 `self._guard.lock`（进程内）与 CDP 锁
（`backend/services/cdp_session_lock.py`：进程内 `asyncio.Lock` + PG advisory lock，
PG 不可用时降级为进程内）。CDP 锁已经提供了**跨进程**的每账号互斥，所以
`max_concurrency` 不是在补它的漏洞，而是在 Gateway 层把"同一能力不并发"变成
**声明**而不是**约定** —— 与 `docs/tool-runtime.md` 开篇的理由一致。

诚实边界：Gateway 的信号量是**进程级**且**全账号共用**。多 worker 部署下它不是
"每账号 1 个"，而是"每进程 1 个"。真正的每账号互斥仍归 CDP 锁，别把两者混为一谈。

### 3.3 为什么 `max_attempts` 保持 1

与 `backend/tools/runtime/catalog.py:647-655` 对 `xhs.publish` 的理由逐字同构，且更重：一次 Gateway 超时是
在浏览器**提交动作进行中**取消调用，调用方无法区分"提交前失败"与"提交了但答复丢了"。
重试后者 = 给同一个真人发两条一样的私信。`requires_idempotency_key=True` 只满足
`ToolSpec` 的构造前置条件，**它不回答重试真正要回答的问题**。等 §5 的和解路径存在，
且能在重试前读回真实状态，才谈 `max_attempts=2`。

---

## 4. 幂等键：平台没有幂等 API，所以键本身不防重

小红书没有可用的幂等提交接口。因此键的用途必须写清楚，否则会得到一种很危险的错觉：

| 只有键 | 键 + Effect 账本 |
|---|---|
| 同一次重试可被识别 | 提交前能查到"这个键已经发过"并**拒绝** |
| 但不阻止第二次提交 | 提交后能记录结果，`unknown` 能被和解 |

### 4.1 键怎么算

从**效果**算，不从请求算：

```
eng:{kind}:{account_id}:{target_id}:{sha256(reply_content)[:16]}
```

- `kind` ∈ `comment_reply` / `dm`
- `target_id` = `comment_id`（评论回复）或 `sender_id`（私信）
- 内容摘要而不是全文：键要能进唯一索引，且正文不该常驻账本

为什么不是 per-attempt 的 uuid：uuid 每次尝试都不同，"同一次效果被提交两次"在账本里
表现为两条互不相干的记录，恰好是键唯一能提供的那点保护也消失了。
这个选择与 `creator_agent.execution.PublishRequest` 用 `content_hash` 而非请求 id 是
同一族做法（`backend/creator_agent/execution.py:104-113`）。

---

## 5. Effect 账本

### 5.1 记录什么

提交**之前**写 intent 行（这是关键：先记账再动手，崩在中途才有据可查）：

| 字段 | 说明 |
|---|---|
| `idempotency_key` | §4.1，唯一索引 `(account_id, idempotency_key)` |
| `capability` | `xhs.comment_reply` / `xhs.dm_send` |
| `target_id` | 评论 id / 收件人 id |
| `payload_digest` | 正文摘要（不存正文） |
| `thread_id` / `approved_by` / `approved_at` | 谁批的，见 §7.2 |
| `state` | 见 §5.2 |

表形态复用 `backend/db/creator_agent.py` 的 `UNIQUE (account_id, idempotency_key)`
（`:116-122`）—— 同一份库里已有先例，不必发明第二套。

### 5.2 四态

| state | 含义 | 可重试 |
|---|---|---|
| `intent` | 已登记，尚未提交 | 否（先和解，见下） |
| `committed` | 平台回显了回执（评论 id / 平台消息 id） | 否 |
| `refused` | 平台给了终局判决（额度、风控、blocked） | **否**，重试会烧额度 |
| `unknown` | 提交动作已发出，答复丢失 | **否**，必须先读回 |

`intent` 与 `unknown` 的区别：`intent` 是"我们还没提交"，`unknown` 是"可能提交了"。
前者可以在确认没提交后继续，后者只能读回。

### 5.3 `unknown` 只能在读回之后才离开

读回 = 拉一次目标对象的真实状态（笔记评论区 / 私信会话）；命中则 `resolved_sent`,
未命中则 `resolved_not_sent`。这是 `unknown` 唯一的出口，也是它**不自动重试**的原因。

诚实边界：读回接口的存在性是本 spec 的前提之一（开放问题 §9.2）。如果某个方向读不
回来，那么那一侧的 `unknown` 就是**终局**，必须报给人 —— 而不是"等等再试"。

### 5.4 什么才算回执

只有**平台回显**的 id 才算。`dm_{timestamp}` 这类本地生成的 id 一律记
`receipt = ""` + `receipt_source = "synthetic"`，并且**永远**不能作为 `committed`
的依据。这一条直接对应 §1.4。

---

## 6. 超时：`_ENGAGEMENT_SAFETY_NET_S = 300`

推导（全部取自代码，可复核）：

| 组成 | 取值 | 出处 |
|---|---|---|
| CDP 锁获取 | 120s 默认（`XHS_CDP_ENGAGEMENT_LOCK_TIMEOUT_S`） | `backend/services/xhs_engagement.py:222-227` |
| 元素等待 | 10s + 5s | `xhs_engagement.py:305, 330` |
| 每个浏览器动作的冷却 | 5s 默认（`XHS_ENGAGEMENT_COOLDOWN_SECONDS`） | `backend/services/xhs_engagement.py:90-97` |
| 一次回复的动作数 | ≤ 6（goto / 查询 / fill / click / 断言 ×2） | `backend/services/xhs_engagement.py:301-305` |
| **合计上界** | **≈ 165s** | |

`LatencyClass.SLOW` 的默认 120s **小于**工具自身预算，会取消一次仍在合法进行的提交，
并为一个可能已经发生的副作用报超时 —— 与 `_PUBLISH_SAFETY_NET_S = 900`
（`backend/tools/runtime/catalog.py:84-92`）是同一个形状。安全网必须**严格大于**工具自身预算，否则它交付的
答案比它抢占的那次更差。300s 对 165s 上界留 1.8 倍余量。

---

## 7. 授权：`auth_scope` 不是防线

### 7.1 实测：scope 只在**唯一一条**调用路径上生效

`backend/tools/runtime/gateway.py:200-206`：

```python
def _check_scopes(self, spec: ToolSpec, granted: tuple[str, ...] | None) -> None:
    """No ``granted_scopes`` means "not checked here" (S3+ passes them)."""
    if granted is None or not spec.auth_scope:
        return
```

不传 `granted_scopes` = 不检查。全仓 `backend/` 里只有一处会解析并传入它 ——
`backend/creator_agent/execution.py:328-339` 的 `gateway_publish_dispatcher`：

```python
scopes = granted_scopes
if scopes is None:
    scopes = await (scope_resolver or resolve_scopes)(request.account_id)
```

而另一条发布路径 `backend/agents/publisher.py:735` 是这样的：

```python
tool_result = await runtime.tools.invoke("xhs.publish", payload, thread_id=...)
```

没有 `granted_scopes`。**所以连 `xhs.publish` 已经落地的那条 `auth_scope`，在 agent
这条路径上也是不检查的** —— 这不是互动工具的问题，是 scope 机制当前的覆盖面。

结论不变，但依据更硬：**注册即触达。** 把互动能力加进 `build_registry()` 的那一刻，
任何一处 `self.tools.invoke("xhs.dm_send", ...)` 都能调到它，而 scope 检查是调用方
**可选**的，不是一个会拦住你的门。所以"先注册、用 scope 兜住"这条路不成立 ——
**注册顺序不是实现细节，它就是安全边界**，必须等 §7.2 的前置条件满足。

### 7.2 `human_confirmed` 不能变成 payload 里的一个 bool

`backend/services/xhs_engagement.py:392` 的冷启动外发闸门依赖调用方传入 `human_confirmed=True`。
一个 bool 由调用方自己声明，正是审批闸门的前提不能被信任的形态；Gateway 也没有
"审批"这个概念，`auth_scope` 表达的是"这个主体有这类权限"，不是"这一条被批过"。

提案：审批作为**调用前置条件**由操作员路径完成，并把结果写进 §5.1 的账本 intent 行
（`approved_by` / `approved_at`）。Gateway 侧不新增字段 —— 它不该成为审批状态的存储。

### 7.3 落地两段

**Phase A（不改变可及面）** —— 修 §1 的四个缺陷，全部可独立测试：

1. 找不到发送按钮 → 不允许 `success: True`（必须是明确的失败，带可判别的 kind）
2. `status` / `error_code` 透传到调用方，`quota` / `risk_control` 被识别为终局
3. `reply_id` / `message_id` 只来自平台回显，本地生成一律置空 + `receipt_source`
4. 异常不再在工具层归一化成业务字典（判据：工具层退出后没有 `except Exception` 返回值）

Phase A 里必须同时钉住：`note_dm_sent`（配额记账）只在**确认发出**之后调用。

**Phase B（注册）** —— 前置：§5 账本 + §7.2 审批闸门 + Phase A 全绿。注册后 agent
才第一次能调到它们，这一刻才是 `docs/agent-os-upgrade-2026q4.md` §4.1 所说的
"可及的外部副作用面发生变化"。

---

## 8. 验收标准

Phase A（每条都能写成一条测试）：

| # | 判据 |
|---|---|
| 1 | 发送按钮选择器失配时，返回的结局不是成功，且配额计数不变 |
| 2 | `quota` / `risk_control` 的 `error_code` 到达调用方，且被标为不可重试 |
| 3 | 无平台回显时 `reply_id == ""` 且 `receipt_source == "synthetic"` |
| 4 | 服务层抛异常时工具层**抛出**，不再返回业务字典（Gateway 才能给出 `error_kind`） |
| 5 | `human_confirmed` 缺省时冷启动外发被拒（钉住现有闸门，防迁移时丢） |

Phase B（在 A 之上追加）：

| # | 判据 |
|---|---|
| 6 | 同一 `idempotency_key` 第二次调用在**提交前**被拒绝，账本可查 |
| 7 | 超时后账本状态为 `unknown`，且不自动重试 |
| 8 | `unknown` 只能经读回变为 `resolved_sent` / `resolved_not_sent` |
| 9 | Gateway trace 事件里 `side_effect == "side_effecting"`，且不含正文 |

---

## 9. 开放问题（需拍板）

1. **DM "结果不明"该报 `DomainOutcome("unknown")` 还是让网关超时？**
   `publisher.py` 选了前者（平台给出了"提交了但结果不明"这个判断），而互动这边
   超时发生在浏览器动作中途，平台层未必有机会给结论。倾向：能在服务层判定的报
   `DomainOutcome`，判不了的交给网关超时并进 `unknown`。
2. **读回接口存在吗？** 笔记评论区可以读；私信会话能否列出自己发过的消息，需要在
   真实账号上验证一次。**这是 §5.3 的唯一前提**，没有它，私信侧 `unknown` 就是终局。
3. **每账号并发上限要不要进 DB？** 现在 `max_concurrency` 是进程级信号量，多 worker
   下退化。CDP 锁已经是 PG advisory（跨进程），是否让账本/信号量也走 DB，取决于
   部署形态。
4. **本轮是否允许 agent 触达？** 本文建议：不允许。§7.1 已经证明注册即触达。
5. **要不要一张按账号的策略表？** §3.1 的结论是当前 scope 只能表达"这个账号登录着"，
   表达不了"这个账号被允许主动私信谁"。真要做区分，需要一个策略源（谁被允许触达、
   每账号每日上限、是否只允许应答式触达），并把 `XhsCredential.scopes` 从"凭证推导"
   改成"凭证 ∧ 策略"。这是一个独立的数据模型，建议单开一票。
6. **`backend/agents/publisher.py:735` 那条路径要不要补 `granted_scopes`？** 它现在是
   `xhs.publish` 的唯一 agent 入口，不传 scope。补上会让已声明的 `auth_scope` 真正生效，
   但也可能在缺少凭证解析的部署上把发布整条关掉（fail-closed）。属于独立缺陷，建议单开。
