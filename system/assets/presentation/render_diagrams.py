#!/usr/bin/env python3
"""
Render generated SVG diagrams to PNG and build a contact sheet for visual QA.

Usage:
- image/.render_venv/bin/python image/render_diagrams.py
"""

from __future__ import annotations

from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
SVG_DIR = ROOT / "svg"
OUT = ROOT / "rendered"
WIDTH = 1920
HEIGHT = 1080
THUMB_W = 480
THUMB_H = 270
LABEL_H = 42
COLS = 2


def load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_svgs() -> list[Path]:
    OUT.mkdir(exist_ok=True)
    rendered: list[Path] = []
    for svg in sorted(SVG_DIR.glob("*.svg")):
        png = OUT / f"{svg.stem}.png"
        cairosvg.svg2png(
            url=str(svg),
            write_to=str(png),
            output_width=WIDTH,
            output_height=HEIGHT,
        )
        rendered.append(png)
    return rendered


def build_contact_sheet(rendered: list[Path]) -> Path:
    rows = (len(rendered) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * THUMB_W, rows * (THUMB_H + LABEL_H)), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = load_font(22)

    for idx, png in enumerate(rendered):
        img = Image.open(png).convert("RGB").resize((THUMB_W, THUMB_H), Image.Resampling.LANCZOS)
        x = (idx % COLS) * THUMB_W
        y = (idx // COLS) * (THUMB_H + LABEL_H)
        sheet.paste(img, (x, y + LABEL_H))
        draw.rectangle([x, y, x + THUMB_W - 1, y + LABEL_H + THUMB_H - 1], outline=(156, 163, 175), width=2)
        draw.text((x + 12, y + 10), png.stem, fill=(17, 24, 39), font=font)

    contact_sheet = OUT / "contact_sheet.png"
    sheet.save(contact_sheet)
    return contact_sheet


def main() -> None:
    rendered = render_svgs()
    contact_sheet = build_contact_sheet(rendered)
    print(f"rendered={len(rendered)}")
    print(f"contact_sheet={contact_sheet}")


if __name__ == "__main__":
    main()
