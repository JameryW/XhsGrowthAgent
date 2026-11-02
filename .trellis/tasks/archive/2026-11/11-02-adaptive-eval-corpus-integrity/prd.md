# feat(eval): manifest 指纹与 out-of-band 校验 + 可选加盐假名（票 5ck）

> 独立审查的两条低危：①「语料完整性只自洽——fixture+manifest 成对改写仍通过」，
> ②「pseudonym 是截断 SHA-256，短账号 id 可被字典攻击」。本票把两条都变成可选项：
> 写出 `manifest.sha256` 指纹并支持 `--expect-manifest-sha256` 做 out-of-band 核对；
> 支持用环境变量提供的密钥做 HMAC 假名，manifest 记录模式。默认行为（无密钥）保持兼容，
> 但会在输出里明确提示"未加盐、可被字典攻击"。

## 1. 交付

| 文件 | 变化 |
|---|---|
| `scripts/eval/fixtures.py` | `pseudonym(kind, value, key=None)` 支持 HMAC；`build_fixture(..., redaction_key=...)`；`FixtureManifest.pseudonym_mode`（`sha256`/`hmac`） |
| `scripts/eval/extract_fixtures.py` | 读 `XHS_EVAL_REDACTION_KEY`（CLI 可传 `--redaction-key-env`）；写 `manifest.json` 同时写 `manifest.sha256`；无密钥时打印警告 |
| `scripts/eval/run_gate.py` | 若语料内有 `manifest.sha256` 则校验；新增 `--expect-manifest-sha256`（out-of-band 核对），不匹配 → 红；报告输出实际指纹 |
| `tests/*` | 加盐/未加盐、指纹校验与不匹配、out-of-band 期望值 |
| 文档 | §6.5 语料格式与安全说明；runbook 记录密钥与指纹 |

## 2. 语义

- **指纹**：`manifest.sha256` 是 manifest 字节的 SHA-256。它能发现"只改了 manifest"的
  篡改；对"fixture + manifest + 指纹一起重写"只能靠 out-of-band 值（`--expect-manifest-sha256`
  或 plan/实验记录里保存的指纹）发现——文档如实说明这一点，不宣称防篡改。
- **加盐假名**：密钥由部署侧环境变量提供（`XHS_EVAL_REDACTION_KEY`），不写入语料；
  同一密钥下假名稳定（可比较），无密钥时退回 sha256 并在输出/manifest 里标注。
  更换密钥后旧语料不可比（预期行为，文档写明）。

## 3. 验证

- fixtures/gate 用例新增后全绿；全量 pytest 与 CI 见 journal；
- 实跑：无密钥抽取 → manifest `pseudonym_mode=sha256` + 警告；带密钥 → `hmac`，同一输入
  两次运行假名一致；改动 manifest 后 gate 因指纹不符转红。

## 4. 不做什么

- 不引入 GPG/签名基础设施（超出本仓库范围）；不把密钥写进语料或 manifest；
- 不改默认（无密钥仍可用，只是有明确警告）。
