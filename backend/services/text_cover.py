"""Generate fallback text cover images for XHS publishing."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from PIL import Image, ImageDraw, ImageFont

    # ponytail: PIL stubs place FreeTypeFont and ImageFont as siblings (no
    # subtype relation at runtime either); a font factory returns the union.
    Font: TypeAlias = ImageFont.FreeTypeFont | ImageFont.ImageFont

RgbColor: TypeAlias = tuple[int, int, int]

_IMAGE_SIZE = (1080, 1440)
_PANEL_BOX = (72, 108, 1008, 1332)
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/opentype/unifont/unifont.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)
_FALLBACK_COLORS = ("#FDE2E4", "#BEE1E6", "#CDEAC0")
_FALLBACK_POINTS = ("抓住核心痛点", "给出清晰方法", "留下行动理由")
_HEX_RE = re.compile(r"^[0-9a-fA-F]{6}$")


def generate_text_cover_image(
    *,
    title: str,
    key_points: Sequence[str],
    color_palette: Sequence[str],
    output_dir: str | Path,
) -> str:
    """Create a 3:4 PNG text cover and return its absolute path."""

    from PIL import Image, ImageDraw

    colors = _select_colors(color_palette)
    image = _make_background(colors)
    image = image.convert("RGBA")

    overlay = Image.new("RGBA", _IMAGE_SIZE, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        _PANEL_BOX,
        radius=56,
        fill=(255, 255, 255, 226),
        outline=(255, 255, 255, 245),
        width=3,
    )
    image = Image.alpha_composite(image, overlay)

    draw = ImageDraw.Draw(image)
    _draw_cover_text(
        draw,
        title=title.strip() or "小红书笔记",
        key_points=_select_points(key_points),
        accent=colors[1] if len(colors) > 1 else colors[0],
    )

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"text_cover_{uuid.uuid4().hex[:12]}.png"
    image.convert("RGB").save(path, format="PNG", optimize=True)
    return str(path)


def _select_colors(color_palette: Sequence[str]) -> list[RgbColor]:
    colors: list[RgbColor] = []
    for raw in color_palette:
        parsed = _parse_hex(raw)
        if parsed is not None:
            colors.append(parsed)

    if colors:
        return colors[:3]

    return [color for color in (_parse_hex(value) for value in _FALLBACK_COLORS) if color]


def _parse_hex(value: str) -> RgbColor | None:
    normalized = value.strip().lstrip("#")
    if len(normalized) == 3:
        normalized = "".join(char * 2 for char in normalized)
    if not _HEX_RE.match(normalized):
        return None
    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
    )


def _select_points(key_points: Sequence[str]) -> list[str]:
    points = [point.strip() for point in key_points if point.strip()]
    for fallback in _FALLBACK_POINTS:
        if len(points) >= 3:
            break
        points.append(fallback)
    return points[:3]


def _make_background(colors: list[RgbColor]) -> Image.Image:
    from PIL import Image, ImageDraw

    first = colors[0]
    second = colors[1] if len(colors) > 1 else colors[0]
    width, height = _IMAGE_SIZE
    image = Image.new("RGB", _IMAGE_SIZE, first)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(first[index] * (1 - ratio) + second[index] * ratio) for index in range(3))
        draw.line((0, y, width, y), fill=color)

    if len(colors) > 2:
        accent = colors[2]
        draw.rectangle((0, 0, width, 26), fill=accent)
        draw.rectangle((0, height - 34, width, height), fill=accent)

    return image


def _font(size: int) -> Font:
    from PIL import ImageFont

    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _draw_cover_text(
    draw: ImageDraw.ImageDraw,
    *,
    title: str,
    key_points: list[str],
    accent: RgbColor,
) -> None:
    title_font = _font(86)
    point_font = _font(42)
    label_font = _font(36)
    meta_font = _font(32)
    text_color = (32, 35, 38)
    muted_color = (92, 96, 102)

    panel_left, panel_top, panel_right, _ = _PANEL_BOX
    max_width = panel_right - panel_left - 112
    x = panel_left + 56
    y = panel_top + 72

    draw.text((x, y), "XHS NOTE", font=meta_font, fill=muted_color)
    y += 72

    for line in _wrap_text(draw, title, title_font, max_width=max_width, max_lines=5):
        draw.text((x, y), line, font=title_font, fill=text_color)
        y += 104

    y += 44
    draw.line((x, y, x + 160, y), fill=accent, width=8)
    y += 72

    for index, point in enumerate(key_points, start=1):
        box_top = y
        box_bottom = y + 150
        draw.rounded_rectangle(
            (x, box_top, panel_right - 56, box_bottom),
            radius=28,
            fill=(250, 250, 250, 255),
            outline=(232, 234, 237, 255),
            width=2,
        )
        badge_box = (x + 28, box_top + 36, x + 104, box_top + 112)
        draw.rounded_rectangle(badge_box, radius=22, fill=accent)
        draw.text(
            (x + 43, box_top + 52),
            f"{index:02d}",
            font=label_font,
            fill=(255, 255, 255),
        )
        point_lines = _wrap_text(draw, point, point_font, max_width=max_width - 148, max_lines=2)
        text_y = box_top + 36
        for line in point_lines:
            draw.text((x + 132, text_y), line, font=point_font, fill=text_color)
            text_y += 52
        y += 178


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: Font,
    *,
    max_width: int,
    max_lines: int,
) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []

    lines: list[str] = []
    current = ""
    truncated = False
    for char in normalized:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current.rstrip())
            if len(lines) >= max_lines:
                truncated = True
                break
            current = char.lstrip()
        else:
            current = candidate

    if not truncated and current.strip() and len(lines) < max_lines:
        lines.append(current.strip())

    if truncated and lines:
        ellipsis = "..."
        last = lines[-1].rstrip()
        while last and draw.textlength(last + ellipsis, font=font) > max_width:
            last = last[:-1].rstrip()
        lines[-1] = f"{last}{ellipsis}" if last else ellipsis

    return lines
