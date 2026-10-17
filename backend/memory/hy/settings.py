"""Hy Memory (hy-memory) 集成配置 — 混元双系统认知记忆引擎。

默认关闭（``enabled=False``）：不配置 LLM/Embedder 端点时整个集成是零成本的
no-op，import 也不会发生（SDK 是可选依赖，见 pyproject ``memory-hy`` extra）。
启用后 XhsGrowthAgent 的记忆体系变成两层：

- 既有层：LangGraph BaseStore 命名空间记忆（``backend.memory.store`` /
  ``backend.memory.creative``）——结构化记录，SQL/向量检索。
- hy-memory 层：双系统认知记忆——chat 场景沉淀账号画像（L0-L7 层级）、
  working 场景沉淀可复用经验（facts + experiences），跨会话连续。

所有配置通过 ``HYMEMORY_`` 前缀环境变量注入（见 .env.example）。
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

#: SDK 支持的运行档位（hy_memory.HyMemoryClient.VALID_MODES）。
#: - lite : 纯原始记忆 + 向量检索，零 LLM 调用，摄取最快
#: - pro  : LLM 抽取 + 冲突调和，标准负载
#: - ultra: + System 2 图式归纳（evolve() 触发），需要图存储
HY_MODES: tuple[str, ...] = ("lite", "pro", "ultra")

#: SDK 支持的记忆场景（hy_memory.HyMemoryClient）。
#: - chat    : 闲聊/个人信息/偏好 —— L0-L7 层级记忆
#: - working : 生产力工作 —— 两层记忆（session facts + 可复用 experiences）
#: - coding  : 软件工程 —— working 两层 + 代码版本演化链
HY_SCENES: tuple[str, ...] = ("chat", "working", "coding")


class HyMemorySettings(BaseSettings):
    """Hy Memory 集成配置（默认全部关闭）。"""

    # 总开关。False 时 bridge 是 no-op：不建 client、不发任何请求。
    enabled: bool = False

    # 运行档位：lite / pro / ultra（见 HY_MODES）。
    mode: str = "lite"

    # ── LLM 端点（pro/ultra 抽取与调和用；lite 可留空）──
    # 任何 OpenAI 兼容服务均可（DeepSeek / DashScope / OpenAI …）。
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

    # ── Embedder 端点（向量检索必需；lite 也需要）──
    embedder_api_key: str = ""
    embedder_base_url: str = ""
    embedder_model: str = ""
    embedding_dims: int = 0  # 0 = 用模型默认维度

    # ── 存储 ──
    # 数据目录（Chroma 持久化 + SQLite 元数据 + SDK 日志）。
    # 空 = SDK 默认 ~/.hy_memory。容器部署应指向持久卷。
    data_dir: str = ""

    # ── 行为 ──
    # 默认场景：未显式指定 scene 时的落点。账号画像/偏好走 chat，
    # 工作流经验走 working。
    default_scene: str = "chat"
    # source 隔离标签：search 时用 include_sources/exclude_sources 区分调用方，
    # 与本服务的 LangGraph 记忆互不串味。
    source: str = "xhs_growth"
    # 单次 recall 的默认条数。
    default_limit: int = Field(default=5, ge=1, le=50)

    model_config = {"env_prefix": "HYMEMORY_", "env_file": ".env", "extra": "ignore"}
