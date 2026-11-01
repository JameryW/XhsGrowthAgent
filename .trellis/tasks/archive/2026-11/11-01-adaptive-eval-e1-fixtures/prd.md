# feat(eval): E1 评测语料抽取器——真实 checkpoint + 强制脱敏 + 可配置预算（票 5cd）

> 用户拍板三项：**评测口径都需要**（决策正确性 + 内容质量）、**数据来源真实**、
> **预算可配置或选择**。本票落地 E1（数据集框架），不碰 E2 变体接口，也不改线上行为。

## 1. 交付

| 文件 | 作用 |
|---|---|
| `scripts/eval/fixtures.py` | `EvalFixture` / `FixtureEntry` / `FixtureManifest` schema；**唯一**脱敏 pass `redact_state`；`build_fixture`/`state_sha256`/`pseudonym` |
| `scripts/eval/extract_fixtures.py` | 只读真实 checkpoint（SQLite / Postgres 的 `alist`）→ 每线程最新状态 → 脱敏 fixture + manifest；CLI |
| `tests/unit/scripts/test_eval_fixtures.py` | 10 个用例，含用 `AsyncSqliteSaver` 播种真实 sqlite 后跑完整抽取管线 |

## 2. 脱敏契约（locked）

- 标识符（account/thread/session/creator/audience/owner/user/approved_by）→
  `<kind>_<sha256[:12]>` 稳定假名；
- 密钥类键（cookie/web_session/token/api_key/secret/password/authorization/proxy/credential）
  → 空字符串；
- 位置类（cdp_endpoint/chrome_profile_path）→ 空字符串；
- 图片路径 → `image/NN.<ext>`（保留扩展名，去掉目录与文件名）；
- `messages` 默认丢弃（`--include-messages` 才保留）；
- **内容字段保留**：copy_content/visual_plan/plan 等，质量评测需要；
- 非 JSON-like 状态直接拒绝（`ValueError`），深度上限 12。

## 3. 预算/选择可配置

`--limit N`（默认 100，0/`--all` 表示不限）、`--phases reviewing,publishing`、
`--sqlite-path`（默认 `.xhs/checkpoints.sqlite`）/`--postgres-uri`、`--dry-run`、
`--include-messages`、`--output`（默认 `.eval-fixtures/`，gitignore）。

## 4. 验证

- 新用例：**10 passed**（含真实 sqlite 往返、manifest sha256 与"写入物不含明文"断言）。
- 空本地库 dry-run：0 fixtures、exit 0、提示"source has no matching checkpoints"。
- `tests/unit/scripts` 与全量 pytest 见 notes。
- 纯新增离线工具：不触网、不跑 workflow、不改默认路由。

## 5. 本地现实

本 checkout 的 `.xhs/checkpoints.sqlite` 为空（0 checkpoints）；真实语料需在有数据的
部署/已填充 sqlite 上生成。E1 的正确性由种子库测试覆盖，文档已写明。

## 6. 不做什么

- 不做 E2 变体接口 / E3 门禁 / L3 端到端（各自独立票）；
- 不把真实 fixture 提交进仓库（`.eval-fixtures/` gitignore）。
