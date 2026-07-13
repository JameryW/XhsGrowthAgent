# 真实账号 Creator Stats 浏览器采集与持久化可靠性

## Goal

修复最近 PR 审查发现的问题，并确保已登录真实账号的笔记统计可经常驻 Chrome
稳定采集、原子持久化和回读，不要求用户复制 Cookie 或平台签名。

## 背景与调查结论

- Creator Center 当前请求由页面 JavaScript 生成 `x-s` / `x-t` 等签名；复用
  Cookie 的 `httpx` 或 Playwright `APIRequestContext` 请求会被平台拒绝。
- 已有账号的常驻 Chrome 已经拥有登录态，并通过每账号 CDP endpoint 可访问。
- 真实页面的笔记管理页会调用
  `/api/galaxy/v2/creator/note/user/posted`，账号统计页会调用
  `/api/galaxy/v2/creator/datacenter/account/base`。
- 原 CLI 没有 FastAPI lifespan，因而可能只写入进程内内存；账号概览和笔记也
  需要作为同一个快照提交。

## 实施范围

1. **原生浏览器采集**
   - `CdpTransport` 连接已登录的 Chrome，打开 Creator Center 页面，观察页面自身
     成功的响应；不读取、复制或重放 Cookie/签名。
   - 采集账号概览与笔记管理页的分页结果，兼容 Creator Center 实际字段形状并完成
     标准化。
   - 保留 Cookie/httpx 路径作为兼容 fallback；CDP 端点优先。

2. **真实数据持久化**
   - 账号概览和所有笔记通过一个 PostgreSQL 事务 upsert。
   - standalone `sync-stats --no-dry-run` 显式初始化并校验数据库表；数据库不可用
     时在网络采集之前失败，绝不把临时内存结果伪装成持久化成功。
   - `--dry-run` 保持无数据库依赖，供 CI 与离线验证。

3. **审查发现的回归修复**
   - 新增 altruism 维度后的旧八维全量权重自动归一化，且全局权重使用 PostgreSQL
     可写的空字符串 scope，不使用 `NULL` 主键值。
   - 补齐前端雷达/详情/中英文标签和 OMP 的十维说明。
   - 创作记忆按互动率排序；Style DNA 同一 `(account_id, tone, visual_style)` 的
     读/合并/写入由进程内锁和 PostgreSQL advisory transaction lock 共同保护。
   - 部署脚本将 Ripple 配置经标准输入写入容器，并只输出脱敏状态，不再将 API key
     写入终端或日志。

## 不做

- 不伪造或逆向生成平台请求签名。
- 不删除已有 Cookie fallback。
- 不扩展到发布、登录或非 Creator Center 数据源。

## 验收标准

- 在真实已登录账号上，API 和 CLI 均可从页面原生请求获得笔记；回读结果中的每条
  笔记都有 ID 和互动指标。
- 生产同步后，PostgreSQL 中的账号概览和笔记数量一致，且导入过程不会产生半快照。
- 无 PostgreSQL 的 fixture dry-run 成功；live CLI 在数据库不可用时明确失败。
- Creator Stats、evaluator config、creative memory 的单测、Ruff、mypy，以及
  frontend/OMP 类型构建均通过。
- 部署输出不包含 Ripple API key。
