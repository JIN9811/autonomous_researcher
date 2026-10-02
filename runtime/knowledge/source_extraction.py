"""Complete, bounded extraction of local source files into Markdown and stable blocks."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import subprocess
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml


SUPPORTED_FORMATS = frozenset(
    {"md", "txt", "csv", "json", "yaml", "yml", "pdf", "html", "htm", "docx"}
)
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_BLOCKS = 4096
BLOCK_BYTES = 2_000


def source_format(path: Path) -> str:
    value = path.suffix.lower().removeprefix(".")
    if value not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported source format: {path.suffix or '<none>'}")
    return value


def extract_source(path: Path, *, source_id: str, format_name: str | None = None) -> dict:
    """Return complete Markdown and page-aware blocks, or fail without truncating."""
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("source must be a regular non-symlink file")
    size = path.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise ValueError(f"source exceeds maximum size {MAX_SOURCE_BYTES}")
    resolved_format = format_name or source_format(path)
    if resolved_format not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported source format: {resolved_format}")

    if resolved_format == "pdf":
        pages = _pdf_pages(path)
        markdown = "\n\n".join(
            f"<!-- page: {number} -->\n\n{text}"
            for number, text in enumerate(pages, start=1)
        )
    elif resolved_format == "docx":
        markdown = _docx_markdown(path)
        pages = [markdown]
    else:
        raw = _read_utf8(path)
        if resolved_format == "csv":
            markdown = _csv_markdown(raw)
        elif resolved_format == "json":
            try:
                json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON source: {exc}") from exc
            separator = "" if raw.endswith("\n") else "\n"
            markdown = f"```json\n{raw}{separator}```"
        elif resolved_format in {"yaml", "yml"}:
            try:
                yaml.safe_load(raw)
            except yaml.YAMLError as exc:
                raise ValueError(f"invalid YAML source: {exc}") from exc
            markdown = f"```yaml\n{raw}\n```"
        elif resolved_format in {"html", "htm"}:
            markdown = _html_markdown(raw)
        else:
            markdown = raw
        pages = [markdown]

    if not markdown.strip():
        raise ValueError("source yielded no extractable text; OCR is not fabricated")
    model_pages = [_model_page(page) for page in pages] if resolved_format == "pdf" else pages
    blocks = _blocks(model_pages, source_id=source_id)
    return {"markdown": markdown, "blocks": blocks, "pages": pages}


def _model_page(page: str) -> str:
    """Compact PDF layout padding for bounded model views, retaining all text."""
    return "\n".join(
        re.sub(r"[ \t]{2,}", " | ", line).rstrip() for line in page.splitlines()
    )


def _read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise ValueError("text source is not valid UTF-8; no replacement text was fabricated") from exc


def _pdf_pages(path: Path) -> list[str]:
    try:
        process = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"PDF text extraction failed: {type(exc).__name__}") from exc
    pages = process.stdout.replace("\r\n", "\n").replace("\r", "\n").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    normalized = [page.strip("\n") for page in pages]
    if not normalized or not any(page.strip() for page in normalized):
        raise ValueError("PDF yielded no text; OCR is disabled and no text was fabricated")
    return normalized


def _csv_markdown(raw: str) -> str:
    try:
        rows = list(csv.reader(io.StringIO(raw, newline=""), strict=True))
    except csv.Error as exc:
        raise ValueError(f"invalid CSV source: {exc}") from exc
    if not rows or not rows[0]:
        raise ValueError("CSV source contains no rows")
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]

    return _markdown_table(rows)


class _HTMLMarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.skip_depth = 0
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []
        elif self.table is None:
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                self.output.append("\n\n" + "#" * int(tag[1]) + " ")
            elif tag == "li":
                self.output.append("\n- ")
            elif tag in {"p", "div", "section", "article", "br"}:
                self.output.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in {"td", "th"} and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.table:
                self.output.append("\n\n" + _markdown_table(self.table) + "\n\n")
            self.table = None
        elif tag in {"p", "div", "section", "article", "li"} and self.table is None:
            self.output.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth or not data:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.table is None:
            self.output.append(data)

    def markdown(self) -> str:
        lines = [line.rstrip() for line in "".join(self.output).splitlines()]
        result: list[str] = []
        for line in lines:
            if line.strip() or (result and result[-1]):
                result.append(line.strip() if line.strip() else "")
        return "\n".join(result).strip()


def _html_markdown(raw: str) -> str:
    parser = _HTMLMarkdownParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:
        raise ValueError(f"invalid HTML source: {exc}") from exc
    return parser.markdown()


def _docx_markdown(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            names = ["word/document.xml"]
            names.extend(
                sorted(
                    name
                    for name in archive.namelist()
                    if re.fullmatch(
                        r"word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml",
                        name,
                    )
                )
            )
            parts: list[tuple[str, bytes]] = []
            total = 0
            for name in names:
                info = archive.getinfo(name)
                total += info.file_size
                if total > MAX_SOURCE_BYTES:
                    raise ValueError("DOCX text-bearing XML exceeds extraction size limit")
                parts.append((name, archive.read(info)))
    except (KeyError, zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"invalid DOCX source: {type(exc).__name__}") from exc
    rendered: list[str] = []
    for name, xml in parts:
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            raise ValueError(f"invalid DOCX XML in {name}: {exc}") from exc
        if name == "word/document.xml":
            container = next(
                (node for node in root.iter() if _local_name(node.tag) == "body"),
                None,
            )
            if container is None:
                raise ValueError("invalid DOCX source: document body missing")
            content = _word_container_markdown(container)
        else:
            content = _word_container_markdown(root)
        if content:
            if name == "word/document.xml":
                rendered.append(content)
            else:
                kind = re.match(r"word/([a-z]+)", name).group(1).rstrip("s").title()
                if name.endswith("notes.xml"):
                    kind += "s"
                rendered.append(f"## {kind}: {Path(name).name}\n\n{content}")
    return "\n\n".join(rendered).strip()


def _word_container_markdown(container: ElementTree.Element) -> str:
    sections: list[str] = []
    for child in container:
        name = _local_name(child.tag)
        if name == "p":
            text = _word_text(child)
            if text:
                sections.append(text)
        elif name == "tbl":
            rows: list[list[str]] = []
            for row in child:
                if _local_name(row.tag) != "tr":
                    continue
                cells = [
                    "<br>".join(
                        text
                        for paragraph in cell
                        if _local_name(paragraph.tag) == "p"
                        and (text := _word_text(paragraph))
                    )
                    for cell in row
                    if _local_name(cell.tag) == "tc"
                ]
                if cells:
                    rows.append(cells)
            if rows:
                sections.append(_markdown_table(rows))
        elif name in {"footnote", "endnote"}:
            content = _word_container_markdown(child)
            if content:
                sections.append(content)
    return "\n\n".join(sections).strip()


def _word_text(node: ElementTree.Element) -> str:
    pieces: list[str] = []
    for child in node.iter():
        name = _local_name(child.tag)
        if name == "t" and child.text:
            pieces.append(child.text)
        elif name == "tab":
            pieces.append("\t")
        elif name in {"br", "cr"}:
            pieces.append("\n")
    return "".join(pieces).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _markdown_table(rows: list[list[str]]) -> str:
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]

    def cell(value: str) -> str:
        return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")

    lines = ["| " + " | ".join(cell(value) for value in padded[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    lines.extend(
        "| " + " | ".join(cell(value) for value in row) + " |" for row in padded[1:]
    )
    return "\n".join(lines)


def _blocks(pages: list[str], *, source_id: str) -> list[dict]:
    result: list[dict] = []
    for page_number, page in enumerate(pages, start=1):
        for text in _split_complete(page, BLOCK_BYTES):
            ordinal = len(result)
            identity = f"{source_id}\0{ordinal}\0{page_number}\0{text}"
            block_id = f"block-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
            result.append({"block_id": block_id, "text": text, "page": page_number})
            if len(result) > MAX_BLOCKS:
                raise ValueError(f"source exceeds maximum block count {MAX_BLOCKS}")
    if not result:
        raise ValueError("source yielded no blocks")
    return result


def _split_complete(text: str, limit: int) -> list[str]:
    if len(text.encode("utf-8")) <= limit:
        return [text]
    chunks: list[str] = []
    cursor = 0
    while cursor < len(text):
        low = cursor + 1
        high = len(text)
        while low <= high:
            middle = (low + high) // 2
            if len(text[cursor:middle].encode("utf-8")) <= limit:
                low = middle + 1
            else:
                high = middle - 1
        end = max(cursor + 1, high)
        if end < len(text):
            boundary = text.rfind("\n\n", cursor, end)
            if boundary <= cursor:
                boundary = text.rfind("\n", cursor, end)
            if boundary <= cursor:
                boundary = end
            else:
                boundary += 2 if text[boundary : boundary + 2] == "\n\n" else 1
            end = boundary
        chunks.append(text[cursor:end])
        cursor = end
    return chunks
