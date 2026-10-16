"""P2-3: read-only Acceptance signoff board (docs mirror, not a write DB)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("xhs_growth.acceptance_signoff")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BOARD_PATH = _REPO_ROOT / "docs" / "acceptance" / "signoff-board.json"


def load_signoff_board(*, path: Path | None = None) -> dict[str, Any]:
    """Load the structured G1–G8 signoff board from docs/acceptance.

    Failures return an explicit error payload — never invent signed conclusions.
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
        }

    if not isinstance(raw, dict):
        return {
            "ok": False,
            "error": "signoff_board_invalid",
            "gates": [],
            "disclaimer": "Acceptance board must be a JSON object.",
        }

    gates = raw.get("gates") if isinstance(raw.get("gates"), list) else []
    return {
        "ok": True,
        "version": raw.get("version", 1),
        "source_doc": raw.get("source_doc") or "docs/acceptance/signoff-request-2026-09-22.md",
        "disclaimer": raw.get("disclaimer")
        or ("Documentation status mirror only — does NOT replace out-of-repo human signoff."),
        "updated_at": raw.get("updated_at"),
        "gates": gates,
        "waiver": raw.get("waiver"),
        "replaces_human_signoff": False,
    }


__all__ = ["load_signoff_board"]
