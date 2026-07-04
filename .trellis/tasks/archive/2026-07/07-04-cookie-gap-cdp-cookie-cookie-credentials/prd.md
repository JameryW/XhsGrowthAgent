# PRD: CDP 发布跳过 cookie 必需检查

## 背景

真实发布链路当前 gap：

1. 扫码登录（`backend/services/xhs_login.py`）成功后登录态写入 `account.chrome_profile_path`（persistent context profile）。
2. `run_publish`（`backend/agents/publisher.py:116`）从 `get_account_cookie` 读 `XHS_COOKIE`，**无 cookie 直接 fail (no_cookie)**（publisher.py:137-158）。
3. 但 CDP 模式下 `xhs_publisher._ensure_page`（`backend/services/xhs_publisher.py:122-129`）直接用常驻 Chrome 已有 context（profile 自带登录态），**不读 `self.cookie`**——`cookie` 参数只在非 CDP launch 分支（line 155）用。

→ 扫码登录已成功、profile 已有登录态，但 `run_publish` 卡在 cookie 必需检查，真实发布走不通。

## 决策

- **做**：CDP 模式（per-account endpoint 命中）跳过 cookie 必需检查。profile 登录态即足够。
- **砍**：扫码同步 cookie 到 credentials。CDP 模式 cookie 被忽略，中转多余；跨子域问题 CDP 下不存在（profile 同一 user-data-dir 管 www + creator cookie）。

## 需求

### R1: CDP 模式跳过 cookie 必需检查

`run_publish` 选定 `publish_account_id` 时：
- 读 cookie（保留，兼容非 CDP fallback 路径）+ 读 per-account CDP endpoint。
- **无 cookie 且无 per-account CDP endpoint** → 保留原 `no_cookie` fail fast（profile 没登录态、也没 cookie，确实发不了）。
- **无 cookie 但有 per-account CDP endpoint** → 不 fail，继续发布（CDP 模式靠 profile 登录态，cookie 参数被忽略）。日志说明。
- **有 cookie** → 原路径不变（非 CDP 或 CDP+cookie 都传，CDP 分支忽略无害）。

### R2: is_active 检查保留

停用账号早 fail（`publisher.py:159-182`）与 cookie 无关，保留不动。

### R3: 不改 xhs_publisher

CDP 分支行为正确（不注 cookie），不动。

## 验收

- `test_no_cookie_returns_failed_no_cookie` 改造：无 cookie + 无 CDP endpoint → no_cookie fail（保留断言）。
- 新增：无 cookie + 有 CDP endpoint → 不 fail，XHSClient 被构造，cookie="" 传入。
- 既有 CDP endpoint 测试（`test_per_account_cdp_endpoint_passed_to_client` 等）不受影响。
- 全量 `pytest tests/unit/agents/test_run_publish.py` 绿。

## 不做

- 扫码同步 cookie 到 credentials（CDP 模式无意义）。
- 跨子域 cookie 验证（CDP 下 profile 自管）。
- launcher Chrome 启动 / 真扫码 / 真发布实测（B 段，需用户参与）。
