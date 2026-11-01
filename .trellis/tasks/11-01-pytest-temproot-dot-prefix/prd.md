# test: pytest 临时根目录放回仓库内且点号前缀，避免污染 docs 引用扫描（票 5cb）

> 写 P3 提案时 `tests/unit/scripts` 出现两处假红，根因不在文档，而在**测试基础设施泄漏**：
> 沙箱系统 temp 不可写 → `tempfile.mkdtemp` 回落到仓库根 → 留下非点号前缀的
> `dsh-pytest-temproot-*` 目录 → docs 引用扫描把它当成"仓库自己的文件"，于是
> `postgres:15` / `localhost:8000` 这类 host:port 文本被解析成 `path:line` 引用。

## 1. 根因链（已核实）

| 环节 | 事实 |
|---|---|
| 沙箱系统 temp 不可写 | `tempfile.gettempdir()` 在本工作区返回的是**仓库根**（TEMP/TMP 指向系统目录但不可写，mkdtemp 回落到 cwd） |
| 旧 conftest | `tempfile.mkdtemp(prefix="dsh-pytest-temproot-")` 未指定 `dir`，于是建在仓库根 |
| 泄漏目录非点号前缀 | `docs_citation_rule._walk` 只跳过点号开头的路径成分，因此把这些目录当"我们的文件" |
| 假红两处 | `test_docs_citations::test_every_cited_line_number_in_the_corpus_resolves`：bare basename 多处匹配；`test_execution_plane_claims`：`line_number_references_in_this_document` 159→162 |

## 2. 修复（locked）

1. 在仓库内显式创建点号前缀根：`.dsh-pytest-temproot/`（`os.makedirs(mode=0o777)`，沙箱可写），
   把每次运行的 `PYTEST_DEBUG_TEMPROOT` 放进它 —— corpus 规则按"点号 = 不属于我们"跳过，
   即使残留也不会污染引用解析。
2. `.gitignore` 增加 `.dsh-pytest-temproot/`。
3. 删除本次会话已泄漏的 4 个 `dsh-pytest-temproot-*` 目录（已确认可删）。
4. 不改变 pytest fixture 语义：仍然是私有的 temproot，只是位置与命名变了。

## 3. 验证

- 泄漏目录清空后：`test_docs_citations.py` + `test_execution_plane_claims.py` **33 passed**
  （claim 回到 159）。
- `tests/unit/scripts` 全量：**108 passed**。
- 新运行产生的根目录为 `.dsh-pytest-temproot/`（点号 + gitignore）。
- 全量 pytest 见 notes。

## 4. 不做什么

- 不改测试对 `tmp_path` 的使用；不删除 `.pytest-*` / `tmpprobe-*` 这些历史 ACL 目录
  （它们不可读、被 os.walk 的默认错误处理跳过，且 gitignore/不可见）。
