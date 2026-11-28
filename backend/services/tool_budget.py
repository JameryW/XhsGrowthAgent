"""Per-tool payload budget at the Tool Gateway (ledger scheme #46).

The ledger's TRACER slice says an agent re-uses roughly a quarter of what a
tool hands back, and that the rest is spent again on every context compile.
This module makes that claim *measurable* on a real deployment and, when the
operator asks for it, trimmable — without touching a single call site.

Two gaps had to be closed before any of this could be wired, and they are why
the contract layer in :mod:`backend.services.interaction_contracts` was dead
code until now:

* **Contract keys never matched capability ids.** ``RETENTION_CONTRACTS`` is
  keyed by the pre-runtime tool names (``xhs_trending``), while the Gateway is
  addressed by capability ids (``xhs.trending``). A lookup by capability
  silently found nothing. :data:`CAPABILITY_CONTRACTS` is the explicit alias
  table; :func:`contract_for` is the only place that translates.
* **Payloads are not always mappings.** ``xhs.trending`` and
  ``xhs.competitor_analyzer`` return ``list[dict]``
  (``backend/agents/trend_scout.py``). Per-row field projection would change
  the meaning of the rows, so list payloads are measured only.

Modes (``XHS_TOOL_BUDGET``):

``off`` (default)
    Nothing is computed, no field is added, the trace event keeps exactly the
    keys it has today — byte-identical to a deployment without this module.
``report``
    Account for every successful call: original/projected characters,
    retention ratio, and the keys a trim *would* drop. ``value`` is untouched,
    so the only thing that changes is the data the operator can read.
``trim``
    ``report`` plus: a mapping payload with a contract is replaced by its
    projection, and the full payload travels back in
    ``ToolResult.full_value`` so a caller that needs it can recover it. List
    and scalar payloads still pass through untouched.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from backend.services.interaction_contracts import (
    RETENTION_CONTRACTS,
    RetentionContract,
    project_tool_output,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CAPABILITY_CONTRACTS",
    "TOOL_BUDGET_ENV",
    "BudgetMode",
    "PayloadShape",
    "ProjectionReport",
    "UNMATCHED_CONTRACTS",
    "budget_enabled",
    "budget_mode",
    "contract_for",
    "payload_shape",
    "project_capability",
]

TOOL_BUDGET_ENV = "XHS_TOOL_BUDGET"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_warned_unknown = False


class BudgetMode(StrEnum):
    """How much this deployment wants from the payload accounting."""

    OFF = "off"
    REPORT = "report"
    TRIM = "trim"


class PayloadShape(StrEnum):
    """What the tool actually returned — the trimming question depends on it."""

    MAPPING = "mapping"
    LIST = "list"
    SCALAR = "scalar"


CAPABILITY_CONTRACTS: dict[str, str] = {
    "xhs.trending": "xhs_trending",
    "xhs.competitor_analyzer": "competitor_analyzer",
    "xhs.keyword_monitor": "keyword_monitor",
    "ripple.predict_spread": "ripple_predict",
}
"""Capability id -> ``RETENTION_CONTRACTS`` key.

Hand-written on purpose: the two id spaces were introduced in different slices
and no derivation can prove they line up. A test pins every entry to a real
contract key and to a real catalogue capability, so a rename on either side
fails loudly instead of silently disabling the accounting.
"""

UNMATCHED_CONTRACTS: tuple[str, ...] = ("analytics_reader",)
"""Contracts with no capability behind them today.

``analytics_reader`` predates the analytics read path that goes through
``xhs.*`` capabilities; keeping it declared makes the gap visible instead of
deleting a contract nobody had noticed was unreachable.
"""


def budget_mode() -> BudgetMode:
    """Read the switch. Any unknown value is ``off`` — never a guess."""
    global _warned_unknown
    raw = os.environ.get(TOOL_BUDGET_ENV, "").strip().lower()
    if not raw or raw == BudgetMode.OFF:
        return BudgetMode.OFF
    if raw == BudgetMode.REPORT or raw in _TRUTHY:
        return BudgetMode.REPORT
    if raw == BudgetMode.TRIM:
        return BudgetMode.TRIM
    if not _warned_unknown:
        _warned_unknown = True
        logger.warning(
            "unknown %s value %r, treating as off (expected off/report/trim)",
            TOOL_BUDGET_ENV,
            raw,
        )
    return BudgetMode.OFF


def budget_enabled() -> bool:
    return budget_mode() is not BudgetMode.OFF


def contract_for(capability: str) -> RetentionContract | None:
    """The retention contract behind this capability, if any."""
    key = CAPABILITY_CONTRACTS.get(capability)
    if key is None:
        return None
    return RETENTION_CONTRACTS.get(key)


def payload_shape(value: Any) -> PayloadShape:
    if isinstance(value, Mapping):
        return PayloadShape.MAPPING
    if isinstance(value, (list, tuple)):
        return PayloadShape.LIST
    return PayloadShape.SCALAR


def _json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


@dataclass(frozen=True)
class ProjectionReport:
    """What the gateway could have dropped, and what it did drop."""

    capability: str
    mode: str
    contract: str
    shape: str
    original_chars: int
    projected_chars: int
    retention_ratio: float
    dropped_keys: tuple[str, ...] = ()
    trimmed: bool = False
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "mode": self.mode,
            "contract": self.contract,
            "shape": self.shape,
            "original_chars": self.original_chars,
            "projected_chars": self.projected_chars,
            "retention_ratio": round(self.retention_ratio, 4),
            "dropped_keys": list(self.dropped_keys),
            "trimmed": self.trimmed,
            "note": self.note,
        }


def _measure_mapping(
    capability: str,
    payload: Mapping[str, Any],
    contract: RetentionContract | None,
    mode: BudgetMode,
) -> tuple[ProjectionReport, Mapping[str, Any]]:
    original = _json_chars(payload)
    if contract is None:
        return (
            ProjectionReport(
                capability=capability,
                mode=mode.value,
                contract="",
                shape=PayloadShape.MAPPING.value,
                original_chars=original,
                projected_chars=original,
                retention_ratio=1.0,
                note="no_retention_contract",
            ),
            payload,
        )
    projection = project_tool_output(contract.tool, payload, max_chars=contract.max_chars)
    dropped = tuple(key for key in payload if key not in projection.payload)
    trimmed = mode is BudgetMode.TRIM
    return (
        ProjectionReport(
            capability=capability,
            mode=mode.value,
            contract=contract.tool,
            shape=PayloadShape.MAPPING.value,
            original_chars=projection.original_chars,
            projected_chars=projection.projected_chars,
            retention_ratio=projection.retention_ratio,
            dropped_keys=dropped,
            trimmed=trimmed,
            note="trimmed" if trimmed else "measured_only",
        ),
        projection.payload if trimmed else payload,
    )


def _measure_other(
    capability: str, value: Any, shape: PayloadShape, mode: BudgetMode
) -> ProjectionReport:
    size = _json_chars(value)
    note = (
        "list_payload_measured_only"
        if shape is PayloadShape.LIST
        else "scalar_payload_measured_only"
    )
    return ProjectionReport(
        capability=capability,
        mode=mode.value,
        contract="",
        shape=shape.value,
        original_chars=size,
        projected_chars=size,
        retention_ratio=1.0,
        note=note,
    )


def project_capability(
    capability: str,
    value: Any,
    *,
    mode: BudgetMode | None = None,
) -> tuple[ProjectionReport, Any]:
    """Measure one successful payload, and return what the caller should see.

    The second element is the payload to hand back: identical to ``value``
    unless this is ``trim`` mode with a mapping-shaped payload that has a
    contract. Returning the pair (instead of mutating) keeps the Gateway's
    success path linear and makes the report impossible to forget.
    """
    resolved = budget_mode() if mode is None else mode
    shape = payload_shape(value)
    contract = contract_for(capability)
    if shape is PayloadShape.MAPPING:
        return _measure_mapping(capability, value, contract, resolved)
    return _measure_other(capability, value, shape, resolved), value
