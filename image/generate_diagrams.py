#!/usr/bin/env python3
"""
Generate academic presentation figure-style SVG architecture diagrams and prompt files.

Input:
- image/diagram_manifest.json

Output:
- image/prompt/*.prompt.md
- image/svg/*.svg

Design constraints:
- 16:9 SVG viewBox, default 1920x1080.
- Text uses SVG text elements, minimum 24px (~18pt), above the requested 14pt floor.
- White-background, academic presentation figure-style diagrams are deterministic
  and vector-based so they can be regenerated after system upgrades.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from textwrap import wrap
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "diagram_manifest.json"
PROMPT_DIR = ROOT / "prompt"
SVG_DIR = ROOT / "svg"

COLORS = {
    "bg": "#ffffff",
    "ink": "#111827",
    "muted": "#4b5563",
    "line": "#374151",
    "blue": "#2563eb",
    "blue_dark": "#1e3a8a",
    "green": "#047857",
    "green_dark": "#065f46",
    "orange": "#b45309",
    "orange_dark": "#92400e",
    "red": "#b91c1c",
    "purple": "#6d28d9",
    "card": "#ffffff",
    "soft_blue": "#f8fbff",
    "soft_green": "#f7fcfa",
    "soft_orange": "#fffaf2",
    "soft_red": "#fff8f8",
    "soft_purple": "#fbf9ff",
    "shadow": "#ffffff",
}

MIN_FONT = 24
FONT_FAMILY = "Noto Sans CJK KR, Noto Sans, DejaVu Sans, Arial, sans-serif"


def esc(value: object) -> str:
    return escape(str(value), {"\"": "&quot;"})


def slug_label(slug: str) -> str:
    return slug.replace("_", " ").title()


def text_width_chars(width_px: int, font_px: int) -> int:
    # Conservative estimate for mixed Korean/English SVG text wrapping.
    return max(10, int(width_px / (font_px * 0.62)))


def tspan_lines(text: str, width_px: int, font_px: int) -> list[str]:
    chunks: list[str] = []
    for raw in str(text).split("\n"):
        raw = raw.strip()
        if not raw:
            chunks.append("")
            continue
        chunks.extend(wrap(raw, width=text_width_chars(width_px, font_px), break_long_words=False) or [raw])
    return chunks


def svg_open(title: str, subtitle: str, width: int, height: int, desc: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{esc(title)}</title>',
        f'<desc id="desc">{esc(desc)}</desc>',
        '<defs>',
        '<filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">'
        '<feDropShadow dx="0" dy="0" stdDeviation="0" flood-color="#ffffff" flood-opacity="0"/>'
        '</filter>',
        '<marker id="arrow" markerWidth="16" markerHeight="16" refX="12" refY="8" orient="auto" markerUnits="strokeWidth">'
        f'<path d="M2,2 L14,8 L2,14 Z" fill="{COLORS["line"]}"/>'
        '</marker>',
        '<style>',
        f'text {{ font-family: {FONT_FAMILY}; fill: {COLORS["ink"]}; }}',
        '.title { font-size: 42px; font-weight: 760; letter-spacing: -0.3px; }',
        '.subtitle { font-size: 25px; font-weight: 560; fill: #4b5563; }',
        '.section { font-size: 29px; font-weight: 720; }',
        '.label { font-size: 26px; font-weight: 720; }',
        '.body { font-size: 24px; font-weight: 500; }',
        '.small { font-size: 24px; font-weight: 500; }',
        '.tiny { font-size: 24px; font-weight: 500; }',
        '.mono { font-family: JetBrains Mono, DejaVu Sans Mono, monospace; font-size: 24px; }',
        '</style>',
        '</defs>',
        f'<rect width="{width}" height="{height}" fill="{COLORS["bg"]}"/>',
        f'<text x="80" y="72" class="title">{esc(title)}</text>',
        f'<text x="82" y="116" class="subtitle">{esc(subtitle)}</text>',
        '<line x1="80" y1="136" x2="1840" y2="136" stroke="#e5e7eb" stroke-width="2"/>',
    ]


def rect(x: int, y: int, w: int, h: int, fill: str, stroke: str = "#374151", radius: int = 18, shadow: bool = False) -> str:
    filt = ' filter="url(#softShadow)"' if shadow else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"{filt}/>'


def add_text(lines: list[str], x: int, y: int, text: str, *, width: int, font_px: int = MIN_FONT, cls: str = "body", fill: str | None = None, line_gap: int | None = None) -> int:
    line_gap = line_gap or int(font_px * 1.28)
    style = f' fill="{fill}"' if fill else ""
    wrapped = tspan_lines(text, width, font_px)
    if not wrapped:
        return y
    lines.append(f'<text x="{x}" y="{y}" class="{cls}" font-size="{font_px}"{style}>')
    for idx, item in enumerate(wrapped):
        dy = 0 if idx == 0 else line_gap
        lines.append(f'<tspan x="{x}" dy="{dy}">{esc(item)}</tspan>')
    lines.append('</text>')
    return y + line_gap * len(wrapped)


def add_bullets(lines: list[str], items: list[str], x: int, y: int, *, width: int, font_px: int = MIN_FONT, bullet_color: str = "#2f6fed", max_items: int | None = None) -> int:
    shown = items[:max_items] if max_items else items
    cy = y
    for item in shown:
        wrapped = tspan_lines(item, width - 36, font_px)
        lines.append(f'<circle cx="{x + 8}" cy="{cy - 7}" r="6" fill="{bullet_color}"/>')
        lines.append(f'<text x="{x + 28}" y="{cy}" class="body" font-size="{font_px}">')
        for idx, part in enumerate(wrapped):
            dy = 0 if idx == 0 else int(font_px * 1.26)
            lines.append(f'<tspan x="{x + 28}" dy="{dy}">{esc(part)}</tspan>')
        lines.append('</text>')
        cy += max(1, len(wrapped)) * int(font_px * 1.26) + 10
    return cy


def compact_list(items: list[str]) -> str:
    return " · ".join(str(item).strip() for item in items if str(item).strip())


def arrow(x1: int, y1: int, x2: int, y2: int, *, color: str = "#1f3a5f", width: int = 4, dashed: bool = False) -> str:
    dash = ' stroke-dasharray="12 10"' if dashed else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" marker-end="url(#arrow)"{dash}/>'


def node(lines: list[str], x: int, y: int, w: int, h: int, title: str, subtitle: str, fill: str, accent: str) -> None:
    lines.append(rect(x, y, w, h, fill, accent, radius=18, shadow=False))
    lines.append(f'<rect x="{x}" y="{y}" width="{w}" height="8" rx="4" fill="{accent}"/>')
    title_end = add_text(lines, x + 22, y + 45, title, width=w - 44, font_px=28, cls="label", line_gap=34)
    subtitle_y = max(y + 88, title_end + 6)
    add_text(lines, x + 22, subtitle_y, subtitle, width=w - 44, font_px=24, cls="small", fill=COLORS["muted"], line_gap=30)


def generate_system(diagram: dict, width: int, height: int) -> str:
    lines = svg_open(diagram["title"], diagram["subtitle"], width, height, f'Generated from prompt/{diagram["slug"]}.prompt.md')

    lines.append(rect(80, 150, 1760, 140, COLORS["card"], COLORS["line"], radius=18))
    add_text(lines, 120, 197, "Operator / GUI Surface", width=520, font_px=32, cls="section", fill=COLORS["blue_dark"])
    add_text(lines, 120, 238, compact_list(diagram["operator"]), width=1620, font_px=24, cls="body", fill=COLORS["muted"], line_gap=30)

    node_h = 170
    y1 = 330
    x_positions = [80, 430, 780, 1130, 1480]
    row1 = ["Orchestrator", "Design", "Specimen Making", "Vision", "Manipulation"]
    subtitles1 = ["route + state", "experiment_spec", "STL + printer.prepare", "observation", "robot / SARM"]
    for x, title, sub in zip(x_positions, row1, subtitles1):
        fill = COLORS["soft_blue"] if title in {"Orchestrator", "Design"} else COLORS["soft_green"]
        accent = COLORS["blue"] if title in {"Orchestrator", "Design"} else COLORS["green"]
        node(lines, x, y1, 300, node_h, title, sub, fill, accent)
    for x in x_positions[:-1]:
        lines.append(arrow(x + 300, y1 + 85, x + 350, y1 + 85))

    y2 = 540
    row2 = [(1480, "Lab Equipment", "Windows / UTM"), (1130, "Analysis", "metrics + score"), (780, "Knowledge", "RAG + memory"), (430, "Guardian", "policy gate")]
    for x, title, sub in row2:
        fill = COLORS["soft_orange"] if title == "Lab Equipment" else COLORS["soft_purple"] if title in {"Analysis", "Knowledge"} else COLORS["soft_red"]
        accent = COLORS["orange"] if title == "Lab Equipment" else COLORS["purple"] if title in {"Analysis", "Knowledge"} else COLORS["red"]
        node(lines, x, y2, 300, node_h, title, sub, fill, accent)
    lines.append(rect(80, y2, 300, node_h, COLORS["card"], COLORS["line"], radius=18))
    add_text(lines, 102, y2 + 48, "Loop Signal", width=256, font_px=28, cls="label", fill=COLORS["line"])
    add_text(lines, 102, y2 + 88, "revise · continue · stop · fail-safe", width=250, font_px=24, cls="small", fill=COLORS["muted"], line_gap=30)
    lines.append(arrow(1630, y1 + node_h, 1630, y2))
    for x in [1480, 1130, 780]:
        lines.append(arrow(x, y2 + 85, x - 50, y2 + 85))
    lines.append(arrow(430, y2 + 85, 380, y2 + 85, dashed=True))
    lines.append(arrow(230, y2, 230, y1 + node_h, dashed=True))

    # Bottom platform cards.
    cards = [
        (80, 750, 520, 300, "Model Runtime", diagram["runtime"], COLORS["soft_blue"], COLORS["blue"]),
        (700, 750, 520, 300, "MCP Tools / Device Bridges", diagram["tools"], COLORS["soft_green"], COLORS["green"]),
        (1320, 750, 520, 300, "Memory / Logs / Artifacts", diagram["memory"], COLORS["soft_orange"], COLORS["orange"]),
    ]
    for x, y, w, h, title, items, fill, accent in cards:
        lines.append(rect(x, y, w, h, fill, accent, radius=30))
        title_end = add_text(lines, x + 28, y + 48, title, width=w - 56, font_px=30, cls="section", fill=accent, line_gap=38)
        body_y = max(y + 98, title_end + 4)
        add_text(lines, x + 28, body_y, compact_list(items), width=w - 56, font_px=24, cls="body", fill=COLORS["ink"], line_gap=30)

    lines.append('</svg>')
    return "\n".join(lines) + "\n"


def generate_agent(diagram: dict, width: int, height: int) -> str:
    subtitle = diagram.get("stage", "Agent diagram")
    lines = svg_open(diagram["title"], subtitle, width, height, f'Generated from prompt/{diagram["slug"]}.prompt.md')

    # Central agent card.
    lines.append(rect(560, 185, 800, 610, COLORS["card"], COLORS["blue_dark"], radius=22))
    lines.append(f'<circle cx="960" cy="265" r="68" fill="{COLORS["soft_blue"]}" stroke="{COLORS["blue_dark"]}" stroke-width="2"/>')
    initials = "".join(part[0] for part in re.findall(r"[A-Za-z]+", diagram["title"])[:2]).upper() or "AI"
    add_text(lines, 920, 282, initials, width=120, font_px=40, cls="title", fill=COLORS["blue_dark"])
    add_text(lines, 610, 370, "Role", width=740, font_px=32, cls="section", fill=COLORS["blue_dark"])
    add_text(lines, 610, 415, diagram["role"], width=720, font_px=26, cls="body")
    add_text(lines, 610, 510, "Core Actions", width=720, font_px=32, cls="section", fill=COLORS["blue_dark"])
    add_bullets(lines, diagram["actions"], 610, 552, width=720, font_px=24, bullet_color=COLORS["blue"], max_items=6)

    # Input / Output cards.
    lines.append(rect(80, 190, 420, 650, COLORS["soft_green"], COLORS["green_dark"], radius=20))
    add_text(lines, 115, 242, "Inputs", width=360, font_px=34, cls="section", fill=COLORS["green_dark"])
    add_bullets(lines, diagram["inputs"], 120, 292, width=340, font_px=24, bullet_color=COLORS["green"], max_items=7)

    lines.append(rect(1420, 190, 420, 650, COLORS["soft_orange"], COLORS["orange_dark"], radius=20))
    add_text(lines, 1455, 242, "Outputs", width=360, font_px=34, cls="section", fill=COLORS["orange_dark"])
    add_bullets(lines, diagram["outputs"], 1460, 292, width=340, font_px=24, bullet_color=COLORS["orange"], max_items=7)

    lines.append(arrow(500, 515, 560, 515, color=COLORS["green_dark"], width=5))
    lines.append(arrow(1360, 515, 1420, 515, color=COLORS["orange_dark"], width=5))

    # Bottom tools and safety row.
    bottom_y = 850
    bottom_h = 195
    lines.append(rect(80, bottom_y, 860, bottom_h, COLORS["soft_purple"], COLORS["purple"], radius=18))
    tools_title_end = add_text(lines, 115, bottom_y + 45, "Tools / Interfaces", width=800, font_px=30, cls="section", fill=COLORS["purple"], line_gap=38)
    add_text(lines, 120, max(bottom_y + 87, tools_title_end + 4), compact_list(diagram["tools"]), width=780, font_px=24, cls="body", fill=COLORS["ink"], line_gap=30)

    lines.append(rect(980, bottom_y, 860, bottom_h, COLORS["soft_red"], COLORS["red"], radius=18))
    safety_title_end = add_text(lines, 1015, bottom_y + 45, "Safety / Contract", width=800, font_px=30, cls="section", fill=COLORS["red"], line_gap=38)
    add_text(lines, 1020, max(bottom_y + 87, safety_title_end + 4), compact_list(diagram["safety"]), width=780, font_px=24, cls="body", fill=COLORS["ink"], line_gap=30)

    lines.append('</svg>')
    return "\n".join(lines) + "\n"


def prompt_text(diagram: dict, width: int, height: int) -> str:
    sections = [
        f"# {diagram['title']} 이미지 생성 프롬프트",
        "",
        "목표: PPT에 바로 넣을 수 있는 16:9 벡터 기반 시스템 다이어그램을 생성한다.",
        f"권장 캔버스: {width}x{height}px SVG, 16:9.",
        "글자 크기: 내부 텍스트 최소 14pt 이상. 이 프로젝트 SVG 생성기는 최소 24px로 생성한다.",
        "저장 구조: SVG는 `image/svg/`, PNG 렌더는 `image/rendered/`, 프롬프트는 `image/prompt/`에 둔다.",
        "목표 독자: 박사급 연구자/지도교수 대상 발표자료에 들어갈 수 있는 academic figure 톤으로 만든다.",
        "발표용 fig 스타일: 순백색 배경, 얇은 선, 낮은 채도, 절제된 색 구분, 그림자/장식 배제, 충분한 여백, 큰 글씨를 사용한다.",
        "레이아웃 제약: 모든 텍스트는 카드/패널 내부에 들어가야 하며, 캔버스나 둥근 카드 밖으로 넘치면 안 된다.",
        "줄바꿈 규칙: 긴 목록은 세로 bullet을 과하게 쌓지 말고 한 줄 요약 또는 2-3줄 이하의 compact list로 배치한다.",
        "여백 규칙: 텍스트와 카드 경계 사이에는 최소 24px 이상의 안쪽 여백을 유지한다.",
        "렌더 검증: SVG 생성 후 `image/.render_venv/bin/python image/render_diagrams.py`로 PNG와 contact sheet를 만든다.",
        "육안검사: `image/rendered/contact_sheet.png`와 원본 PNG를 열어 텍스트 겹침, 카드 밖 이탈, 화살표와 텍스트 충돌을 확인한다.",
        "수정 루프: 육안검사에서 문제가 보이면 prompt와 diagram_manifest.json 또는 generate_diagrams.py를 수정하고 SVG/PNG/contact sheet를 다시 생성한다.",
        "스타일: 선명한 벡터 라인, 둥근 카드, 명확한 화살표, 과도한 장식 없는 박사급 연구 발표 figure 톤.",
        "업데이트 원칙: 시스템이 바뀌면 이 프롬프트와 image/diagram_manifest.json의 동일 항목을 함께 수정한 뒤 generate_diagrams.py를 다시 실행한다.",
        "",
        "핵심 표현:",
        f"- {diagram.get('prompt_focus', '')}",
    ]
    if diagram["type"] == "system":
        for key, label in [("operator", "Operator/GUI"), ("workflow", "Agent Workflow"), ("runtime", "Model Runtime"), ("tools", "Tools/Bridges"), ("memory", "Memory/Logs")]:
            sections.extend(["", f"## {label}"])
            sections.extend([f"- {item}" for item in diagram.get(key, [])])
    else:
        for key, label in [("role", "Role"), ("inputs", "Inputs"), ("actions", "Core Actions"), ("outputs", "Outputs"), ("tools", "Tools/Interfaces"), ("safety", "Safety/Contract")]:
            sections.extend(["", f"## {label}"])
            value = diagram.get(key, [])
            if isinstance(value, list):
                sections.extend([f"- {item}" for item in value])
            else:
                sections.append(f"- {value}")
    sections.append("")
    return "\n".join(sections)


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    width = int(manifest.get("canvas", {}).get("width", 1920))
    height = int(manifest.get("canvas", {}).get("height", 1080))
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    SVG_DIR.mkdir(parents=True, exist_ok=True)
    for diagram in manifest["diagrams"]:
        slug = diagram["slug"]
        (PROMPT_DIR / f"{slug}.prompt.md").write_text(prompt_text(diagram, width, height), encoding="utf-8")
        if diagram["type"] == "system":
            svg = generate_system(diagram, width, height)
        else:
            svg = generate_agent(diagram, width, height)
        (SVG_DIR / f"{slug}.svg").write_text(svg, encoding="utf-8")
    readme = """# Image Assets\n\nThis folder contains PPT-ready academic presentation figure-style vector diagrams generated from `diagram_manifest.json`.\n\n- `prompt/*.prompt.md`: image-generation prompts, one per diagram.\n- `svg/*.svg`: generated 16:9 vector diagrams.\n- `generate_diagrams.py`: deterministic SVG generator.\n- `render_diagrams.py`: renders SVGs to PNG and creates `rendered/contact_sheet.png` for visual QA.\n- `rendered/*.png`: optional rendered QA outputs for visual inspection.\n\nStyle baseline:\n\n- White background.\n- Thin strokes, muted colors, and restrained accents suitable for PhD-level research presentations.\n- No decorative grid, wave background, or drop shadows.\n- Text is generated at 24px or larger for readability in PPT and printed handouts.\n\nUpdate workflow:\n\n1. Edit `diagram_manifest.json` and the matching prompt intent if the system changes.\n2. Run `python3 image/generate_diagrams.py` from the repository root.\n3. Run `image/.render_venv/bin/python image/render_diagrams.py` from the repository root.\n4. Inspect `image/rendered/contact_sheet.png` and original-size PNGs for text overlap, text outside cards, or arrow/text collision.\n5. Insert the SVG files from `image/svg/` directly into PowerPoint or a paper figure pipeline.\n"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    main()
