# 账号和 API Key 管理功能

## Goal

在 Web UI 中提供完全多租户的账号和 API Key 管理界面。每个账号独立一套凭证（XHS Cookie/UserID + 各 LLM Provider API Key + Ripple CAS 配置），支持在前端添加/编辑/删除账号，切换活跃账号，Key 使用 Fernet 加密存储在 Postgres 中。

## Requirements

* 后端：`accounts` 表 + `account_credentials` 表（Fernet 加密存储）
* 后端：CRUD API `/api/accounts` — 创建/列表/更新/删除账号
* 后端：`/api/accounts/{id}/credentials` — 管理 API Key 和 XHS 凭证
* 后端：写入后同步到 `os.environ`（活跃账号的 key），agents 立即生效
* 后端：服务启动时从 DB 恢复活跃账号的 key 到 `os.environ`
* 前端：Settings 页面 `/settings`，管理账号列表和凭证
* 前端：Navbar 增加 Settings 入口（gear icon）
* 前端：WorkflowStartForm 的 accountId 下拉框关联真实账号列表
* 前端：凭证值脱敏展示（只显示前4后4位）
* 前端：账号切换 — 切换活跃账号后热加载对应凭证

## Acceptance Criteria

* [ ] 可以在前端创建/编辑/删除账号
* [ ] 每个账号有独立的 XHS 凭证 + API Key + Ripple 配置
* [ ] API Key 在 DB 中 Fernet 加密，API 响应脱敏
* [ ] 修改凭证后热加载到 os.environ，agents 立即生效
* [ ] 服务重启后从 DB 恢复活跃账号凭证
* [ ] Health check / PreLaunchChecklist 反映活跃账号的凭证状态
* [ ] WorkflowStartForm accountId 下拉框列出所有账号
* [ ] Navbar 有 Settings 入口

## Definition of Done

* Tests added/updated（unit + integration）
* Lint / typecheck green
* 前后端联调通过

## Out of Scope

* Key 变更审计日志
* API Key 轮转/过期策略
* 账号间权限隔离（共享同一个 admin 登录）
* 导入/导出账号配置

## Technical Approach

### DB Schema

```sql
CREATE TABLE accounts (
  id TEXT PRIMARY KEY,           -- UUID
  name TEXT NOT NULL,            -- 显示名称
  is_active BOOLEAN DEFAULT FALSE, -- 是否为活跃账号
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE account_credentials (
  account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE,
  key_name TEXT NOT NULL,        -- e.g. 'XHS_COOKIE', 'ANTHROPIC_API_KEY'
  encrypted_value BYTEA NOT NULL, -- Fernet encrypted
  PRIMARY KEY (account_id, key_name)
);
```

### 加密

* `ENCRYPTION_KEY` 环境变量提供 Fernet 密钥（服务启动必须）
* `cryptography.fernet.Fernet` 加解密
* 无 `ENCRYPTION_KEY` 时降级为明文存储 + 日志警告

### API Routes

* `POST /api/accounts` — 创建账号
* `GET /api/accounts` — 列表（含活跃状态）
* `PUT /api/accounts/{id}` — 更新名称/活跃状态
* `DELETE /api/accounts/{id}` — 删除账号及凭证
* `GET /api/accounts/{id}/credentials` — 获取脱敏凭证
* `PUT /api/accounts/{id}/credentials` — 批量设置凭证
* `DELETE /api/accounts/{id}/credentials/{key_name}` — 删除单个凭证

### 热加载

* 设置凭证或切换活跃账号时，将活跃账号的所有 key 写入 `os.environ`
* 删除凭证时从 `os.environ` 移除
* 服务启动时在 lifespan 中加载活跃账号凭证

### 前端

* 新增 `/settings` 路由 + `Settings.vue`
* 账号卡片列表 + 凭证编辑表单
* Navbar 底部加 gear icon 指向 `/settings`
* WorkflowStartForm accountId 改为从 accounts API 获取下拉选项

## Decision (ADR-lite)

**Context**: 需要支持多个 XHS 账号，每个账号独立一套凭证，且 API Key 安全存储。
**Decision**: 多租户账号模型 + DB 存储 + Fernet 加密 + 热加载 os.environ。
**Consequences**: 增加 DB 表和加密依赖，但提供安全性和多账号灵活性。Fernet 密钥管理成为运维要求。
