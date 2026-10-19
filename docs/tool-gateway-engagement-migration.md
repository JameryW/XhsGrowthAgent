# 互动能力迁入 Tool Gateway —— 规格草案（不接线）

**状态：Phase A 已落地，仍未接线。** 本文不注册任何 capability；§1 的四个缺陷已修
（PR #684），本文保留它们修前的形态作为证据，并在每节末尾写明修后契约与守护测试。

一句话结论：**仍然不能接线。** 迁移本身是一小时的事，剩下的挡路项是 Effect 账本与
审批闸门（§5、§7.2）—— 先把一个会谎报成功的工具搬进 Gateway，等于给谎报装上统一的、
可追溯的外观。而且 `auth_scope` 挡不住 agent（§7.1 有实测依据），所以"先注册、
用 scope 兜住"这条路根本不成立。

---

## 1. 为什么迁：四个已实测的缺陷（Phase A 已修）

不是"架构上更整齐"，是这四个缺陷当时就在生产路径上，且每一个都在
`docs/tool-runtime.md` 想消灭的那一类里 —— **归一化发生在第二个地方**。

下表是修前 → 修后的对照，细节在 §1.1–§1.4：

| # | 修前 | 修后 |
|---|---|---|
| 1 | DM 找不到发送按钮 → 跳过点击、照记配额、返回 `success: True` | `status=failed`、`error_code=send_button_missing`、不记配额 |
| 2 | 平台 `status`/`error_code` 在工具层被丢 | 原样透传，且 `retryable` 由错误码一次推出 |
| 3 | 工具层 `except Exception` → 业务字典（Gateway 看到 `ok=True`） | 异常原样抛出，归一化只在 Gateway |
| 4 | `reply_<ts>` / `dm_<ts>` 冒充回执 | `receipt_id` 只来自平台回显，无回显即空 |

### 1.1 DM 在没点发送的情况下报成功

`backend/services/xhs_engagement.py`（修前，该段已删除）：

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

**修后**：`backend/services/xhs_engagement.py:594` 起，按钮缺失直接返回
`FAILED` + `send_button_missing`；配额改由 `send_dm` 读判决后记账，只在
`status ∈ {sent, unknown}` 时增加。守护：
`tests/unit/services/test_xhs_engagement_verdicts.py::TestDirectMessageVerdicts::test_a_missing_send_button_no_longer_reports_success`。

### 1.2 平台给出的结论被丢在工具层

`_blocked_result`（修前形态）明确带四个字段：


```python
{"success": False, "status": "blocked", "error_code": error_code, "error": message}
```

但两个工具（修前）只取三个字段：

```python
"success": result.get("success", False),
"reply_id": result.get("reply_id", ""),
"error": result.get("error", ""),
```

`status` 与 `error_code` 在这里被丢弃。后果是三种**语义完全不同**的结局，到了上层长得
一模一样：额度用尽（`error_code=quota`）、风控暂停（`risk_control`）、CDP 被别的功能
占着（`cdp_busy`）、页面没找到评论。前两种是终局（不该重试，重试还会烧额度），后两种
是暂时（等等可以）。现在它们都只是 `success: False` 加一句中文。

**修后**：两个工具直接把服务层判决原样透出（`status` / `error_code` / `retryable`
一个不少），只额外回显请求身份。`retryable` 由 `_TRANSIENT_ERROR_CODES` 一次推出，
**默认不可重试** —— 说不清原因的错误码不该被自动重放。守护：
`tests/unit/services/test_xhs_engagement_verdicts.py::TestRetryabilityIsDerivedOnce`。

### 1.3 异常在工具层被归一化成业务字典

两个工具（修前）都有这段：

```python
except Exception as e:
    logger.error(f"回复评论失败: {e}")
    return {"comment_id": comment_id, "success": False, "error": str(e)}
```

Gateway 只能看到"一次成功返回的调用，值是 `success: False`"（`ok=True`）。于是
**传输失败与平台拒绝无法区分**，而 Gateway 的重试、超时、`degraded`、trace 全部建立在
`ok` / `error_kind` 上。这正是 `backend/tools/xhs/publisher.py` 已经拆掉的那层
（该文件 docstring：*"归一化只在 Gateway 一个归属地"*）。

**修后**：两个工具不再捕获任何异常，只在 `finally` 里关会话；异常原样向上传。守护：
`tests/unit/tools/test_xhs_engagement_tool_contract.py::TestCommentReplierPassesTheVerdictThrough::test_an_exception_is_no_longer_turned_into_a_dict`。

边界要说清 —— Phase A 之后，全仓 `backend/tools/` 剩下的 `except Exception` 没有一处
还是"有副作用的写操作 + 吞掉平台判决"：

| 位置 | 形状 | 是否同一类问题 |
|---|---|---|
| ~~`backend/tools/xhs/engagement.py`~~ | 返回业务字典，丢弃 `status`/`error_code` | **已修（Phase A）** |
| ~~`backend/tools/xhs/engagement.py:261`~~ | `fetch_pending_comments` 异常返回 `[]` | **已修（2026-10-19）**。比"异常信息不好看"严重得多：那一步在无 cookie 时**根本不抛异常**（`get_comments` 见 `_http is None` 直接 `return []`），所以这个审核队列工具**恒定**回答"没有待办"，而评论一条都没读过。现在守卫在 `try` 内、读失败即抛，`[]` 只表示"读到了，确实没有"。守护：`TestTheModerationQueueRefusesToSayEmpty` |
| `backend/tools/ripple/integration.py:178-180` | `return {"error": str(e)}` | 是同一形状（S3c 修过它的孪生），但只读、无副作用 |
| ~~`backend/tools/analysis/topic_scorer.py`~~ | 返回基础评分兜底 | **已修（2026-10-19）**，并且**本行原先的判断是错的**：它把这处写成"显式降级，产出的是真值"。`heat_score=50` / `potential_score=25.0` 是 `except` 分支里的两个常量，没有任何标定，strategist 把它当平台数据写进了 prompt |
| `backend/tools/content/de_ai_taste.py:222-224` | 回退到算法路径 | 不是：改名回退，产出仍由算法算出 |
| `backend/tools/xhs/analytics.py:105-107` / `:122-124` | `except: pass` | 不是同一类：静默忽略可选数据，不影响返回值真假 |

### 1.4 顺带：`message_id` 不是身份，是时钟

`f"dm_{int(time.time())}"`（修前，评论侧另有 `f"reply_{int(time.time())}"`）。它不含平台任何回执，重复发送
与真实发送产生的是**同一形态**的 id，且同一秒内两次调用会撞。任何以它为幂等键或
对账依据的账本都会立刻失效。

**修后**：两个能力都只报 `receipt_id`（仅平台回显）+ `receipt_source`，本地标识改名为
`correlation_id` 并注明"不是回执"。评论路径的 `verified=True` 来自 DOM 里 `.reply-item`
出现；私信没有读回，所以 `verified` 恒为 `False` —— 点击只是"已提交"，不是"已送达"。
守护：
`test_a_confirmed_reply_is_sent_but_carries_no_receipt` /
`test_a_clicked_send_is_sent_but_unverified`。

### 1.5 原先还剩的同类实例（Phase A 未覆盖）—— 现已清零（2026-10-19）

| 位置 | 形状 | 现状 |
|---|---|---|
| ~~`backend/services/xhs_client.py` 的 `get_direct_messages`~~ | 拉取私信时逐条套 `message_id=f"dm_{int(time.time())}"`，同一秒内所有消息拿到**同一个 id** | **已删（2026-10-19）**：它和 `reply_to_comment` / `send_dm` / `publish_post` 四个方法在本仓**没有任何调用者**、也没有测试（连同载荷数据类 `XHSPost` / `XHSDirectMessage` 一起删）。真正被用的是 `XHSEngagement.send_dm` / `reply_to_comment`，返回完整判决 —— 与被删的两个是不同类的同名方法。时钟 id 的缺陷随死代码一起消失，而不是被修好 |
| ~~`backend/services/xhs_client.py` 的 `send_dm`~~ | 把判决压成 `bool` | 同上：死路径被删。`use_browser=False` 时那半边还返回 `{"post_id": "", "status": "disabled"}` 这种**结果形状**的答案描述"功能没开"，调用方分不清它和"发出去了没拿到 id" —— 这是删它而不修它的另一个理由 |
| ~~`backend/tools/xhs/engagement.py:261`~~ | 读失败返回 `[]` | **已修（2026-10-19）**，见 §1.3 上方的表。同一个修复还去掉了它底下那层 `XHSClient.get_comments` 的同类兜底，否则只修工具是装饰 |

"清死代码"不再是留给 Phase B 的话：`chore/remove-dead-xhs-client-paths`（2026-10-19）
把整段 Playwright 半边删了。顺带修掉第 6 例「失败=数据」—— `get_post_analytics`
的 `except` 里**没有** `return <literal>`，只是落到 `try` 之后的
`return XHSAnalytics(post_id=...)`（零值对象 = "这篇 0 浏览"），**AST 扫描看不见**
（`tests/unit/tools/runtime/test_silent_fallbacks.py` 的 `TestKnownBlindSpots`
钉住该盲区）；守它的是行为测试 `test_get_post_analytics_*`，现在无 cookie 与读失败
都改为失败即抛，因为 `XHSAnalytics` 的零值本身就是一句关于帖子的话，没有中性的
"空"可退。

**服务层剩下的 5 处同类兜底已改成可数的账**，不再靠人记：
`tests/unit/tools/runtime/test_silent_fallbacks.py` 用 AST 扫 `@tool` 与
`XHSClient` 的每个方法，把"`except` 里 return 字面量"的位置钉成两张表。删一处、
加一处都会让那条测试变红。判据是**字面量**而不是"有没有 except"：handler 是
因为调用失败才进的，它交回的值不可能是对那个问题的回答。

**服务层的同类兜底已清零**（2026-10-19）：原 5 处（`get_trending` / `search_posts` /
`search_users` / `get_user_info` / `get_user_notes`）全部改为失败即抛。其中三处曾经被
`test_xhs_client_blogger.py` 的 `test_*_error_returns_empty` **断言**"出错返回空" ——
那不是"没人验证所以不动"，是**一份把谎话写进契约的测试**；这次连那三条测试一起改成
`test_*_error_propagates`，契约本身是被改动的对象。顺带修掉一个更深的：`get_user_notes`
自动翻页，中途失败过去会表现为"结果偏少"（读成"这个博主笔记不多"），现单独立了
`test_get_user_notes_a_mid_pagination_failure_is_not_a_short_result`。

`monitor_keywords` 的逐词吞异常也一并去掉：它把失败的词**整个从结果里丢掉**，于是
五个词失败两个会以三行到达，读作"只监控了三个"。"一个词坏不该拖垮整批"是真政策，
但那是**调用方**的政策，调用方可以自己按词 catch 并把失败行留在自己的答案里；
在服务层再放一个更安静的归一化器，正是这一层与 Gateway 当初对不上账的原因。

---

## 2. 现状与目标形态

| | Phase A 之后 | 迁移后 |
|---|---|---|
| 调用方式 | agent 直接持有 `@tool` 函数 | `gateway.invoke("xhs.comment_reply", payload)` |
| 超时 | 无（`XhsLoginSession` 那套不覆盖互动） | `_ENGAGEMENT_SAFETY_NET_S`，见 §6 |
| 重试 | 无，但判决自带 `retryable` | `RetryPolicy(max_attempts=1)`，见 §3.3 |
| 权限 | 无声明 | `auth_scope`，但**不构成防线**，见 §7.1 |
| 归一化 | 只在服务层给判决，工具层抛 | 只在 Gateway（工具抛，服务给结论） |
| 平台结论 | 透传 `status`/`error_code` + `retryable` | `DomainOutcome`，含全部判决字段 |
| 幂等 | 无 | 内容级键 + Effect 账本，见 §4 |
| 可观测 | `correlation_id` 可串日志 | Gateway trace 事件（`kind: "tool"`） |

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

`backend/services/xhs_credentials.py:223-230`：

```python
scopes: list[str] = []
if self.usable:
    scopes.append(XHS_READ_SCOPE)
if self.usable or self.profile_bound:
    scopes.append(XHS_WRITE_SCOPE)
    if self.outreach.allows_proactive:
        scopes.append(XHS_OUTREACH_SCOPE)
return tuple(scopes)
```

即 read / write 是**机制**推导出来的：读只有一条路（HTTP client，身份就是 cookie），
写有两条（走 HTTP 的评论/私信，或走 CDP 的账号自己的浏览器）。纯机制推导时，新造一个
`xhs:engagement:write` 只有两种结局：

- 不扩 `XhsCredential.scopes` → 没有任何调用方持有它 → scope 检查**永远拒**（fail-closed，
  等于把能力静默关掉）；
- 扩进去 → 任何有可用 cookie **或**已绑定 profile 的账号都持有它 → **零区分度**。

两者都不是防线。**票 5a 已经把缺的那张按账号的策略表补上了**（§9.5 第 5 条）：
`XhsOutreachPolicy`（谁被允许主动触达、每日主动上限、是否只允许应答式）随
`load_credential` 装进 `XhsCredential.outreach`，于是有了第三档
`xhs:outreach` = **机制 ∧ 策略** —— 这正是"评论/私信 与 发布 不是同一档权限"的
可表达形式。剩下没做的是把它挂到 capability 的 `auth_scope` 上：
`xhs.dm_send` 的 spec 仍声明 `("xhs:write",)`，因为策略检查今天发生在服务层
（`check_dm_target_allowed` + 入口的 `allows_engagement`），还没走到 Gateway 的
scope 检查。**别把 `xhs:outreach` 声明进任何 capability**，直到 Gateway 侧真有
调用方传 `granted_scopes` 并按它分支 —— 声明一个没人检查的 scope 就是 §9.5 第 6 条
那个洞的原样复发。

### 3.2 为什么 `max_concurrency=1`

服务层已经有 `self._guard.lock`（进程内）与 CDP 锁
（`backend/services/cdp_session_lock.py`：进程内 `asyncio.Lock` + PG advisory lock，
PG 不可用时降级为进程内）。CDP 锁已经提供了**跨进程**的每账号互斥，所以
`max_concurrency` 不是在补它的漏洞，而是在 Gateway 层把"同一能力不并发"变成
**声明**而不是**约定** —— 与 `docs/tool-runtime.md` 开篇的理由一致。

**票 5e 已落地（2026-10-20）**：闸门从「进程级、全账号共用的 `asyncio.Semaphore`」
改成**按账号分键的双层名额**（`backend/tools/runtime/account_gate.py`）：payload 带
`account_id` 时键为 `capability|account`（每账号一个天花板），不带则退回
`capability` 旧键；进程内信号量快路径 + PG advisory lock 计数名额
（每个名额一个 `pg_try_advisory_lock(8911, hashtext(f"{key}#{i}"))`，照 CDP 锁先例，
持锁连接占住整个在途、进程崩溃即自动释放），PG 不可用降级为进程内。等待有界：
名额等待吃 `effective_timeout_s` 的安全网窗口，等不到报
`ToolResult(ok=False, error_kind=timeout, attempts=0)` —— 调用从未开始，无副作用。

诚实边界（收窄后仍在的）：① PG 不可用就降级为进程内名额，多 worker 下每 worker
各自计数 ——「多 worker 不退化」以 PG 半边可用为前提，部署形态仍是前提；② 每个在途
占住一条池连接（与 CDP 锁同性质），池容量需覆盖并发在途数；③ **跨能力**的每账号
互斥仍归 CDP 锁，Gateway 名额只管单能力的每账号在途上限，别把两者混为一谈；
④ 账号识别是 payload 键约定（`account_id`），不是 schema 声明。

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

**已落地（票 5c，2026-10-19）**：`backend/db/engagement_effects.py`（PG 表 +
无池内存回退，`insert_or_get` 用 `ON CONFLICT DO NOTHING` + `RETURNING` 判定
created，`cas_update` 以 `expected_state` 为条件拒绝陈旧写）+
`backend/services/xhs_effect_ledger.py`（§4.1 键、`EngagementApproval`、六态状态机、
claim / 判决 / 读回 API）。接线进 `send_dm` / `reply_to_comment`：浏览器提交动作
之前 claim，判决之后记账（`tests/unit/services/test_xhs_effect_wiring.py` 用
"goto 那一刻行已在账本里"钉顺序）。

### 5.2 四态

| state | 含义 | 可重试 |
|---|---|---|
| `intent` | 已登记，尚未提交 | 否（先和解，见下） |
| `committed` | 平台回显了回执（评论 id / 平台消息 id） | 否 |
| `refused` | 平台给了终局判决（额度、风控、blocked） | **否**，重试会烧额度 |
| `unknown` | 提交动作已发出，答复丢失 | **否**，必须先读回 |

`intent` 与 `unknown` 的区别：`intent` 是"我们还没提交"，`unknown` 是"可能提交了"。
前者可以在确认没提交后继续，后者只能读回。

**落地状态（票 5c）**：实现按上表钉死，外加 §5.3 的两个读回出口
（`resolved_sent` / `resolved_not_sent`）和一个重臂迁移
（`resolved_not_sent → intent`：读回证明上一次没发出，同一逻辑效果才允许再试；
其余终态一律封死）。判决 → 账本状态的映射只有一处（
`state_for_engagement_verdict`），要点：**`sent` 无平台回执不进 `committed`**
（§5.4 的排除法：私信路径干净点击落 `unknown`；评论路径点完后的 DOM 复查算一次
内联读回，命中落 `resolved_sent`）；点击前明确失败
（`comment_not_found` / `*_input_missing` / `send_button_missing` / `configuration`）
落 `resolved_not_sent`（本地动作日志即"确认没提交"）。

诚实边界：`risk_control` 若发生在点击**之后**才弹拦截页，真实状态是"可能已发出"
（§3.3 的歧义）；当前按上表名单记 `refused` —— 与 `unknown` 一样堵重试（不会双发），
差别只在读回后能否重臂。`login_required` 不在名单内，落保守侧 `unknown`。
等 §9.2 读回能力落地后应复核 `risk_control` 这一档。

### 5.3 `unknown` 只能在读回之后才离开

读回 = 拉一次目标对象的真实状态（笔记评论区 / 私信会话）；命中则 `resolved_sent`,
未命中则 `resolved_not_sent`。这是 `unknown` 唯一的出口，也是它**不自动重试**的原因。

诚实边界：读回接口的存在性是本 spec 的前提之一（开放问题 §9.2）。如果某个方向读不
回来，那么那一侧的 `unknown` 就是**终局**，必须报给人 —— 而不是"等等再试"。

**落地状态（票 5c → 5d）**：出口模型已钉住 —— `record_readback` 是 `unknown` 唯一的
离开方式（`record_not_sent` 只可从 `intent` 离开，本地日志对 `unknown` 无话可说；
`tests/unit/services/test_xhs_effect_ledger.py::TestTheStateMachine` 钉死）。

**读回接口已落地（票 5d）**：`XHSEngagement.readback_comment_reply` /
`readback_dm`（拉目标真实状态，DOM 文本归一化匹配）+ `reconcile_effect`（正文
摘要对账后才动状态）。判决是**三值** `hit` / `miss` / `inconclusive`，不是二值 ——
安全不对称决定词汇量：**假 miss 会解锁重臂（同一效果再发一次 = 给同一个真人发
两条），假 hit 只是把键锁死（无双发）**。所以"读不到"（元素缺失/风控/空列表/
折叠未展开/条目读不出）一律 `inconclusive`，行原封不动；只有可枚举且非空的表面
上确实没有才 `miss`（`tests/unit/services/test_xhs_effect_readback.py` 钉住）。

诚实边界（§9.2 从"存在性"降级为"验证度"）：选择器是对页面结构的尽力读法（与
本模块其余部分同一诚实位）；**私信会话能否列出自己发过的消息尚未在真实账号上
验证**，验证前私信侧任何 `miss` 只能当"按当前 DOM 读法没看到"用 —— 对私信侧的
重臂要多一层人工复核。

### 5.4 什么才算回执

只有**平台回显**的 id 才算。本地标识一律不进 `receipt_id`：`receipt_id = ""` +
`receipt_source = "none"`，本地那个值放 `correlation_id`，并且**永远**不能作为
`committed` 的依据。这一条直接对应 §1.4；Phase A 已按此实现（不再有任何本地生成的
`reply_*` / `dm_*`）。

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

**已落地（票 5c，2026-10-19）**：`human_confirmed: bool` 已删除，换成
`EngagementApproval(thread_id, approved_by, approved_at)`（三字段非空校验 ——
半条记录就是那个 bool 换了个形状）。冷启动时 `check_dm_target_allowed` 在提交前
要求审批记录存在（`dm_unconfirmed`），记录进 intent 行；入站应答不需要逐条审批，
账本三列如实留空（不编造审批人）。工具层 `dm_handler` / `comment_replier` 改收
审批三件套参数。

### 7.3 落地两段

**Phase A（不改变可及面）—— 已落地（PR #684）** —— 修 §1 的四个缺陷，全部可独立测试：

1. 找不到发送按钮 → 不允许 `success: True`（必须是明确的失败，带可判别的 kind）✅
2. `status` / `error_code` 透传到调用方，`quota` / `risk_control` 被识别为终局 ✅
3. 回执只来自平台回显，本地生成一律置空 + `receipt_source` ✅
4. 异常不再在工具层归一化成业务字典（判据：工具层退出后没有 `except Exception` 返回值）✅

Phase A 里必须同时钉住：配额记账只在判决为 `sent` / `unknown` 之后调用 ✅
（`unknown` 也算，因为可能已经发出、收不回来 —— 见 §5.2）。

**Phase B（注册）—— 未开始** —— 前置三项已全部满足（§5 账本 ✅ 票 5c、§7.2
审批闸门 ✅ 票 5c、Phase A 全绿 ✅）。**仍未注册**：卡在 §9.4（本轮是否允许
agent 触达，需拍板）。注册后 agent 才第一次能调到它们，这一刻才是
`docs/agent-os-upgrade-2026q4.md` §4.1 所说的"可及的外部副作用面发生变化"。

---

## 8. 验收标准

Phase A（**全部已通过**）：

| # | 判据 | 守护测试 |
|---|---|---|
| 1 | 发送按钮选择器失配时，返回的结局不是成功，且配额计数不变 | `TestDirectMessageVerdicts::test_a_missing_send_button_no_longer_reports_success` / `TestCommentReplyVerdicts::test_a_missing_send_button_is_a_failure_not_a_success` |
| 2 | `quota` / `risk_control` 的 `error_code` 到达调用方，且被标为不可重试 | `TestCommentReplyVerdicts::test_a_quota_block_is_reported_with_its_own_code` / `TestRetryabilityIsDerivedOnce` |
| 3 | 无平台回显时 `receipt_id == ""` 且 `receipt_source == "none"` | `test_a_confirmed_reply_is_sent_but_carries_no_receipt` / `test_a_clicked_send_is_sent_but_unverified` |
| 4 | 服务层抛异常时工具层**抛出**，不再返回业务字典（Gateway 才能给出 `error_kind`） | `TestCommentReplierPassesTheVerdictThrough::test_an_exception_is_no_longer_turned_into_a_dict` |
| 5 | 无逐条审批记录时冷启动外发被拒，且**不触达浏览器** | `TestDirectMessageVerdicts::test_a_cold_target_without_confirmation_never_reaches_the_browser`（票 5c 起钉的是 `approval=None`，旧 `human_confirmed` 已删） |

第 3 条原文写的是 `receipt_source == "synthetic"`，实现时改成 `"none"`：既然我们
**不再生成**任何本地 id，"synthetic" 会描述一个不存在的东西。`"platform"` / `"none"`
两个值就够了；本地标识改叫 `correlation_id`，名字本身就说明它不是回执。

Phase B（在 A 之上追加）：

| # | 判据 | 状态 |
|---|---|---|
| 6 | 同一 `idempotency_key` 第二次调用在**提交前**被拒绝，账本可查 | ✅ 票 5c（`TestTheSameKeyIsRefusedBeforeASecondSubmit`） |
| 7 | 超时后账本状态为 `unknown`，且不自动重试 | ✅ 票 5c（映射表 + `max_attempts=1` 不动；`unknown` 无任何自动重试路径） |
| 8 | `unknown` 只能经读回变为 `resolved_sent` / `resolved_not_sent` | ✅ 票 5c（`TestTheStateMachine`；读回**接口**本身见 §9.2） |
| 9 | Gateway trace 事件里 `side_effect == "side_effecting"`，且不含正文 | ⏳ Phase B 注册后（§9.4 挂起） |

---

## 9. 开放问题（需拍板）

1. **DM "结果不明"该报 `DomainOutcome("unknown")` 还是让网关超时？**
   `publisher.py` 选了前者（平台给出了"提交了但结果不明"这个判断），而互动这边
   超时发生在浏览器动作中途，平台层未必有机会给结论。倾向：能在服务层判定的报
   `DomainOutcome`，判不了的交给网关超时并进 `unknown`。
2. **读回接口存在吗？** ~~笔记评论区可以读；私信会话能否列出自己发过的消息，需要在
   真实账号上验证一次。**这是 §5.3 的唯一前提**，没有它，私信侧 `unknown` 就是终局。~~
   **已落地（票 5d，2026-10-20）**：评论侧/私信侧读回接口都实现了（三值判决
   `hit`/`miss`/`inconclusive`，见 §5.3 落地状态）。降级为**验证度**问题：私信会话
   列自己消息的 DOM 读法尚未在真实账号上验证，验证前私信侧 `miss` 需人工复核才可
   重臂。
3. **每账号并发上限要不要进 DB？** 现在 `max_concurrency` 是进程级信号量，多 worker
   下退化。CDP 锁已经是 PG advisory（跨进程），是否让账本/信号量也走 DB，取决于
   部署形态。**已落地（票 5e，2026-10-20）**：要 —— 信号量改成按账号分键的双层
   名额（进程内 + PG advisory 计数名额，照 CDP 锁先例，PG 不可用降级进程内），
   多 worker 共享天花板，见 §3.2；账本侧在票 5c 已进 DB（`engagement_effects`）。
4. **本轮是否允许 agent 触达？** 本文建议：不允许。§7.1 已经证明注册即触达。
5. **要不要一张按账号的策略表？** ~~§3.1 的结论是当前 scope 只能表达"这个账号
   登录着 / 有自己绑定的浏览器"，表达不了"这个账号被允许主动私信谁"。~~ **已落地
   （票 5a，2026-10-19）**：`XhsOutreachPolicy` 三模式（`nobody` / `inbound_only`
   默认 / `confirmed_anyone`）+ `daily_proactive_cap`，解析优先级为
   账号行（带策略键即终局）→ 部署 env（含遗留全局开关 `XHS_ALLOW_OUTBOUND_DM`，
   映射为 `confirmed_anyone`）→ 安全默认（`inbound_only`, cap 0），**只朝限制方向
   失败安全**（reader 抛异常/坏值/未知 mode 全部落到更严）。`XhsCredential.scopes`
   已按"机制 ∧ 策略"出第三档 `xhs:outreach`（仅冷启动需要；应答式回复只吃
   `xhs:write`）。门禁 `check_dm_target_allowed` 改为 policy 驱动（DI 传入），
   旧的 `outbound_dm_allowed(account_id)`（签名撒谎：无视 account_id 读全局 env）
   已删除。**诚实边界**：①~~per-account 的 `dm_daily_limit` / `comment_reply_daily_limit`
   覆盖仍结构不可达~~ **已修（票 5b，2026-10-19）**：读者（`_policy_value`）本来就在查
   `_policies`，断在写侧/恢复侧/展示侧三面——`set_cooldown_policy` 的 `incoming`
   没有这两键、`_POLICY_FIELDS` 白名单（hydrate 恢复 + `get_cooldown_policy` 过滤）
   没有这两键、`global_cooldown_defaults` 也没有 ⇒ per-account 请求永远落到全局 env。
   现四面对齐（白名单/写入器/默认表/API `CooldownPolicyRequest`），配额门禁
   `check_dm_quota` / `check_comment_reply_quota` 立即按账号生效，覆盖跨重启存活
   （hydrate 往返有测试钉住）；②`xhs:outreach` 尚未挂进任何 capability 的
   `auth_scope`（见 §3.1 末段）；③策略表是进程内解析 + DB 读，没有管理界面/写路径，
   账号行策略需直接写 `account_credentials`。
6. **scope 到底该接在哪一层？**（原写作"agent 发布路径要不要补 `granted_scopes`"，
   实测后问题变大了，见下。）

   **实测（2026-10-19，由 `tests/unit/tools/runtime/test_scope_coverage.py` 复算）**：
   12 个 capability 里 **8 个声明了 `auth_scope`**，当时全仓**只有 1 个调用点**真的传
   `granted_scopes`（`backend/creator_agent/execution.py`）⇒ **7 个声明了 scope 的
   能力没有任何已检查的调用点**；`xhs.publish` 有两条路径，一条检查
   （`creator_agent`）、一条不检查（`backend/agents/publisher.py`）—— 后者已在 S5c 接上。

   **为什么不能直接把 `creator_agent` 的做法抄到 agent 路径**（当时的实测状态）：scope
   的唯一来源是 `XhsCredential.scopes`，它当时**只**由 cookie 可用性推导。
   而发布这条路径根本不用 cookie —— `backend/tools/xhs/publisher.py:30` 明确构造
   `XHSPublisher(cookie="")`，真正的提交走 CDP 连上已登录的 Chrome。于是：

   - `.env.example` 里 `XHS_COOKIE=` 是**空的**（它只是"可选项"，没有注释说发布需要它），
     真实发布靠 `XHS_CDP_*` + 已登录的浏览器；
   - 接上 scope 后，这类部署的 `usable=False` ⇒ `scopes=()` ⇒ agent 发布直接
     `PermissionDeniedError`，**而它今天能正常发出**。

   这不是 bug，是**两条口径打架**：声明说"发布需要凭证"，机制说"发布只需要一个已登录的
   浏览器"。

   **已定案：选项 A（让授权追上机制）**。理由是它同时保住了两样真东西 ——
   "授权不随 Chrome 进程启停翻转"（所以判绑定、不判可达），以及 `.env.example` 承诺的那
   套「空 cookie + CDP」部署。

   | 选项 | 做法 | 代价 |
   |---|---|---|
   | **A. 让授权追上机制**（已采用） | `XhsCredential` 增加 `profile_bound`，`scopes` 由"cookie ∨ 已绑定 profile"推导 | 授权定义域从"凭证"扩到"机制"，"可达性算不算授权"的旧论证要重写 |
   | B. 让机制追上授权（未采用） | 维持 cookie 推导，全线接线，同时把 `XHS_COOKIE` 写成发布的**硬前提**（文档 + 启动自检） | 依赖空 cookie + CDP 的现有部署会立刻发不出去，属破坏性变更 |

   **A 落地后的授权规则**（`backend/services/xhs_credentials.py:156-189`）：

   - `xhs:read` ⟸ cookie 可用。读只有 HTTP 这一条路，`XHSClient` 的身份就是 cookie。
   - `xhs:write` ⟸ cookie 可用 **∨** 账号已绑定浏览器 profile。发布走 CDP，评论/私信
     走 HTTP，两条路各自成立就够了。
   - **绑定 ≠ 可达**：`profile_bound` 只读账号行的 `cdp_port`（
     `backend/db/accounts.py:483` 的 `get_account_cdp_endpoint`），不建连接、不探测。
     "浏览器没开"仍由发布工具自己报 `cdp_unavailable`，而不是被 Gateway 说成"没被授权"。
   - 两个事实各自由自己那次读取决定：cookie 行读取失败仍然是 fail-closed（不回退部署
     身份），但**不会顺手抹掉** binding —— 绑定来自另一次成功读取，且属于这个账号本身。
   - **空 account_id 也有绑定**：具名账号读它自己的 `cdp_port`，空 account_id 读部署
     声明的 `XHS_CDP_ENDPOINT`（与 `XHS_COOKIE` 对称 —— 这就是"单账号部署"的意思）。
     少了这一半，`.env.example` 那套「空 cookie + 全局 CDP」的单账号部署仍然拿不到写权限，
     选项 A 就等于没落地。两者都只读**声明**，不探测浏览器是否在跑。
   - **授权说哪个浏览器，payload 就带哪个**：控制面发布此前不带 `cdp_endpoint`，靠工具的
     全局回落。grant 一旦可以由 binding 成立，这个回落就会让一个账号的授权跑在另一个账号的
     会话上，所以 `build_publish_payload` 补上了该字段（agent 路径早就按账号解析并传入）。

   **本轮已做（不动行为）**：trace 事件新增 `scopes: checked | unchecked | none`
   （`docs/tool-runtime.md` 有表），让"声明了但没检查"在日志里是一条可数的事实；
   覆盖面被测试钉成数字，债务不会再悄悄扩大。

   **接线（S5c）**：主链 `backend/agents/publisher.py:run_publish` 现在也解析并传入
   `granted_scopes`，且在幂等账本**之前**拒绝——一次没被授权的发布不该留下 prepared
   记录。归属跟**选中的账号**（`publish_options.account_id`）走，不跟
   `state["account_id"]` 这个从未被校验过的标签走；没有选中账号时，行为主体就是部署本身。

   覆盖面从 **1 → 2 个调用点**（都落在 `xhs.publish`），**"没有已检查调用点的能力"
   是 4 个**：债务按能力计，不按调用点计——一个能力有一个已检查调用点就不算"部分
   受保护"。这两个数字由 `test_scope_coverage.py` 从代码树复算。

   **4 而不是 7，是因为删了三条声明（2026-10-19）**：`ripple.get_report` /
   `ripple.predict_spread` / `ripple.validate_pmf` 的 `auth_scope=("ripple:read",)`
   已从目录移除。它们从来不是"没接线"，而是**接不了** —— ripple 用
   `Settings().ripple.api_token` 认证（部署级密钥，没有账号维度），而
   `granted_scopes()` 只能吐 `xhs:*`，这个 scope **永远无法被满足**。
   当时摆在面前的两个选项：

   | 选项 | 做法 | 为什么不 |
   |---|---|---|
   | 改 vocabulary（未采用） | 教 `granted_scopes()` 在部署配好 token 时授予 `ripple:read` | 效果等于"所有调用方恒有权限"，那是一个**伪装成权限的配置检查**；它会把"ripple 没配 token"报成"你没被授权"——与"浏览器没开 ≠ 没被授权"是同一个范畴错误。配置缺失已由 `RippleService` 健康检查按自己的语言报告（`DomainOutcome("unavailable")`） |
   | **删声明**（已采用） | 三个 spec 去掉 `auth_scope` | 无 |

   删的理由不只是"这条声明没用"，而是**它是个陷阱**：做一次"把所有声明的 scope 都接上"
   的机械扫描，这三个能力就会被永久拒掉，而 trace 会把锅甩给调用方的身份。
   `test_no_declared_scope_is_unsatisfiable` 现在把这条钉住：任何声明的 scope 都必须是
   `granted_scopes()` 真能产出的。

   **接线带来的唯一收紧**：具名账号若 `cdp_port=0`、只靠全局浏览器，以前会经那台浏览器
   发布，现在被拒（`missing_publish_credential` + `recovery` 指路）。判断依据是它
   正是"一个账号的选择、另一个账号的身份"。没有选中账号的部署不受影响，前提是它
   **声明**了 `XHS_CDP_ENDPOINT`；只靠 9223 探活兜底的部署会拿到同一条拒绝，这是
   "只读声明、不探测"的直接代价，已写进 `docs/tool-runtime.md`。
