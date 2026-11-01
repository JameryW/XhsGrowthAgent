# test: login 用例改用 tmp_path，去掉硬编码 /tmp（票 5bp）

> 全量跑出唯一一红：`tests/unit/cli/test_main.py::TestCliLogin::test_login_opens_persistent_context`
> 断言 `launch_persistent_context` 未被 await。与业务代码无关，是**测试自身**的移植性缺陷。

## 1. 根因

| 事实 | 证据 |
|---|---|
| 用例把账号 `chrome_profile_path` 写死为 `/tmp/xhs-login-test` | 原 `tests/unit/cli/test_main.py` |
| CLI 会先 `Path(profile_path).mkdir(parents=True, exist_ok=True)` | `backend/cli/main.py` login |
| Windows 把 `/tmp/...` 解析成当前盘根的 `\tmp\...`，工作区沙箱拒绝在仓库外创建目录 | 仓库自带 `tests/unit/test_no_hardcoded_tmp_paths.py` 的同一理由 |
| mkdir 抛错被 `CliRunner.invoke` 捕获 → 未走到 `async_playwright()`，mock await 次数为 0 | 失败输出 `Awaited 0 times` |

之前能过，只是因为某次运行在沙箱外创建过该目录、`exist_ok=True` 使 mkdir 变成 no-op；目录一旦被清理，测试就红。

## 2. 决定

1. 用 `tmp_path` fixture 生成 profile 路径（pytest temp root 由 conftest 处理为可写），
   与 `tests/unit/test_no_hardcoded_tmp_paths.py` 对 backend 的移植性要求一致。
2. 断言改为 `user_data_dir == str(profile_path)`；其余断言不动。
3. 纯测试修复，不改 CLI 行为、不加 sleep/跳过。

## 3. 验证

- `tests/unit/cli/test_main.py` 14 passed
- ruff check / format 绿
- 全量见 notes

## 4. 不做什么

- 不把 guard 扩到 tests/ 全量（本次只修已红的用例）；不改 sandbox 策略。
