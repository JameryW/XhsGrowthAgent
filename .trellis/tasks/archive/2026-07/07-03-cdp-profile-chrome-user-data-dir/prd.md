# CDP 多 profile——每账号独立 Chrome user-data-dir 发布

## Goal

CDP 模式下 `_ensure_page` 用真实 Chrome `browser.contexts[0]`（profile 自带登录态），忽略传入的 cookie。选定哪个账号发布都用真实 Chrome 当前登录账号，多账号发布不工作。

让每账号绑定独立 Chrome user-data-dir + 独立 CDP port，发布时 `connect_over_cdp` 连对应账号的 endpoint，使选定账号真正生效。含 launcher（启 N 常驻 Chrome）+ 登录入（headed 扫码）。

## Research References

* [`research/cdp-per-profile.md`](research/cdp-per-profile.md) — `connect_over_cdp` 保留扩展 per-account；每账号独立 `--user-data-dir`+`--remote-debugging-port` 常驻 daemon；SingletonLock gotcha；CDP attach 不取 lock 安全；扫码需 headed
* [`research/account-profile-binding.md`](research/account-profile-binding.md) — accounts 表加列 migration 用 `ALTER TABLE ADD COLUMN IF NOT EXISTS`（同 evaluator_config）；`XHSPlatformSettings` env_prefix mirror `cdp_endpoint`，env-only 不入 SYSTEM_KEYS；seam 在 `run_publish`→`XHSClient`→`XHSPublisher`

## Requirements

### 数据层
- accounts 表加 `chrome_profile_path TEXT` + `cdp_port INTEGER` 列（migration：`ALTER TABLE ADD COLUMN IF NOT EXISTS`，idempotent）
- `AccountRow` 加两字段
- 创建账号时自动分配：`chrome_profile_path` 默认 `<chrome_profiles_dir>/<account_id>`，`cdp_port` = 首个空 port（`cdp_base_port`+1 起递增，跳占用）
- operator 可改两字段（账号管理 API）

### 配置
- `XHSPlatformSettings` 加 `chrome_profiles_dir: str`（env `XHS_CHROME_PROFILES_DIR`）+ `cdp_base_port: int = 9222`（env `XHS_CDP_BASE_PORT`），env-only（mirror `cdp_endpoint`，不入 SYSTEM_KEYS）
- `.env.example` 补两 env

### 发布链路
- `run_publish` 解析选定 account 的 `cdp_port` → `cdp_endpoint=f"http://host.containers.internal:{port}"`（容器内）/ `http://127.0.0.1:{port}`（本地），传 `XHSClient`→`XHSPublisher`
- 账号无 `cdp_port`（0/null）→ fallback 全局 `_resolve_cdp_endpoint`（向后兼容单账号 `.chrome-profile/`）
- `_resolve_cdp_endpoint` 扩展为 per-account 优先

### Launcher（进程管理）
- 脚本/服务读 accounts 表，确保每活跃+有 port 的账号 Chrome 在跑
- HTTP-probe `GET /json/version` 探活；down 且 SingletonLock stale → 清 lock 重启；down 且 lock 活 → skip
- `google-chrome --user-data-dir=<path> --remote-debugging-port=<port> --remote-debugging-address=0.0.0.0`（host 启，container 连 host.containers.internal）
- 常驻 daemon，pidfile

### 登录入
- headed Chrome 打开 XHS creator 登录页供扫码
- 触发：账号管理 API 或 CLI 命令，按 account_id 启对应 profile 的 Chrome 开登录页
- 登录态写入该 account 的 user_data_dir，持久

## Acceptance Criteria

- [ ] accounts 表有 `chrome_profile_path`+`cdp_port` 列，创建账号自动分配
- [ ] 账号 A 绑 port 9223、账号 B 绑 9224，两常驻 Chrome 各自登录 A/B
- [ ] 选定 A 发布 → XHS 发布身份为 A；选定 B 发布 → 身份为 B
- [ ] 账号无 port → fallback 全局 CDP（不破坏现有单账号）
- [ ] launcher 探活 + stale lock 清理正确（无第二个 Chrome 抢同 dir）
- [ ] 登录入：按 account_id 启 headed Chrome 开 XHS 登录页，扫码后状态持久
- [ ] 测试：account→port 解析、无 port fallback、自动分配 port 跳占用、migration idempotent

## Definition of Done

- 单测覆盖（DB 解析、fallback、自动分配、migration）
- Lint/typecheck/CI 绿
- `.env.example` + 部署文档更新（launcher 启动方式）
- 不破坏单账号 CDP 兼容

## Decision (ADR-lite)

**Context**: CDP 单一全局端点，多账号发布都用全局 Chrome 登录账号。需 per-account profile。

**Decision**:
- DB 存 `chrome_profile_path`+`cdp_port`，创建时自动分配（path 约定默认、port 首空递增），operator 可改
- `connect_over_cdp` 保留，endpoint 改 per-account
- Chrome always-on daemon，外部 launcher 脚本启，app 只 connect
- env-only 配置（不入 system_config SYSTEM_KEYS）

**Consequences**:
- N 账号 = N 常驻 Chrome（~200-400MB/个 idle），账号多时 RAM 压力
- 首次每账号需扫码（手动一次）
- per-account port 需 host↔container 网络（`--remote-debugging-address=0.0.0.0` + host.containers.internal）
- `.chrome-profile/` 保留全局默认，无 port 账号 fallback 它

## Out of Scope

- 自动 cookie 刷新（过期仍人工 re-扫码）
- profile 清理/轮换/压缩
- 非 CDP launch 模式改造
- Chrome 进程 supervisor（systemd/pm2）集成——launcher 脚本手动/部署钩子启

## Technical Notes

- migration 范式：`backend/db/evaluator_config.py` `_ADD_SNAPSHOT_COL_SQL` `ALTER TABLE ADD COLUMN IF NOT EXISTS`
- seam：`run_publish`（`publisher.py:170-193`）已取 `publish_account_id`，加 `get_account` 取 port/path
- `XHSPublisher._ensure_browser` CDP 分支不变，只 endpoint 变
- `_resolve_cdp_endpoint`（`publisher.py:60`）扩展 per-account 优先
- SingletonLock：`<user_data_dir>/SingletonLock` symlink 指向 `<host>-<pid>`，PID 死方可清
- Chrome binary：`google-chrome`（非 chromium，反爬），launcher 需探路径
