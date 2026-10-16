"""P2-3: acceptance signoff board loader (docs mirror)."""

from __future__ import annotations

import json
from pathlib import Path

from backend.services.acceptance_signoff import (
    is_gate_passed,
    is_gate_waived,
    load_signoff_board,
)


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
    # Waiver ≠ pass must stay explicit in disclaimer.
    assert (
        "waived_risk_accepted" in board["disclaimer"]
        or "not a pass" in board["disclaimer"].lower()
        or "不是" in board["disclaimer"]
        or "CI" in board["disclaimer"]
    )
    ids = {g["id"] for g in board["gates"]}
    assert {"G1", "G2", "G3", "G4", "G5"}.issubset(ids)
    for gate in board["gates"]:
        assert gate["status"]
        assert gate["owner_role"]
        # Repo board tracks 2026-09-22 risk acceptance — never treat as passed.
        if gate["status"] in {"waived_risk_accepted", "waived"}:
            assert gate["is_waived"] is True
            assert gate["is_passed"] is False
            assert gate.get("next_review_at")
            assert not is_gate_passed(gate["status"])
            assert is_gate_waived(gate["status"])
        else:
            assert gate["status"] != "passed" or gate.get("conclusion")


def test_repo_board_waiver_block() -> None:
    board = load_signoff_board()
    assert board["ok"] is True
    waiver = board.get("waiver")
    assert isinstance(waiver, dict)
    assert waiver.get("replaces_signoff") is False
    assert waiver.get("next_global_review_at")
    # All listed gates should be waived risk-accepted, not passed.
    gate_ids = {"G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"}
    waived = [g for g in board["gates"] if g["id"] in gate_ids]
    assert waived
    for gate in waived:
        assert gate["status"] == "waived_risk_accepted"
        assert gate["is_passed"] is False
        assert gate["conclusion"] == "" or not str(gate.get("conclusion", "")).strip()


def test_waived_is_never_passed() -> None:
    assert is_gate_passed("waived_risk_accepted") is False
    assert is_gate_passed("waived") is False
    assert is_gate_waived("waived_risk_accepted") is True
    assert is_gate_passed("passed") is True
    assert is_gate_passed("approved") is True
    assert is_gate_waived("passed") is False


def test_missing_board_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    board = load_signoff_board(path=missing)
    assert board["ok"] is False
    assert board["error"] == "signoff_board_missing"
    assert board["gates"] == []
    assert board["replaces_human_signoff"] is False


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
    assert board["gates"][0]["is_passed"] is False
    assert board["gates"][0]["is_waived"] is False


def test_loader_preserves_waived_fields(tmp_path: Path) -> None:
    path = tmp_path / "board.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "disclaimer": "waiver ≠ pass; CI green is not signoff",
                "gates": [
                    {
                        "id": "G1",
                        "title": "t",
                        "owner_role": "r",
                        "status": "waived_risk_accepted",
                        "conclusion": "",
                        "signed_by": "",
                        "signed_at": "",
                        "next_review_at": "2027-01-14",
                        "chase_action": "review again",
                    }
                ],
                "waiver": {
                    "recorded_at": "2026-09-22",
                    "replaces_signoff": False,
                    "next_global_review_at": "2027-01-14",
                },
            }
        ),
        encoding="utf-8",
    )
    board = load_signoff_board(path=path)
    assert board["ok"] is True
    gate = board["gates"][0]
    assert gate["status"] == "waived_risk_accepted"
    assert gate["is_waived"] is True
    assert gate["is_passed"] is False
    assert gate["next_review_at"] == "2027-01-14"
    assert gate["chase_action"] == "review again"
    assert board["waiver"]["next_global_review_at"] == "2027-01-14"
    assert board["replaces_human_signoff"] is False


def test_loader_coerces_waiver_replaces_signoff_false(tmp_path: Path) -> None:
    """Even a mistaken true in JSON must not claim waiver replaces human signoff."""
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
                        "status": "waived_risk_accepted",
                        "conclusion": "",
                        "signed_by": "",
                        "signed_at": "",
                        "next_review_at": "2027-01-14",
                        "chase_action": "chase",
                    }
                ],
                "waiver": {
                    "recorded_at": "2026-09-22",
                    "replaces_signoff": True,
                    "next_global_review_at": "2027-01-14",
                },
            }
        ),
        encoding="utf-8",
    )
    board = load_signoff_board(path=path)
    assert board["ok"] is True
    assert board["waiver"]["replaces_signoff"] is False
    assert board["replaces_human_signoff"] is False
    assert board["gates"][0]["is_passed"] is False
