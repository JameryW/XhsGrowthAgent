# 本地中文 embedding 替代 DeepSeek 404

## Goal

用本地 CPU 运行的中文 embedding 模型（bge-small-zh-v1.5）替代当前指向 DeepSeek 的 embedding 配置，修复 analyst 节点 `store_insight` / `_recall_memory` 触发的 `openai.NotFoundError: 404`（DeepSeek 无 embedding API）。本地运行无 API 成本、无外部依赖、CPU 可行。

## What I already know

### 根因（已排查）
- `.env`: `XHS_EMBED_MODEL=openai_compatible:deepseek-embedding` + `XHS_EMBED_BASE_URL=https://api.deepseek.com`
- DeepSeek **没有 embedding API**：`/v1/embeddings` 对所有模型名（deepseek-embedding / text-embedding-3-small 等）返回 404 空响应
- analyst.py:95 `mm.store_insight(...)` 写记忆时调 embedding → 404 → AgentError → workflow 卡在 analyst
- `_recall_memory` 同样 404

### 当前 embedding 架构（backend/memory/index.py）
- `_build_embeddings(provider, model_name)` 只支持 `openai` / `openai_compatible`（都走 langchain_openai）
- `_PROVIDER_KEY_MAP`: openai/openai_compatible 都需 `OPENAI_API_KEY`
- `get_store_index()`: 无 key → 返回 None（降级为无语义搜索，不报错）
- 配置：`XHS_EMBED_MODEL`（provider:model 格式）、`XHS_EMBED_DIMS`、`XHS_EMBED_BASE_URL`
- `get_prod_store_index()`: 加 `distance_type=cosine`

### 选定方案
- 模型：**BAAI/bge-small-zh-v1.5**（512 维，~100MB，中文优化，CPU 友好）
- 本地推理：`sentence-transformers` + `langchain-huggingface` 的 `HuggingFaceEmbeddings`
- 维度：512（当前 1536，需改 `XHS_EMBED_DIMS`）
- 旧向量：清空 Postgres `store_vectors` 表（旧 1536 维数据与新 512 维不兼容）

### CPU 可行性
- bge-small-zh-v1.5: 3 层 transformer，24M 参数，单句 CPU 推理 20-50ms
- 场景是记忆库写入/检索（低频），CPU 绰绰有余
- sentence-transformers 默认 CPU 推理，无需 GPU 配置
- 首次启动下载模型 ~100MB，容器需 HuggingFace 镜像源（`HF_ENDPOINT=https://hf-mirror.com`）防网络受限

## Requirements

- 新增 `local` embedding provider，用 HuggingFaceEmbeddings 本地推理
- `.env` 改为 `XHS_EMBED_MODEL=local:BAAI/bge-small-zh-v1.5` + `XHS_EMBED_DIMS=512`
- `local` provider 无需 API key（跳过 _PROVIDER_KEY_MAP 检查）
- 清空 Postgres store_vectors 表（旧 1536 维向量不兼容）
- 容器部署加 `HF_ENDPOINT=https://hf-mirror.com` 环境变量
- 部署后 analyst store_insight 不再 404，memory store 语义搜索正常

## Acceptance Criteria

- [ ] `local` provider 在 _build_embeddings 实现，用 HuggingFaceEmbeddings
- [ ] `local` provider 跳过 API key 检查
- [ ] `.env` 配置改为 bge-small-zh-v1.5 + 512 维
- [ ] Postgres store_vectors 表清空（或重建）
- [ ] 部署后健康检查 memory_store 语义索引 enabled
- [ ] analyst 节点 store_insight 不再 404（端到端验证 workflow 跑过 analyst）
- [ ] 单测覆盖 local provider 构造逻辑

## Out of Scope

- 其他 embedding 模型支持（只加 local，bge-small-zh 固定）
- 已有向量数据迁移（直接清空）
- GPU 加速配置（CPU 足够）
- 多 embedding provider 动态切换

## Technical Notes

- 关键文件：backend/memory/index.py、.env、scripts/deploy.sh（传 HF_ENDPOINT）、Dockerfile（装 sentence-transformers）
- 依赖：sentence-transformers、langchain-huggingface（加到 pyproject.toml dependencies）
- 模型名：BAAI/bge-small-zh-v1.5（HuggingFace Hub）
- 维度：512
- Postgres store_vectors 表：AsyncPostgresStore 自动创建，清空用 TRUNCATE 或 drop/recreate
- spec: workflow-state.md / memory 相关 spec 需同步更新 embedding provider 说明
