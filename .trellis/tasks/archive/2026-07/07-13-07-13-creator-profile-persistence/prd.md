# 创作者账号资料采集、持久化与展示

## 背景

当前创作者中心同步仅保存周期表现和笔记数据。创作者中心页面还会在同一已登录会话中请求
`/api/galaxy/user/info`，返回账号身份资料；这些资料尚未被采集、保存或展示。

## 目标

在不读取敏感账号数据的前提下，将创作者中心的基础账号资料纳入现有
“采集 → 标准化 → PostgreSQL → API → CreatorStatsPanel”链路。

## 范围

1. CDP 采集器捕获与账户统计同一次页面加载的 `GET /api/galaxy/user/info` 响应。
2. 标准化并保存以下白名单字段：
   - 平台用户 ID（`userId`）
   - 昵称（`userName`）
   - 红书号（`redId`）
   - 头像 URL（`userAvatar`）
   - 简介（`userDesc`）
   - 创作者角色（`role`）
   - 地区（`zone`）
3. 扩展 `creator_account_stats` 的建表、幂等迁移、upsert 和读取逻辑；与账户统计和笔记保持同一事务。
4. 现有 `GET /api/analytics/creator-stats/{account_id}` 返回新增资料字段。
5. 在现有 `CreatorStatsPanel` 展示账号资料。该组件已被账号设置页和分析页复用，因此两处自动覆盖。
6. 扩展 fixture、CDP、标准化、持久化/API 测试，并用已登录真实账号验证资料已落库和 API/页面数据可读。

## 隐私与非目标

- 不读取、不记录或返回手机号、权限、实名状态、Cookie、登录令牌、设备信息等敏感字段。
- 不新增独立登录流程，也不改变现有同步授权边界。
- 当资料接口暂时不可用时，已成功取得的指标/笔记同步不能被回滚；记录可用资料即可。

## 验收标准

- 真实 CDP 同步后，数据库的 `creator_account_stats` 存有上述可用账号资料。
- 读取 API 的 `account` 对象包含资料字段且不含敏感字段。
- 账号设置页和分析页复用的 CreatorStatsPanel 显示头像、昵称/红书号、简介及可用角色/地区。
- 数据库 schema 升级对已有表可重复执行；同步操作保持原子性。
- 后端 lint、格式、mypy、相关单测和前端 typecheck/build 通过。
