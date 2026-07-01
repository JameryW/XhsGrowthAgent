"""Tests for fallback text cover generation."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from backend.services.text_cover import generate_text_cover_image


def test_generate_text_cover_image_creates_png(tmp_path: Path):
    path = generate_text_cover_image(
        title="标题",
        key_points=["要点1", "要点2", "要点3"],
        color_palette=["#FFE4E1", "#FFDAB9", "#FFFACD"],
        output_dir=tmp_path,
    )

    output = Path(path)
    assert output.exists()
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(output) as image:
        assert image.size == (1080, 1440)
