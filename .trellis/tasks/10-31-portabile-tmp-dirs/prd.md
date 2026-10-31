# 跨平台临时目录：去掉硬编码 `/tmp` 路径（票 5as）

> 来源：本轮 CI 复演（全量 pytest）里**唯一确定性失败**：
> `tests/integration/test_workflow_bug_fixes.py::test_upload_images_updates_previous_node_without_advancing_review_gate`
> —— 生产代码把上传图片写到 `Path("/tmp/xhs_images/{thread_id}")`，Windows 上解析为
> 当前盘符根目录 `\tmp\...` 且可能不可写（本机 Errno 13）。CI 是 Linux 所以一直没暴露。

## 1. 目标

把 backend 里两处硬编码 `/tmp/` 目录改为 `tempfile.gettempdir()` 派生：
- `backend/api/routes/_wf_application.py` 的图片上传目录；
- `backend/agents/publisher.py` 的文字封面生成目录。

Linux/容器上 `gettempdir()` 就是 `/tmp`，行为不变；Windows/macOS 上落到系统临时目录。
另加静态回归测试：`backend/**` 不得再出现以 `/tmp/` 开头的字符串常量。

## 2. 已核实的事实

| 事实 | 证据 |
|---|---|
| 上传路径硬编码 | `backend/api/routes/_wf_application.py` 的 `image_dir = Path(f"/tmp/xhs_images/{thread_id}")` |
| 封面路径硬编码 | `backend/agents/publisher.py` 的 `output_dir = Path("/tmp/xhs_generated_covers") / ...` |
| 全量门禁里其余失败均为环境性 | 206 个 `tmp_path` ACL ERROR；本用例是唯一 `FAILED`（剩余 1 个），日志 `Permission denied: '\\tmp\\xhs_images\\...'` |
| 无测试/文档断言字面量路径 | 全仓 grep `xhs_images` / `xhs_generated_covers` 仅两处生产代码 |
| CI 在 Linux 上通过 | 硬编码 `/tmp` 在 Linux 恰好可写，故长期未暴露 |

## 3. 要求

1. 两个模块 `import tempfile`，路径改为 `Path(tempfile.gettempdir()) / ...`（保持子目录名与结构不变）。
2. 新增 `tests/unit/test_no_hardcoded_tmp_paths.py`：AST 扫 `backend/**/*.py`，任何以 `/tmp/`
   开头的字符串常量即失败（注释/docstring 不算），并断言两处目标模块通过。
3. 验证：该 integration 用例在 Windows 本机转绿（或如实记录沙箱仍拦系统临时目录 —— 那是环境不是代码）；
   `tests/unit/agents`+`tests/unit/api` 相关子集绿；`ruff`/`format` 绿。

## 4. 验收

- [x] 两处不再硬编码 `/tmp`
- [x] 静态回归测试存在且通过；把路径改回 `/tmp/...` 会让它变红（突变自检已做：改回上传路径 →
      扫描用例红；恢复后绿）
- [x] 相关测试绿（`test_no_hardcoded_tmp_paths` 2 + publisher/text-cover/integration 共 62 passed；
      1 个 `test_text_cover` ERROR 为沙箱 tmp_path ACL 环境性）；**原来失败的那条 integration 用例在本机转绿**
- [x] Linux 语义不变（`gettempdir()` 默认 `/tmp`；可用 `TMPDIR` 覆盖，这是标准行为）

## 5. 不做什么

- 不做目录清理/保留策略（现状也是尽力而为，不引入新生命周期）。
- 不改部署文档（容器内 `/tmp` 语义不变）。
- 不动测试夹具里作为字符串输入的 `/tmp/x.jpg`（不产生 IO）。
