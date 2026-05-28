from pydantic_settings import BaseSettings
from pydantic import Field


class ModelSettings(BaseSettings):
    """LLM 模型配置"""

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""

    # 默认模型分配 — 全部使用 mimo-v2.5-pro
    model_routing: dict[str, str] = Field(
        default_factory=lambda: {
            "routing": "mimo-v2.5-pro",
            "scouting": "mimo-v2.5-pro",
            "strategy": "mimo-v2.5-pro",
            "writing": "mimo-v2.5-pro",
            "visual": "mimo-v2.5-pro",
            "analysis": "mimo-v2.5-pro",
            "publishing": "mimo-v2.5-pro",
            "engagement": "mimo-v2.5-pro",
        }
    )

    # 成本控制
    daily_budget_usd: float = 10.0

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}


class XHSPlatformSettings(BaseSettings):
    """小红书平台配置"""

    cookie: str = ""
    user_id: str = ""
    api_base: str = "https://edith.xiaohongshu.com"
    use_browser: bool = False
    headless: bool = True

    model_config = {"env_prefix": "XHS_", "env_file": ".env", "extra": "ignore"}


class DatabaseSettings(BaseSettings):
    """数据库配置"""

    postgres_uri: str = "postgresql://xhs:xhs@localhost:5432/xhs_growth"
    redis_uri: str = "redis://localhost:6379/0"

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}


class WorkflowSettings(BaseSettings):
    """工作流配置"""

    auto_publish: bool = False
    review_required: bool = True
    max_retries: int = 3
    scout_interval_hours: int = 6
    post_interval_hours: int = 4
    analytics_interval_hours: int = 12
    engagement_check_interval_min: int = 30

    model_config = {"env_prefix": "WORKFLOW_", "env_file": ".env", "extra": "ignore"}


class RippleSettings(BaseSettings):
    """Ripple CAS 引擎配置"""

    base_url: str = "http://127.0.0.1:8081"
    api_token: str = ""
    default_max_waves: int = 8
    default_simulation_horizon: str = "48h"
    default_ensemble_runs: int = 1
    request_timeout: int = 300
    enabled: bool = True

    model_config = {"env_prefix": "RIPPLE_", "env_file": ".env", "extra": "ignore"}


class NotificationSettings(BaseSettings):
    """通知配置"""

    webhook_url: str = ""
    notify_on_review: bool = True
    notify_on_publish: bool = True
    notify_on_error: bool = True

    model_config = {"env_prefix": "NOTIFICATION_", "env_file": ".env", "extra": "ignore"}


class AuthSettings(BaseSettings):
    """认证配置"""

    secret_key: str = "dev-secret-key-change-in-production"
    token_expire_hours: int = 24
    admin_username: str = "admin"
    admin_password: str = "admin123"  # Plain password for demo; use hash in production

    model_config = {"env_prefix": "AUTH_", "env_file": ".env", "extra": "ignore"}


class Settings(BaseSettings):
    """全局配置聚合"""

    models: ModelSettings = Field(default_factory=ModelSettings)
    platform: XHSPlatformSettings = Field(default_factory=XHSPlatformSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    notification: NotificationSettings = Field(default_factory=NotificationSettings)
    ripple: RippleSettings = Field(default_factory=RippleSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)

    model_config = {"env_file": ".env", "extra": "ignore"}
