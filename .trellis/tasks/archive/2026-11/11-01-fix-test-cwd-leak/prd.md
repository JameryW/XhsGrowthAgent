# 修复测试 cwd 泄漏导致的全量顺序 flaky（票 5az）

> 来源：本轮目标回归时复现——`tests/unit/services/creator_stats/test_mode_and_fixture_path.py`
> 的 cwd 测试把仓库根算成 `tests/` 并 `os.chdir` 后留在那里（finally 恢复到同一个错误根），
> 同一进程里后续的 `test_prompt_loader_reads_a_utf8_prompt_regardless_of_host_locale`
> 用 cwd 相对路径写 prompt 文件 → `FileNotFoundError`。单跑通过，组合跑随机红。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| `parents[3]` 是 `tests/` 不是仓库根 | 文件位于 `tests/unit/services/creator_stats/`，parents[4] 才是仓库根 |
| `os.chdir(project_root)` 泄漏 | 复现命令：先跑该 cwd 用例再跑 prompt 用例 → `FileNotFoundError: ...\tests\backend\config\prompts\...` |
| prompt 用例依赖 cwd | `Path("backend/config/prompts").resolve()` |

## 2. 修复

1. `test_mode_and_fixture_path.py`：`parents[4]` 取仓库根；改用 `monkeypatch.chdir`
   （失败也会自动恢复），删掉手动 try/finally 与不再使用的 `os` import。
2. `test_text_io_encoding.py`：prompt 目录用 `Path(__file__).resolve().parents[3]` 定位
   仓库根，不再依赖进程 cwd。

## 3. 验收

- [x] 复现顺序（cwd 用例 → prompt 用例）2 passed
- [x] 组合目录（services + api + db + tools/runtime）不再出现该 failed
- [x] ruff check / format 绿
