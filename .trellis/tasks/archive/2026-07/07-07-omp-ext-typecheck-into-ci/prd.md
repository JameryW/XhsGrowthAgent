# OMP 扩展 typecheck 纳入 CI

## Goal

OMP 扩展（`backend/omp/extensions/xhsagent-ext`，TypeScript）当前无 typecheck script，CI 不跑它。`tsc --noEmit` 本地能过（依赖已装），但无标准命令 + 无 CI 守护，类型回归易漏。加 `typecheck` script + CI job 让 OMP 扩展纳入持续类型检查。

## What I already know

- OMP 扩展：`backend/omp/extensions/xhsagent-ext/`，TypeScript，tsconfig strict。
- `@oh-my-pi/pi-coding-agent` 是 npmjs 公开包（registry.npmjs.org，v16.2.1），CI `npm install` 能装。
- `package.json` 被 git 跟踪；`package-lock.json` **被 .gitignore 排除**（未跟踪）→ CI 用 `npm install`（非 `npm ci`）。
- 本地 `npx tsc --noEmit` exit=0，typecheck 过。
- CI（.github/workflows/ci.yml）三 job 全 Python：lint-format / mypy / test。无 node/TS job。
- devDependencies：`@oh-my-pi/pi-coding-agent`、`@types/node`、`typescript`。

## Requirements

- OMP 扩展 package.json 加 `"scripts": {"typecheck": "tsc --noEmit"}`。
- CI 加 `omp-typecheck` job：
  - setup-node（node 20 LTS）
  - `cd backend/omp/extensions/xhsagent-ext && npm install`
  - `npm run typecheck`
- job 与现有三 job 并列（非依赖，并行跑）。

## Acceptance Criteria

- [ ] package.json 加 typecheck script
- [ ] ci.yml 加 omp-typecheck job
- [ ] CI 本地 act 或 push 后 job 绿（npm install 成功 + tsc 过）
- [ ] 现有三 job（lint-format/mypy/test）不受影响

## Definition of Done

- CI 全 4 job 绿
- package.json + ci.yml 改动 lint/格式过

## Out of Scope

- OMP 扩展纳入 ruff/eslint（仅 typecheck）
- package-lock.json 纳入 git（保持 ignore，CI 用 npm install）
- OMP 扩展 build/dist 产物

## Technical Notes

- 文件：`backend/omp/extensions/xhsagent-ext/package.json`、`.github/workflows/ci.yml`
- node 版本：20 LTS（actions/setup-node@v4）
- npm install 缓存：actions/setup-node cache: npm
- 风险：CI 首次跑 npm install 可能慢（@oh-my-pi 包大），但可接受
