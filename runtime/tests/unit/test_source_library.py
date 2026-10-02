from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from knowledge import source_library as source_library_module
from knowledge.source_library import SourceLibrary


def _admit(library: SourceLibrary) -> str:
    first = library.scan()
    assert first["pending_ids"] == []
    second = library.scan()
    assert len(second["pending_ids"]) == 1
    return second["pending_ids"][0]


def _note(extracted: dict, **overrides: object) -> dict[str, object]:
    note: dict[str, object] = {
        "title": "Qualified threshold",
        "body": "The source reports a threshold of 17.5 under the stated test condition.",
        "category": "process-guidance",
        "ontology_type": "KnowledgeClaim",
        "tags": ["threshold", "qualified"],
        "applicability": {"condition": "fixture-a"},
        "source_block_ids": [extracted["blocks"][-1]["block_id"]],
    }
    note.update(overrides)
    return note


def _publish(library: SourceLibrary, source_id: str, extracted: dict, **note_overrides: object) -> dict:
    return library.publish(
        source_id,
        [_note(extracted, **note_overrides)],
        model={"provider": "test", "model": "fixture", "mock": True, "real": False},
        trace=[{"tool": "inspect_source", "source_id": source_id}],
    )


def _minimal_text_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(data)


def _multipage_text_pdf(texts: list[str]) -> bytes:
    page_numbers = list(range(3, 3 + len(texts)))
    font_number = 3 + len(texts)
    content_numbers = list(range(font_number + 1, font_number + 1 + len(texts)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Kids [{' '.join(f'{number} 0 R' for number in page_numbers)}] "
            f"/Count {len(texts)} >>"
        ).encode("ascii"),
    ]
    for content_number in content_numbers:
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_number} 0 R >> >> "
                f"/Contents {content_number} 0 R >>"
            ).encode("ascii")
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for text in texts:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(data)


def test_scan_requires_two_equal_observations_and_uses_content_identity(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    content = b"stable source content\n"
    (inbox / "sample.txt").write_bytes(content)
    library = SourceLibrary(tmp_path / "library", inbox)

    first = library.scan()
    second = library.scan()

    expected = f"source-{hashlib.sha256(content).hexdigest()}"
    assert first == {"sources": [], "pending_ids": [], "errors": []}
    assert second["pending_ids"] == [expected]
    assert second["sources"] == [
        {
            "source_id": expected,
            "sha256": expected.removeprefix("source-"),
            "paths": ["sample.txt"],
            "current_paths": ["sample.txt"],
            "status": "discovered",
            "format": "txt",
            "current": True,
            "error": "",
        }
    ]
    assert (tmp_path / "library" / "sources" / expected / "original.txt").read_bytes() == content


def test_extraction_preserves_complete_markdown_tables_and_final_evidence(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    content = "# Start\n\n| item | threshold |\n| --- | ---: |\n| alpha | 17.5 |\n\n# End\nTAIL-EVIDENCE"
    (inbox / "sample.md").write_text(content, encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)
    source_id = _admit(library)

    extracted = library.extract(source_id)

    assert extracted["markdown"] == content
    assert "TAIL-EVIDENCE" in extracted["markdown"]
    assert "| alpha | 17.5 |" in extracted["markdown"]
    assert "".join(block["text"] for block in extracted["blocks"]).replace("\n", "")
    assert all(block["page"] == 1 for block in extracted["blocks"])
    assert Path(extracted["path"]).read_text(encoding="utf-8") == content
    inspected = library.inspect(source_id, offset=0, limit=1)
    assert inspected["blocks"] == extracted["blocks"][:1]
    assert inspected["total_blocks"] == len(extracted["blocks"])
    assert inspected["next_offset"] == (1 if len(extracted["blocks"]) > 1 else None)


def test_model_blocks_are_utf8_byte_bounded_without_losing_cjk_text(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    content = "측정값" * 2_000 + "\n마지막-근거"
    (inbox / "korean.md").write_text(content, encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)

    extracted = library.extract(_admit(library))

    assert all(len(block["text"].encode("utf-8")) <= 2_000 for block in extracted["blocks"])
    assert "".join(block["text"] for block in extracted["blocks"]) == content


def test_csv_extraction_keeps_every_row_as_a_markdown_table(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "values.csv").write_text(
        'name,value,qualification\nalpha,17.5,"only when dry"\nomega,21.0,"conflicts with alpha"\n',
        encoding="utf-8",
    )
    library = SourceLibrary(tmp_path / "library", inbox)

    extracted = library.extract(_admit(library))

    assert "| name | value | qualification |" in extracted["markdown"]
    assert "| alpha | 17.5 | only when dry |" in extracted["markdown"]
    assert "| omega | 21.0 | conflicts with alpha |" in extracted["markdown"]


def test_json_extraction_preserves_lexical_numbers_and_key_order(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    raw = '{"z": 1.00, "a": 1e-06, "qualified": "dry only"}\n'
    (inbox / "evidence.json").write_text(raw, encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)

    extracted = library.extract(_admit(library))

    assert extracted["markdown"] == f"```json\n{raw}```"
    assert '"z": 1.00' in extracted["markdown"]
    assert '"a": 1e-06' in extracted["markdown"]


def test_pdf_extraction_uses_real_pdftotext_and_retains_page_provenance(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "sample.pdf").write_bytes(_minimal_text_pdf("PDF-END 17.5 MPa"))
    library = SourceLibrary(tmp_path / "library", inbox)

    extracted = library.extract(_admit(library))

    assert "PDF-END 17.5 MPa" in extracted["markdown"]
    assert extracted["blocks"][0]["page"] == 1
    assert "PDF-END 17.5 MPa" in extracted["blocks"][0]["text"]


def test_pdf_extraction_writes_one_preserved_markdown_file_per_page(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "paper.pdf").write_bytes(
        _multipage_text_pdf(
            ["PAGE-ONE 17.5 MPa          COLUMN-B", "PAGE-TWO tail fact 21.0 MPa"]
        )
    )
    library = SourceLibrary(tmp_path / "library", inbox)

    extracted = library.extract(_admit(library))

    extraction_root = Path(extracted["path"]).parent
    page_one = extraction_root / "pages" / "page-0001.md"
    page_two = extraction_root / "pages" / "page-0002.md"
    assert page_one.read_text(encoding="utf-8").strip() == (
        "PAGE-ONE 17.5 MPa   COLUMN-B"
    )
    assert page_two.read_text(encoding="utf-8").strip() == "PAGE-TWO tail fact 21.0 MPa"
    assert {block["page"] for block in extracted["blocks"]} == {1, 2}
    assert "   " not in extracted["blocks"][0]["text"]
    assert "MPa | COLUMN-B" in extracted["blocks"][0]["text"]
    assert "PAGE-ONE 17.5 MPa" in extracted["blocks"][0]["text"]
    assert "COLUMN-B" in extracted["blocks"][0]["text"]
    manifest = json.loads((extraction_root / "pages.json").read_text(encoding="utf-8"))
    assert manifest["source_id"] == extracted["source_id"]
    assert manifest["pages"] == extracted["pages"]
    assert [page["path"] for page in manifest["pages"]] == [
        "pages/page-0001.md",
        "pages/page-0002.md",
    ]
    assert all(len(page["sha256"]) == 64 for page in manifest["pages"])


def test_html_extraction_retains_paragraph_table_and_final_marker(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "sample.html").write_text(
        "<html><body><h1>Start</h1><p>Qualified value</p>"
        "<table><tr><th>item</th><th>value</th></tr>"
        "<tr><td>alpha</td><td>17.5</td></tr></table>"
        "<p>HTML-TAIL</p></body></html>",
        encoding="utf-8",
    )
    library = SourceLibrary(tmp_path / "library", inbox)

    extracted = library.extract(_admit(library))

    assert "# Start" in extracted["markdown"]
    assert "Qualified value" in extracted["markdown"]
    assert "| item | value |" in extracted["markdown"]
    assert "| alpha | 17.5 |" in extracted["markdown"]
    assert extracted["markdown"].endswith("HTML-TAIL")


def test_docx_extraction_retains_paragraph_table_and_final_marker(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>DOCX Start 17.5</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>item</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>value</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>alpha</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>21.0</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
    <w:p><w:r><w:t>DOCX-TAIL</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    with zipfile.ZipFile(inbox / "sample.docx", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
    library = SourceLibrary(tmp_path / "library", inbox)

    extracted = library.extract(_admit(library))

    assert "DOCX Start 17.5" in extracted["markdown"]
    assert "| item | value |" in extracted["markdown"]
    assert "| alpha | 21.0 |" in extracted["markdown"]
    assert extracted["markdown"].endswith("DOCX-TAIL")


def test_docx_extraction_includes_headers_footers_and_footnotes(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    parts = {
        "word/document.xml": '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>BODY</w:t></w:r></w:p></w:body></w:document>',
        "word/header1.xml": '<w:hdr xmlns:w="urn:w"><w:p><w:r><w:t>HEADER 17.5</w:t></w:r></w:p></w:hdr>',
        "word/footer1.xml": '<w:ftr xmlns:w="urn:w"><w:p><w:r><w:t>FOOTER condition</w:t></w:r></w:p></w:ftr>',
        "word/footnotes.xml": '<w:footnotes xmlns:w="urn:w"><w:footnote w:id="1"><w:p><w:r><w:t>FOOTNOTE dry only</w:t></w:r></w:p></w:footnote></w:footnotes>',
    }
    with zipfile.ZipFile(inbox / "parts.docx", "w") as archive:
        for name, xml in parts.items():
            archive.writestr(name, xml)
    library = SourceLibrary(tmp_path / "library", inbox)

    markdown = library.extract(_admit(library))["markdown"]

    assert "BODY" in markdown
    assert "## Header: header1.xml\n\nHEADER 17.5" in markdown
    assert "## Footer: footer1.xml\n\nFOOTER condition" in markdown
    assert "## Footnotes: footnotes.xml\n\nFOOTNOTE dry only" in markdown


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("image-only.html", b"<html><body><img src='figure.png'></body></html>"),
        ("image-only.docx", None),
    ],
)
def test_image_only_structured_source_fails_without_fabricated_text(
    tmp_path: Path, name: str, content: bytes | None
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / name
    if content is not None:
        path.write_bytes(content)
    else:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p/></w:body></w:document>',
            )
    library = SourceLibrary(tmp_path / "library", inbox)
    source_id = _admit(library)

    with pytest.raises(ValueError, match="no extractable text"):
        library.extract(source_id)


def test_equal_content_aliases_share_one_source(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for name in ("a.md", "nested/b.md"):
        path = inbox / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("same evidence", encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)

    library.scan()
    result = library.scan()

    assert len(result["sources"]) == 1
    assert result["sources"][0]["paths"] == ["a.md", "nested/b.md"]
    assert len(list((tmp_path / "library" / "sources").glob("source-*"))) == 1


def test_changed_content_creates_version_and_keeps_old_artifact(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "sample.md"
    path.write_text("version one", encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)
    old_id = _admit(library)
    old_original = tmp_path / "library" / "sources" / old_id / "original.md"

    path.write_text("version two", encoding="utf-8")
    unstable = library.scan()
    admitted = library.scan()

    assert unstable["pending_ids"] == []
    assert len(admitted["pending_ids"]) == 1
    new_id = admitted["pending_ids"][0]
    assert new_id != old_id
    by_id = {item["source_id"]: item for item in admitted["sources"]}
    assert by_id[old_id]["current"] is False
    assert by_id[old_id]["status"] == "missing"
    assert by_id[new_id]["current"] is True
    assert old_original.read_text(encoding="utf-8") == "version one"


def test_deleted_ready_source_is_not_retrieval_eligible(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "sample.md"
    path.write_text("# Threshold\n17.5", encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)
    source_id = _admit(library)
    extracted = library.extract(source_id)
    published = _publish(library, source_id, extracted)
    record_id = published["record_ids"][0]
    assert library.search("threshold")["hits"]

    path.unlink()
    scanned = library.scan()

    assert scanned["sources"][0]["status"] == "missing"
    assert scanned["sources"][0]["current"] is False
    assert library.search("threshold")["hits"] == []
    assert library.read(record_id)["status"] == "not_found"
    assert Path(extracted["path"]).is_file()


def test_scan_rejects_symlinks_and_unsupported_files_without_following_them(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("PRIVATE-OUTSIDE", encoding="utf-8")
    (inbox / "escape.md").symlink_to(outside)
    (inbox / "payload.exe").write_bytes(b"not a source")
    library = SourceLibrary(tmp_path / "library", inbox)

    result = library.scan()

    assert result["sources"] == []
    assert result["pending_ids"] == []
    assert len(result["errors"]) == 2
    assert all("PRIVATE-OUTSIDE" not in error for error in result["errors"])


def test_unreadable_text_fails_explicitly_without_partial_extraction(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "binary.txt").write_bytes(b"\xff\xfe\x00\x80")
    library = SourceLibrary(tmp_path / "library", inbox)
    source_id = _admit(library)

    with pytest.raises(ValueError, match="UTF-8"):
        library.extract(source_id)

    source = {item["source_id"]: item for item in library.status()["sources"]}[source_id]
    assert source["status"] == "failed"
    assert "UTF-8" in source["error"]
    assert not (tmp_path / "library" / "sources" / source_id / "source.md").exists()


def test_publication_is_atomic_validated_and_scoped(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "sample.md").write_text("# Evidence\nThreshold 17.5\nTAIL", encoding="utf-8")
    root = tmp_path / "library"
    library = SourceLibrary(root, inbox)
    source_id = _admit(library)
    extracted = library.extract(source_id)

    for invalid in (
        _note(extracted, source_block_ids=["block-unknown"]),
        _note(extracted, ontology_type="InventedClass"),
        _note(extracted, category="../../escape"),
    ):
        with pytest.raises(ValueError):
            library.publish(
                source_id,
                [invalid, _note(extracted, title="second")],
                model={"provider": "test", "model": "fixture", "mock": True, "real": False},
                trace=[],
            )
        assert list(root.glob("sources/*/publications/*/notes/**/*.md")) == []
    with pytest.raises(ValueError, match="notes"):
        library.publish(
            source_id,
            [],
            model={"provider": "test", "model": "fixture", "mock": True, "real": False},
            trace=[],
        )
    with pytest.raises(ValueError, match="mock"):
        library.publish(
            source_id,
            [_note(extracted)],
            model={"provider": "test", "model": "fixture", "mock": True, "real": True},
            trace=[],
        )

    publication = _publish(library, source_id, extracted)
    repeated = _publish(library, source_id, extracted)
    record_id = publication["record_ids"][0]
    assert repeated["status"] == "unchanged"
    assert repeated["record_ids"] == publication["record_ids"]
    assert repeated["paths"] == publication["paths"]
    assert all(Path(path).is_file() for path in repeated["paths"])
    hit = library.search(
        "17.5",
        scope={
            "source_id": source_id,
            "category": ["process-guidance"],
            "ontology_type": "KnowledgeClaim",
            "tags": ["threshold", "qualified"],
            "applicability": {"condition": "fixture-a"},
        },
    )["hits"][0]
    assert hit["record_id"] == record_id
    assert hit["source_id"] == source_id
    assert hit["source_refs"] == [f"source:{source_id}#{extracted['blocks'][-1]['block_id']}"]
    assert hit["citations"][0]["block_id"] == extracted["blocks"][-1]["block_id"]
    assert "body" not in hit and "17.5" in hit["excerpt"]
    lightweight = library.read(record_id)["record"]
    assert lightweight["body"].endswith("test condition.")
    assert "source_markdown" not in lightweight and "source_blocks" not in lightweight
    detailed = library.read(record_id, include_source=True)["record"]
    assert detailed["source_markdown"] == extracted["markdown"]
    assert detailed["source_blocks"] == extracted["blocks"]
    assert library.search("", scope={"source_id": []})["hits"] == []
    assert library.read(record_id, scope={"tags": []})["status"] == "not_found"
    with pytest.raises(ValueError, match="unknown scope"):
        library.search("threshold", scope={"path": "../outside"})
    with pytest.raises(ValueError, match="unknown scope"):
        library.read(record_id, scope={"run_id": "fake"})

    again = library.extract(source_id)
    assert again["status"] == "ready"
    assert library.search("17.5")["hits"][0]["record_id"] == record_id
    assert library.scan()["pending_ids"] == []


def test_final_publication_requires_exactly_one_note(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "sample.md").write_text("Grounded evidence", encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)
    source_id = _admit(library)
    extracted = library.extract(source_id)

    with pytest.raises(ValueError, match="exactly one"):
        library.publish(
            source_id,
            [_note(extracted), _note(extracted, title="Second valid note")],
            model={"provider": "test", "model": "fixture", "mock": True, "real": False},
            trace=[],
        )

    assert library.search("")["hits"] == []


@pytest.mark.parametrize("relative", ["source.md", "pages/page-0001.md", "blocks.json"])
def test_extraction_rehydration_rejects_tampered_artifacts(
    tmp_path: Path, relative: str
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "sample.md").write_text("Grounded evidence 17.5", encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)
    source_id = _admit(library)
    extracted = library.extract(source_id)
    target = Path(extracted["path"]).parent / relative
    if target.suffix == ".json":
        target.write_text('{"source_id":"forged","blocks":[]}', encoding="utf-8")
    else:
        target.write_text("FORGED", encoding="utf-8")

    with pytest.raises(ValueError, match="hash|identity"):
        library.inspect(source_id)


def test_extract_recovers_after_directory_publish_precedes_catalog_pin(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "sample.md").write_text("Recoverable evidence", encoding="utf-8")

    class FailCatalogPinOnce(SourceLibrary):
        fail_pin = True

        def _persist_source(self, catalog: dict, source: dict) -> None:
            if self.fail_pin and source.get("extraction_id"):
                self.fail_pin = False
                raise OSError("injected catalog pin failure")
            super()._persist_source(catalog, source)

    library = FailCatalogPinOnce(tmp_path / "library", inbox)
    source_id = _admit(library)

    with pytest.raises(OSError, match="injected"):
        library.extract(source_id)
    extracted = library.extract(source_id)

    assert extracted["markdown"] == "Recoverable evidence"
    extraction_parent = Path(extracted["path"]).parent.parent
    assert list(extraction_parent.glob(".orphan-*"))


def test_new_immutable_original_is_not_visible_when_atomic_link_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "original.pdf"

    def fail_link(source: object, destination: object) -> None:
        raise OSError("injected atomic link failure")

    monkeypatch.setattr(source_library_module.os, "link", fail_link)

    with pytest.raises(OSError, match="injected"):
        source_library_module._write_bytes_new(target, b"complete-source")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_publication_rejects_source_changed_after_scan(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "sample.md"
    path.write_text("stable evidence", encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)
    source_id = _admit(library)
    extracted = library.extract(source_id)
    path.write_text("changed while processing", encoding="utf-8")

    with pytest.raises(ValueError, match="changed"):
        _publish(library, source_id, extracted)

    assert library.search("")["hits"] == []


def test_publication_trace_accepts_valid_deep_applicability_envelope(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "sample.md").write_text("Nested conditions evidence", encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)
    source_id = _admit(library)
    extracted = library.extract(source_id)
    applicability = {
        "conditions": [
            {"range": {"limits": [{"minimum": 1, "maximum": 2}]}}
        ]
    }
    note = _note(extracted, applicability=applicability)
    trace = [
        {"tool": "inspect_source", "observation": {"blocks": extracted["blocks"]}},
        {
            "tool": "publish_knowledge",
            "arguments": {"notes": [note]},
            "observation": {"status": "publication_requested"},
        },
    ]

    result = library.publish(
        source_id,
        [note],
        model={"provider": "test", "model": "fixture", "mock": True, "real": False},
        trace=trace,
    )

    stored = json.loads(
        (Path(result["paths"][0]).parents[2] / "trace.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored == trace

    too_deep: object = "end"
    for _ in range(18):
        too_deep = {"next": too_deep}
    with pytest.raises(ValueError, match=r"trace.*exceeds maximum nesting depth"):
        library.publish(
            source_id,
            [note],
            model={"provider": "test", "model": "fixture", "mock": True, "real": False},
            trace=[too_deep],
        )
