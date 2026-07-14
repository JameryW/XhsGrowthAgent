# 修复 CI 断言失败

## Goal

修复当前分支在 CI/全量测试中暴露的断言失败，保持现有功能行为不回退，并让与本次变更相关的后端、前端和 OMP 检查可重复通过。

## What I already know

* 当前分支为 `feat/historical-note-detail-quality`，工作树初始干净。
* `.github/workflows/ci.yml` 执行 Ruff、Mypy、全量 Pytest 和 OMP TypeScript typecheck。
* 近期本地全量前端 Vitest 曾出现多组既有断言失败，集中在错误卡片、离线恢复、引导、骨架屏、进度阶段文案和 loading composable。
* 本地后端全量 Pytest 在集成健康检查处出现请求阻塞，需要区分环境/依赖问题与真正断言失败。

## Assumptions

* “CI 问题”包含 CI 会执行的后端质量门禁，以及当前工作树中可复现的前端断言失败；不以跳过测试或放宽断言作为修复。
* 修复应优先调整产品代码/测试契约的一致性，只有测试本身明确过时才更新测试。

## Requirements

* [ ] 收集并分类 CI 相关命令及全量前端测试的所有失败。
* [ ] 修复每个可复现的断言失败或导致 CI 阻塞的根因。
* [ ] 保留既有 API/组件对外契约，并补充回归覆盖。
* [ ] 验证 Ruff、Mypy、后端 Pytest、前端 type-check/build/Vitest、OMP typecheck。

## Acceptance Criteria

* [ ] 失败测试不再出现，或有明确的环境性证据并通过稳健的测试隔离修复。
* [ ] 不使用 `skip`、放宽断言、删除测试或降低 CI 检查标准来“修复”问题。
* [ ] 所有改动有清晰的测试结果记录。

## Definition of Done

* 测试和 lint/typecheck 按项目 CI 命令通过。
* 必要时更新规格/测试说明。
* 代码已提交，工作树干净。

## Out of Scope

* 与当前失败无关的新功能。
* 重写测试框架或替换 CI 平台。

## Technical Notes

* CI workflow: `.github/workflows/ci.yml`
* Frontend scripts: `frontend/package.json`
* Backend test config: `pyproject.toml`
