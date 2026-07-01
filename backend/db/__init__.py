"""Database layer — workflow metadata + account/credential management via PostgreSQL."""

from backend.db.accounts import (
    CREDENTIAL_KEYS,
    XHS_KEYS,
    AccountRow,
    CredentialRow,
    activate_credentials,
    create_account,
    deactivate_credentials,
    delete_account,
    delete_credential,
    get_account,
    get_account_cookie,
    get_active_account,
    list_accounts,
    list_credentials,
    load_active_credentials,
    set_active_account,
    set_credentials,
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
from backend.db.evaluator_config import (
    DEFAULT_DIMENSION_WEIGHTS,
    DEFAULT_WEIGHTS,
    EvaluatorSample,
    EvaluatorWeights,
    backfill_engagement,
    export_samples,
    insert_sample,
    list_weights,
    load_weights,
    set_weight,
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
    "CREDENTIAL_KEYS",
    "XHS_KEYS",
    "create_account",
    "delete_account",
    "get_account",
    "get_active_account",
    "get_account_cookie",
    "list_accounts",
    "set_active_account",
    "update_account",
    "list_credentials",
    "set_credentials",
    "delete_credential",
    "activate_credentials",
    "deactivate_credentials",
    "load_active_credentials",
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
    # Evaluator config (learnable grader weights + training samples)
    "DEFAULT_DIMENSION_WEIGHTS",
    "DEFAULT_WEIGHTS",
    "EvaluatorSample",
    "EvaluatorWeights",
    "backfill_engagement",
    "ensure_evaluator_config_tables",
    "export_samples",
    "insert_sample",
    "list_weights",
    "load_weights",
    "set_weight",
]
