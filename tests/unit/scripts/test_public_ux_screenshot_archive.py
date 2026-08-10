"""Unit coverage for the public UX screenshot archive helpers."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.acceptance.public_ux_screenshot_archive import add_storage_init_script, capture


def test_add_storage_init_script_sets_language_and_theme() -> None:
    context = Mock()

    add_storage_init_script(context, "dark")

    script = context.add_init_script.call_args.args[0]
    assert "xhs-theme-mode" in script
    assert "dark" in script
    assert "language" in script


def test_capture_records_dimensions_and_overflow(tmp_path: Path) -> None:
    page = Mock()
    page.evaluate.return_value = {
        "innerWidth": 390,
        "documentWidth": 390,
        "bodyWidth": 390,
    }
    page.screenshot.side_effect = lambda path, full_page: Path(path).write_bytes(b"png")
    output = tmp_path / "capture.png"

    record = capture(
        page,
        output,
        surface="fixture-replay",
        width=390,
        height=844,
        theme="light",
    )

    assert record["surface"] == "fixture-replay"
    assert record["width"] == 390
    assert record["overflow"]["documentWidth"] == 390
    page.screenshot.assert_called_once_with(path=str(output), full_page=True)


def test_capture_rejects_horizontal_overflow(tmp_path: Path) -> None:
    page = Mock()
    page.evaluate.return_value = {
        "innerWidth": 390,
        "documentWidth": 412,
        "bodyWidth": 390,
    }

    with pytest.raises(AssertionError, match="horizontal overflow"):
        capture(
            page,
            tmp_path / "overflow.png",
            surface="fixture-showcase",
            width=390,
            height=844,
            theme="dark",
        )
