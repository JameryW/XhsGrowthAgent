"""Database layer — workflow metadata + account/credential management via PostgreSQL."""

from backend.db.accounts import (
    AccountRow,
    CredentialRow,
    create_account,
    delete_account,
    get_account,
    get_account_cdp_endpoint,
    get_active_account,
    list_accounts,
    list_credentials,
    set_active_account,
    update_account,
)
from backend.db.accounts import (
    ensure_tables as ensure_account_tables,
)
from backend.db.console_users import (
    ConsoleUserRow,
    bootstrap_default_user,
    create_user,
    delete_user,
    list_users,
    update_password,
    verify_login,
)
from backend.db.console_users import (
    ensure_tables as ensure_console_users_tables,
)
from backend.db.creative_memory import (
    ensure_tables as ensure_creative_memory_tables,
)
from backend.db.creative_memory import (
    list_materials,
    list_plays,
    list_styles,
    upsert_material,
    upsert_play,
    upsert_style,
)
from backend.db.creator_stats import (
    ensure_tables as ensure_creator_stats_tables,
)
from backend.db.creator_stats import (
    get_account_stats,
    get_note_stats,
    list_note_stats,
    upsert_account_stats,
    upsert_note_stats,
    upsert_notes,
)
from backend.db.evaluator_config import (
    BIAS_SEVERITY_LEVELS,
    BIAS_SEVERITY_NOTES,
    DEFAULT_DIMENSION_WEIGHTS,
    DEFAULT_WEIGHTS,
    WEIGHTED_DIMENSIONS,
    EvaluatorSample,
    EvaluatorWeights,
    PromptEpoch,
    TrainingReport,
    activate_epoch,
    avg_bias_score,
    backfill_engagement,
    create_epoch,
    export_samples,
    fetch_labeled_samples,
    fetch_trend,
    fit_weights,
    get_active_epoch,
    insert_sample,
    list_epochs,
    list_weights,
    load_weights,
    set_weight,
    train_weights,
)
from backend.db.evaluator_config import (
    ensure_tables as ensure_evaluator_config_tables,
)
from backend.db.pool import close_pool, get_pool, init_pool, is_pool_ready
from backend.db.system_config import (
    SYSTEM_KEY_GROUPS,
    SYSTEM_KEYS,
    SystemConfigRow,
    activate_system_config,
    bootstrap_from_environ,
    list_config,
    migrate_from_accounts,
    set_config,
)
from backend.db.system_config import (
    ensure_tables as ensure_system_config_tables,
)
from backend.db.workflows import (
    WorkflowRow,
    create_workflow,
    delete_workflow,
    get_workflow,
    list_workflows,
    update_workflow,
)

__all__ = [
    "get_pool",
    "init_pool",
    "close_pool",
    "is_pool_ready",
    "WorkflowRow",
    "create_workflow",
    "get_workflow",
    "list_workflows",
    "update_workflow",
    "delete_workflow",
    "AccountRow",
    "CredentialRow",
    "create_account",
    "delete_account",
    "get_account",
    "get_active_account",
    "get_account_cdp_endpoint",
    "list_accounts",
    "set_active_account",
    "update_account",
    "list_credentials",
    "ensure_account_tables",
    # Console users
    "ConsoleUserRow",
    "bootstrap_default_user",
    "create_user",
    "delete_user",
    "list_users",
    "update_password",
    "verify_login",
    "ensure_console_users_tables",
    # System config
    "SystemConfigRow",
    "SYSTEM_KEYS",
    "SYSTEM_KEY_GROUPS",
    "activate_system_config",
    "bootstrap_from_environ",
    "list_config",
    "migrate_from_accounts",
    "set_config",
    "ensure_system_config_tables",
    # Evaluator config (learnable grader weights + training samples + prompt epochs)
    "BIAS_SEVERITY_LEVELS",
    "BIAS_SEVERITY_NOTES",
    "DEFAULT_DIMENSION_WEIGHTS",
    "DEFAULT_WEIGHTS",
    "EvaluatorSample",
    "EvaluatorWeights",
    "PromptEpoch",
    "TrainingReport",
    "WEIGHTED_DIMENSIONS",
    "activate_epoch",
    "avg_bias_score",
    "backfill_engagement",
    "create_epoch",
    "ensure_evaluator_config_tables",
    "export_samples",
    "fetch_labeled_samples",
    "fetch_trend",
    "fit_weights",
    "get_active_epoch",
    "insert_sample",
    "list_epochs",
    "list_weights",
    "load_weights",
    "set_weight",
    "train_weights",
    # Creator-center stats
    "ensure_creator_stats_tables",
    "get_account_stats",
    "get_note_stats",
    "list_note_stats",
    "upsert_account_stats",
    "upsert_note_stats",
    "upsert_notes",
    # Durable creative memory (style DNA / playbook / materials)
    "ensure_creative_memory_tables",
    "list_materials",
    "list_plays",
    "list_styles",
    "upsert_material",
    "upsert_play",
    "upsert_style",
]
