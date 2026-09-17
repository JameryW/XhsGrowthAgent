"""Text files this project persists are UTF-8, whatever the host locale says.

Two production paths opened or wrote text with the platform default codec. On a
GBK host that meant every agent prompt with Chinese failed to load, and a
workflow history file written on one locale could not be read back on another —
the reader swallowed the failure and reported "no history", so state vanished
silently rather than erroring.

These assertions pin exact UTF-8 bytes rather than "decodes with the default
codec", so they hold on every platform and still fail if the codec is dropped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

CHINESE = "春季通勤穿搭"
HISTORY_NAME = "encoding-roundtrip"


@pytest.fixture
def history_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the writer and the reader at one temporary history directory."""
    from backend.api.routes import _runner, _wf_artifacts

    registry = tmp_path / "registry"
    history = registry / "history"
    history.mkdir(parents=True)
    monkeypatch.setenv("XHS_REGISTRY_PATH", str(registry))
    monkeypatch.setattr(_wf_artifacts, "_HISTORY_DIR", history)
    _runner._LAST_HISTORY_WRITE.pop(HISTORY_NAME, None)
    return history


def test_history_writer_emits_exact_utf8_bytes(history_dir: Path) -> None:
    """The serialized state must be UTF-8 bytes, not locale-dependent bytes."""
    from backend.api.routes import _runner

    _runner._save_history_file(HISTORY_NAME, {"note_title": CHINESE, "v": 1})

    written = (history_dir / f"{HISTORY_NAME}.json").read_bytes()
    assert CHINESE.encode("utf-8") in written
    assert written == written.decode("utf-8").encode("utf-8")


def test_history_round_trips_chinese_through_production_readers(history_dir: Path) -> None:
    """Write through the runner, read back through the workflow loader."""
    from backend.api.routes import _runner, _wf_artifacts

    _runner._save_history_file(HISTORY_NAME, {"note_title": CHINESE, "phase": "creating"})

    loaded: dict[str, Any] | None = _wf_artifacts._load_history_file(HISTORY_NAME)

    # The reader's `except Exception` turns an undecodable file into None, so a
    # codec mismatch here would present as missing history, not as an error.
    assert loaded is not None
    assert loaded["note_title"] == CHINESE


def test_history_reader_accepts_utf8_written_without_the_platform_codec(history_dir: Path) -> None:
    """A UTF-8 file from another locale must load even when the host codec differs.

    Written by hand as explicit UTF-8 so this does not depend on the writer,
    which is what lets it exercise a GBK host reading a UTF-8 file.
    """
    import json

    from backend.api.routes import _wf_artifacts

    payload = json.dumps({"note_title": CHINESE, "phase": "completed"}, ensure_ascii=False)
    (history_dir / f"{HISTORY_NAME}.json").write_bytes(payload.encode("utf-8"))

    loaded = _wf_artifacts._load_history_file(HISTORY_NAME)

    assert loaded is not None
    assert loaded["note_title"] == CHINESE


def test_prompt_loader_reads_a_utf8_prompt_regardless_of_host_locale() -> None:
    """Agent prompts carry Chinese copy and must not depend on the host codec."""
    from backend.agents.base import BaseAgent
    from backend.config.models import TaskType

    prompts_dir = Path("backend/config/prompts").resolve()
    prompt_file = prompts_dir / "_test_encoding_prompt.yaml"
    prompt_file.write_text(
        f'system: "你是{CHINESE}领域的写手"\nuser_template: "为 {{topic}} 生成标题"\n',
        encoding="utf-8",
    )

    class ChinesePromptAgent(BaseAgent):
        task_type = TaskType.WRITING
        agent_name = "encoding"
        prompt_file = "_test_encoding_prompt.yaml"

        async def execute(self, state, store):  # type: ignore[override,no-untyped-def]
            return {}

    try:
        loaded = ChinesePromptAgent()._load_prompt()
        assert loaded["system"] == f"你是{CHINESE}领域的写手"
        assert loaded["user_template"] == "为 {topic} 生成标题"
    finally:
        prompt_file.unlink(missing_ok=True)
