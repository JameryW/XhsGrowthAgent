# test(infra): 把 TMPDIR/TEMP/TMP 指向仓库内 .dsh-tmp，杜绝测试产物落在仓库根（票 5cc）

> 5cb 只解决了 pytest 自己的 temproot，但真正的原因更宽：沙箱系统 temp 不可写时
> `tempfile.gettempdir()` 会回落到**当前目录**，于是任何用 `gettempdir()` 的测试写入
> 都落在仓库根。全量跑完实测泄漏了两个非点号目录：
> `xhs_images/`（上传图）与 `data-gym-cache/`（模型缓存）。

## 1. 根因链

| 环节 | 事实 |
|---|---|
| 系统 temp 不可写 | 沙箱内 `tempfile.gettempdir()` 返回仓库根 |
| `backend/api/routes/_wf_application.py` | 上传目录 = `Path(tempfile.gettempdir()) / "xhs_images" / thread_id` → 仓库根/xhs_images |
| 第三方缓存 | 某依赖把缓存目录回落到 cwd → `data-gym-cache/` |
| 后果 | 非点号目录被 docs 引用 corpus 视为"我们的文件"，可再次造成 5cb 那类假红；也污染工作树 |

## 2. 修复（locked）

在 conftest 的 DSH 分支内（仅 `sys.platform == "win32" and DSH_SHELL == 1`）：
1. 创建仓库内点号目录 `.dsh-tmp/`（`os.makedirs(mode=0o777)`，沙箱可写）；
2. 把 `TMPDIR` / `TEMP` / `TMP` 三个变量**覆盖**为它（不是 setdefault——系统值存在但不可写）；
3. pytest temproot 放到 `.dsh-tmp/pytest-temproot/` 下；
4. `.gitignore` 增加 `.dsh-tmp/`；删除本次泄漏的 `xhs_images/`、`data-gym-cache/`。

CI（Linux、无 DSH_SHELL）完全不受影响：分支不进入。

## 3. 验证

- `tests/unit/scripts/test_docs_citations.py`：9 passed（新增文档 + 干净根目录下引用解析正常）。
- 全量 pytest 后仓库根只应有仓库目录（api/backend/docs/frontend/logs/scripts/tests）与历史不可读
  `tmpprobe-*`（os.walk 跳过），不再出现 `xhs_images/`、`data-gym-cache/`、`dsh-pytest-temproot-*`。
- 全量结果见 notes。

## 4. 不做什么

- 不改生产代码里 `tempfile.gettempdir()` 的使用（测试环境覆盖即可）；
- 不改 CI 配置；不删除历史 ACL 目录（不可读、被忽略）。
