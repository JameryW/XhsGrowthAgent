"""Shared contracts for the history/quality consistency rollout.

The analytics and evaluation routes deliberately keep their legacy payloads
backwards compatible, but they need one small piece of shared identity
metadata.  Keeping it here prevents each route from inventing a different
snapshot format or feature-flag parser.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

QUALITY_CONSISTENCY_FLAG = "QUALITY_CONSISTENCY_V2"
QUALITY_CONSISTENCY_CONTRACT = "quality_consistency.v2"
# Internal scope key for aggregate workflow reads. It is hashed into the
# opaque snapshot id and is never returned as a real account identifier.
ALL_ACCOUNTS_SCOPE = "__all_accounts__"


def quality_consistency_v2_enabled() -> bool:
    """Return whether the additive V2 contracts are enabled.

    V2 is on by default because the new fields and endpoints are additive.
    Operators can turn the rollout off without changing code while keeping
    the durable evaluation table and historical data intact.
    """

    raw = os.getenv(QUALITY_CONSISTENCY_FLAG, "1").strip().lower()
    return raw not in {"0", "false", "off", "no", "disabled"}


def snapshot_id(
    account_id: str | None,
    data_as_of: str | None,
    *,
    subject_versions: list[tuple[str, str]] | None = None,
) -> str | None:
    """Build a stable opaque snapshot identity for a response.

    ``data_as_of`` is the MVP snapshot boundary.  When callers have the
    complete note version list available, including it makes the identity
    change even if an older row was refreshed without moving the account
    timestamp.  The returned value contains no account or note identifiers.
    """

    account = str(account_id or "").strip()
    as_of = str(data_as_of or "").strip()
    if not account or not as_of:
        return None
    versions = sorted(
        (str(subject).strip(), str(version).strip())
        for subject, version in (subject_versions or [])
        if str(subject).strip()
    )
    payload: dict[str, Any] = {
        "account_id": account,
        "data_as_of": as_of,
        "subject_versions": versions,
    }
    encoded = repr(payload).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:32]
    return f"snapshot:{digest}"


def max_timestamp(*values: Any) -> str | None:
    """Return the lexicographically latest ISO timestamp-like value."""

    normalized = [str(value).strip() for value in values if str(value or "").strip()]
    return max(normalized) if normalized else None
