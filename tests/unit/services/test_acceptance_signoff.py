"""P2-3: acceptance signoff board loader (docs mirror)."""

from __future__ import annotations

import json
from pathlib import Path

from backend.services.acceptance_signoff import load_signoff_board


def test_load_repo_signoff_board() -> None:
    board = load_signoff_board()
    assert board["ok"] is True
    assert board["replaces_human_signoff"] is False
    assert (
        "does NOT replace" in board["disclaimer"]
        or "不能代替" in board["disclaimer"]
        or "never replaces" in board["disclaimer"].lower()
        or "Documentation" in board["disclaimer"]
    )
    ids = {g["id"] for g in board["gates"]}
    assert {"G1", "G2", "G3", "G4", "G5"}.issubset(ids)
    for gate in board["gates"]:
        assert gate["status"]
        assert gate["owner_role"]


def test_missing_board_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    board = load_signoff_board(path=missing)
    assert board["ok"] is False
    assert board["error"] == "signoff_board_missing"
    assert board["gates"] == []


def test_invalid_json_fails_closed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    board = load_signoff_board(path=bad)
    assert board["ok"] is False
    assert board["error"] == "signoff_board_unreadable"


def test_board_json_lists_g1_g5(tmp_path: Path) -> None:
    path = tmp_path / "board.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "disclaimer": "mirror only",
                "gates": [
                    {
                        "id": "G1",
                        "title": "t",
                        "owner_role": "r",
                        "status": "pending_human_signoff",
                        "conclusion": "",
                        "signed_by": "",
                        "signed_at": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    board = load_signoff_board(path=path)
    assert board["ok"] is True
    assert board["gates"][0]["id"] == "G1"
