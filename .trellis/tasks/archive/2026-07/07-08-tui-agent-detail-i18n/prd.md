# TUI Agent 执行详情 i18n

## Goal

AgentTUI.vue 里 agent 执行过程的展示文案大量硬编码英文,未走 i18n。中文用户在 free 模式(及其他)看到英文 status label / 工具调用块 / 错误 / help / drafts 列表。需统一走 `t()` + 补 zh-CN/en key。

## What I already know

AgentTUI.vue 已有部分 i18n(free 模式 9 key 齐),但 agent 执行详情硬编码英文:

- **工具调用块**(602/609):`▸ toolName(args)` / `↳ toolName result` — 符号 OK,但无文案需评估
- **错误/断连**(552):`⚠ Agent disconnected, reconnecting (N/M)...`
- **未知错误**(620):`event.message || 'Unknown error'`
- **status 展示**(795-799):`phase`/`status`/`progress`/`agent`/`next` 英文 label
- **drafts 列表**(845/850,PR#211 加的):`Free Drafts — {accountId}:` / `(untitled)` — 硬编码!
- **Help 框**(866-879+):`XHS Growth Agent — Help` / `Agent Mode` / `Send message to AI agent` / 各命令说明全英文
- **banner**(866 等):部分已 i18n(flowText),但 Help/Mode 标题硬编码

## Decision — 范围（已定）

**仅执行详情核心**:工具调用块 + status label + 错误/断连 + drafts 列表。
Help 框/banner 标题保留英文(品牌名 + 命令名惯例保留)。

## Open Questions

（已收敛,无 blocking）

## Requirements (final)

### 本地化目标(走 t() + zh-CN/en key)
- **工具调用块**:工具开始/结束展示。`toolName`/`argsStr`/`resultStr` 是动态数据保留;加本地化 label 或保留符号。具体:开始块保留 `▸ toolName(args)`(符号+数据,无需文案);结束块 `↳ toolName result` 同理。若 error 标记需本地化(`✗` 或 "failed" → 中文)。评估后定:符号块保留,只本地化 error 文案。
- **status label**(795-799):`phase`/`status`/`progress`/`agent`/`next` → 中文 label(阶段/状态/进度/智能体/下一步)
- **错误/断连**(552):`⚠ Agent disconnected, reconnecting (N/M)...` → `⚠ 智能体断开,重连中 (N/M)...`
- **未知错误**(620):`'Unknown error'` fallback → `'未知错误'`
- **drafts 列表**(845/850):`Free Drafts — {accountId}:` → `自由草稿 — {accountId}:`;`(untitled)` → `(无标题)`

### 不动
- Help 框(866-879+)英文命令说明保留
- banner 标题(`XHS Growth Agent` 品牌名)保留
- 工具调用块的符号(▸ ↳ ⚠ ❯)+ 动态数据(toolName/argsStr)保留
- agent 执行逻辑不变

## Acceptance Criteria (final)

- [ ] status label(phase/status/progress/agent/next)中文化
- [ ] 断连提示 + 未知错误 fallback 中文化
- [ ] drafts 列表标题 + (untitled) 中文化
- [ ] 工具调用块 error 标记中文化(若有)
- [ ] zh-CN + en key 齐
- [ ] 非 free 模式行为不变(文案改动对 trend/brief 同样生效,但不改逻辑)
- [ ] 前端 build+typecheck 过;CI green

## Definition of Done (team quality bar)

- 前端 build+typecheck 过;i18n key zh-CN+en 齐;ruff 过(无后端改动)
- CI green

## Out of Scope (explicit)

- （待收敛）

## Technical Notes

- 文件:`frontend/src/views/AgentTUI.vue`、`frontend/src/locales/zh-CN.json`、`frontend/src/locales/en.json`
- 现有 i18n 模式:`t('tui.<key>')`,zh-CN.json/en.json `tui` 命名空间
- 约束:不改 agent 执行逻辑,只文案
