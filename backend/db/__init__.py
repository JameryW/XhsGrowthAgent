"""Database layer — workflow metadata + account/credential management via PostgreSQL."""

from backend.db.accounts import (
    CREDENTIAL_KEYS,
    AccountRow,
    CredentialRow,
    activate_credentials,
    create_account,
    deactivate_credentials,
    delete_account,
    delete_credential,
    get_account,
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
from backend.db.pool import close_pool, get_pool, init_pool, is_pool_ready
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
    "create_account",
    "delete_account",
    "get_account",
    "get_active_account",
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
]
