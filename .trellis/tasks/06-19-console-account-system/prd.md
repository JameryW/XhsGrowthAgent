# 管控台账号系统：登录用户 + XHS 账号 + 全局配置三层分离

## Goal

把当前混在一起的「Account + 全部 credentials」拆成三层：

1. **管控台用户（Console User）** — 后台登录身份，拥有自己的工作空间
2. **XHS 账号（XHS Account）** — 真正运营的小红书账号，挂 cookie/user_id 等平台凭证
3. **全局配置（System Config）** — LLM/Ripple/Embed/Search 这类基础设施 keys，与具体小红书账号无关

UI 入口走 Settings 页面 + 侧边栏分组导航，整体观感优雅一点。

## What I already know

### 现有登录系统
- `backend/api/auth.py`：单一硬编码用户 `admin/admin123`（来自 `Settings().auth.admin_username/password`）
- Token 存内存 dict（`_active_tokens`），有 `expires_at`
- 前端 `frontend/src/stores/auth.ts`：localStorage 存 token + user，已有 `Login.vue` 完整登录页
- 路由守卫已通：`isAuthenticated && route.name !== 'login'` 才显示 chrome
- **无 users 表**

### 现有 Account 系统
- 表 `accounts`（id/name/is_active/created_at/updated_at），`account_credentials`（account_id/key_name/encrypted_value）
- 凭证加密落盘（`backend/db/crypto.py`），激活时注入 `os.environ`
- API：`/api/accounts` CRUD + `/api/accounts/{id}/credentials` 批量增删改
- 当前 Settings.vue 把 keys 分 4 组展示，但都是同一个 Account 下：
  - LLM Providers（ANTHROPIC/OPENAI/DEEPSEEK/DASHSCOPE/XIAOMIMIMO）→ **应归全局配置**
  - XHS Platform（XHS_COOKIE/XHS_USER_ID）→ **应归 XHS 账号**
  - Ripple CAS（RIPPLE_*）→ **应归全局配置**
  - Search/Embedding（TAVILY/XHS_EMBED_*）→ **应归全局配置**

### DB 结构
- **PostgreSQL**（psycopg + BYTEA），无 alembic，建表语句写在各 `db/*.py` 内 `CREATE TABLE IF NOT EXISTS` + `ensure_tables()`
- 加密：`backend/db/crypto.py`（已有，沿用 `encrypt_value` / `decrypt_value` / `mask_value`）
- 白名单：`backend/db/accounts.py:CREDENTIAL_KEYS` 已存在，需要拆成 `XHS_KEYS` + `SYSTEM_KEYS` 两组

## Assumptions (temporary)

- 单租户即可；管控台用户是「内部运营人员」，不是 SaaS 多租户
- 全局配置全局共享，不按用户隔离
- XHS 账号也是全局共享（任何登录用户都能切换/管理）；MVP 不做 XHS 账号 owner 归属
- 登录用户密码用 bcrypt/passlib hash（避免明文落盘）

## Decisions

- **D1 — 管控台用户系统深度：L1（多用户最小可用）**
  - 新增 `console_users` 表，bcrypt 密码哈希
  - 所有用户权限相等（都是 admin），不引入 role 字段
  - 不做个人偏好/会话隔离
  - 老 `admin/admin123` 通过迁移种子用户保留可用

- **D2 — 系统配置存储：独立 `system_config` 表**
  - 不复用 `account_credentials` + 哨兵账号
  - 新表结构：`key_name` (PK) / `encrypted_value` / `updated_at`
  - 复用 `backend/db/crypto.py` 加密；`init_db()` 内 `CREATE TABLE IF NOT EXISTS`
  - 启动时（或激活时）把 system_config 全部解密注入 `os.environ`，与 XHS 账号 cookie 注入解耦
  - `accounts` 表语义彻底变为「XHS 账号」

- **D3 — 数据迁移：从激活账号一次性提取，幂等**
  - `ensure_tables()` 后：若 `system_config` 表空 且 存在 `is_active=true` 的账号
  - 把该账号里所有 SYSTEM_KEYS 复制到 `system_config`
  - 然后 `DELETE FROM account_credentials WHERE key_name = ANY(%s)`（对所有账号）
  - `system_config` 非空则跳过（幂等）
  - 不再支持「不同账号有不同 LLM keys」的语义

- **D4 — 界面：内嵌侧边栏到 Settings 页**
  - 单一路由 `/settings` 不变；页内左侧 200px 分组栏，右侧内容区
  - 三组：账户管理 / 平台账号 / 系统配置
  - URL 用 `?tab=console-users|xhs-accounts|system-config` 记选中
  - 顶部 Navbar 不动

## Open Questions

（无）

## Requirements (evolving)

### 数据模型
- 新增 `console_users` 表：id / username / password_hash / role / created_at / last_login_at
- 新增 `system_config` 表（或复用 credentials 表 + 哨兵 account_id）：key_name / encrypted_value（全局共享）
- 现有 `accounts` 改名/重定位为「XHS 账号」语义；`account_credentials` 仅存 `XHS_COOKIE` / `XHS_USER_ID`（白名单）
- 数据迁移：现有 Account 拆出 LLM/Ripple/Embed → system_config，保留 XHS_* 在原表

### 后端 API
- `/api/auth/*` 复用，但 `verify_credentials` 改查 console_users 表
- `/api/console-users` CRUD（管控台用户管理）
- `/api/xhs-accounts` CRUD + credentials（仅接受 XHS 白名单 keys，重命名自现 `/api/accounts`，旧路径保留兼容一段时间）
- `/api/system-config` GET/PUT（全局配置；按分组返回）

### 前端
- Settings.vue 重构：左侧分组栏（账户管理 / 平台账号 / 系统配置），右侧内容区
- 「账户管理」= 管控台用户列表 + 当前用户改密
- 「平台账号」= XHS 账号 CRUD + cookie/user_id 编辑 + 激活切换
- 「系统配置」= LLM / Ripple / 搜索&向量 三组卡片
- 视觉：保留现有 Tailwind + NeonButton 调性，但增加 section header / 卡片化分隔

## Acceptance Criteria (evolving)

- [ ] 旧 admin/admin123 登录在 MVP 仍可用（迁移种子用户），密码改为 bcrypt
- [ ] 至少能创建第二个管控台用户并登录成功
- [ ] 创建新 XHS 账号时只能填 cookie/user_id，看不到 LLM/Ripple keys
- [ ] 系统配置全局唯一：在任何登录身份下编辑结果一致
- [ ] 切换 XHS 账号时 `os.environ.XHS_*` 正确刷新，全局配置保持不变
- [ ] 现有数据迁移脚本一次跑通，不丢失 keys

## Definition of Done

- 单元测试：console_users / system_config 仓库层；XHS 账号白名单校验
- 集成测试：登录新建用户 → 切换 XHS 账号 → 全局配置不变
- Lint / typecheck / pytest 全绿
- 数据迁移幂等（重复跑不出错）

## Out of Scope (explicit)

- RBAC/细粒度权限（只分 admin / member 即可，或先全部当 admin）
- 用户找回密码、邮件、SSO
- XHS 账号的 owner 归属（多用户协作权限）
- 审计日志
- API 文档同步（contract test 单独跟进）

## Technical Notes

- DB 迁移策略：在各 `db/*.py` 的 `init_db()` 加 `ALTER TABLE` / `INSERT...SELECT`，幂等判断；不引入 alembic
- 加密复用 `backend/db/crypto.py`
- 现 `/api/accounts` 路由保留为 `/api/xhs-accounts` 的别名一个版本，前端切换后再删
- 前端文案 i18n：新增 `settings.consoleUsers / settings.xhsAccounts / settings.systemConfig` 三大组 key
