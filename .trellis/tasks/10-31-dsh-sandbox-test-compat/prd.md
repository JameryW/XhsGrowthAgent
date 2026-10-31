# 让全量测试在本机不再报错：DSH 沙箱 tmp 目录 + symlink 权限（票 5at）

> 来源：用户要求“不要让测试用例报错”。全量 pytest 此前是
> **4473 passed / 0 failed / 206 errors**：206 个 error 全是 `tmp_path` 初始化失败；
> 修掉后暴露 11 个 `os.symlink` 权限失败。两项都是**环境性**（CI Linux 不受影响），
> 但本机应当能跑出一份干净结果。

## 1. 根因（已实测）

| # | 现象 | 根因 |
|---|---|---|
| 1 | `PermissionError: [WinError 5] ...\Temp\dsh-*\pytest-of-<user>`，206 errors | DSH Windows 沙箱把 POSIX `0700` 目录模式翻译成**拒绝本进程访问**的 ACL。实测：`os.mkdir(p, 0o700)` 后本进程连 `listdir`/`icacls` 都 Access denied；`mkdir(0o777)`/默认模式正常。pytest 的 `tmp_path` 工厂（`mkdir(mode=0o700)`）与 `tempfile.mkdtemp` 全中招；且 `<Temp>\pytest-of-<user>` 已被早前运行污染成不可读，必须换 temproot。 |
| 2 | 11 个 `OSError: [WinError 1314] 客户端没有所需的特权`（`test_chrome_launcher.py`） | 这些用例用 `os.symlink` 造 `SingletonLock`；Windows 默认只有 Developer Mode/管理员能建 symlink。此前它们根本没跑到（都卡在 tmp_path error），修好 #1 后才暴露。 |

## 2. 修复

1. `tests/conftest.py` 顶部（import 后、任何 fixture 之前）加 **DSH 沙箱兼容 shim**（仅 `sys.platform == "win32" and os.environ.get("DSH_SHELL") == "1"` 生效）：
   - 包一层 `os.mkdir`：`mode == 0o700` 时按 `0o777` 传（普通 Windows 上 mode 本来就被忽略，故在沙箱外是 no-op；Linux CI 不进入该分支）；
   - `PYTEST_DEBUG_TEMPROOT` 指向 `tempfile.mkdtemp(prefix="dsh-pytest-temproot-")` 的**新私有根**，绕开已被污染的 `<Temp>\pytest-of-<user>`。
2. `tests/unit/services/test_chrome_launcher.py`：加 `_symlinks_are_available()` 能力探测（建临时目录→尝试 `symlink_to`→清理），用 `pytest.mark.skipif` 标记 11 个需要 symlink 的用例；无权限环境跳过并给 reason（CI Linux 照常执行）。

## 3. 验收

- [x] 本机全量 pytest：**0 failed / 0 errors**（3 skipped，其中 11 个 symlink 用例 skip 计入 skip 总数）
- [x] `test_chrome_launcher.py`：63 passed / 11 skipped
- [x] CI 语义不变：shim 仅在 win32+DSH_SHELL 生效；skipif 在 Linux 上探测为 True，照常跑
- [x] 普通 Windows（非 DSH）行为不变：`os.mkdir` 本来就忽略 mode
- [x] ruff check / format 绿

## 4. 不做什么

- 不修 DSH 沙箱本身（那是宿主工具问题，上游技能 `diagnose-windows-sandbox-acl` 负责跨轮 ACL 修复；本票只是让测试流程不再被它卡死）。
- 不改变任何被测生产代码路径。
- 不把 `--basetemp` 写进仓库配置（会在 CI 上产生相对路径语义，收益为零）。
