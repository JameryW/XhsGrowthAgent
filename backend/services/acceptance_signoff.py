"""P2-3: read-only Acceptance signoff board (docs mirror, not a write DB)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("xhs_growth.acceptance_signoff")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BOARD_PATH = _REPO_ROOT / "docs" / "acceptance" / "signoff-board.json"

# Statuses that mean a human signed the gate as pass/approve.
_PASSED_STATUSES = frozenset({"passed", "approved", "signed_pass"})
# Risk-acceptance waiver — must never be treated as pass.
_WAIVED_STATUSES = frozenset({"waived_risk_accepted", "waived"})


def is_gate_passed(status: str | None) -> bool:
    """True only for explicit human pass/approve — waived is never pass."""
    if not status:
        return False
    normalized = str(status).strip().lower()
    if normalized in _WAIVED_STATUSES:
        return False
    return normalized in _PASSED_STATUSES


def is_gate_waived(status: str | None) -> bool:
    """True when status is risk-accepted waiver (not a pass)."""
    if not status:
        return False
    return str(status).strip().lower() in _WAIVED_STATUSES


def load_signoff_board(*, path: Path | None = None) -> dict[str, Any]:
    """Load the structured G1–G8 signoff board from docs/acceptance.

    Failures return an explicit error payload — never invent signed conclusions.
    Waived gates stay waived; CI green must never become pass.
    """
    board_path = path or _BOARD_PATH
    try:
        raw = json.loads(board_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("acceptance signoff board missing: %s", board_path)
        return {
            "ok": False,
            "error": "signoff_board_missing",
            "path": str(board_path.relative_to(_REPO_ROOT))
            if board_path.is_relative_to(_REPO_ROOT)
            else str(board_path),
            "disclaimer": (
                "Acceptance board file is missing. This surface never replaces "
                "out-of-repo human signoff."
            ),
            "gates": [],
            "replaces_human_signoff": False,
        }
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("acceptance signoff board unreadable: %s", exc)
        return {
            "ok": False,
            "error": "signoff_board_unreadable",
            "message": str(exc),
            "gates": [],
            "disclaimer": (
                "Acceptance board could not be parsed. This surface never replaces "
                "out-of-repo human signoff."
            ),
            "replaces_human_signoff": False,
        }

    if not isinstance(raw, dict):
        return {
            "ok": False,
            "error": "signoff_board_invalid",
            "gates": [],
            "disclaimer": "Acceptance board must be a JSON object.",
            "replaces_human_signoff": False,
        }

    gates_candidate = raw.get("gates")
    gates_raw: list[Any] = gates_candidate if isinstance(gates_candidate, list) else []
    gates: list[dict[str, Any]] = []
    for item in gates_raw:
        if not isinstance(item, dict):
            continue
        gate = dict(item)
        # Preserve waiver fields; never coerce waived → passed.
        status = gate.get("status")
        if is_gate_waived(status if isinstance(status, str) else None):
            gate["is_passed"] = False
            gate["is_waived"] = True
        else:
            gate["is_passed"] = is_gate_passed(status if isinstance(status, str) else None)
            gate["is_waived"] = False
        gates.append(gate)

    waiver_raw = raw.get("waiver")
    if isinstance(waiver_raw, dict):
        waiver: Any = dict(waiver_raw)
        # Contract: risk acceptance never replaces human signoff.
        waiver["replaces_signoff"] = False
    else:
        waiver = waiver_raw

    return {
        "ok": True,
        "version": raw.get("version", 1),
        "source_doc": raw.get("source_doc") or "docs/acceptance/signoff-request-2026-09-22.md",
        "chase_checklist": raw.get("chase_checklist"),
        "disclaimer": raw.get("disclaimer")
        or (
            "Documentation status mirror only — does NOT replace out-of-repo human signoff. "
            "waived_risk_accepted is not a pass; CI green must never count as signoff."
        ),
        "updated_at": raw.get("updated_at"),
        "gates": gates,
        "waiver": waiver,
        "replaces_human_signoff": False,
    }


__all__ = ["load_signoff_board", "is_gate_passed", "is_gate_waived"]
