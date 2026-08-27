from __future__ import annotations

import json
from pathlib import Path

import yaml

from knowledge.graph_backend import JsonGraphBackend
from knowledge.manuals.ingest import ManualIngestor
from knowledge.manuals.service import ManualKnowledgeService


def test_manual_ingest_preserves_page_section_and_source_provenance(tmp_path: Path) -> None:
    source = tmp_path / "manual.pdf"
    source.write_bytes(b"manual-source")
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "schema": "manual_source_registry.v1",
                "sources": [
                    {
                        "source_id": "utm-software",
                        "equipment_type": "utm",
                        "title": "UTM Software Manual",
                        "product": "Example Tester",
                        "version": "17.7.0",
                        "path": "manual.pdf",
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    ingestor = ManualIngestor(page_extractor=lambda _path: [
        "1. 시험 순서\n시험번호를 입력한다.\n시험 시작 버튼을 누른다.",
        "2. 장애 조치\n원인: 통신 포트 불일치\n조치: COM 번호를 일치시킨다.",
    ])
    result = ingestor.ingest_registry(registry, tmp_path / "runtime")

    assert result["ok"] is True
    corpus = json.loads((tmp_path / "runtime" / "corpus.json").read_text(encoding="utf-8"))
    assert corpus["schema"] == "manual_corpus.v1"
    assert corpus["sources"][0]["equipment_type"] == "utm"
    assert corpus["sources"][0]["product"] == "Example Tester"
    assert corpus["sources"][0]["version"] == "17.7.0"
    assert {chunk["page"] for chunk in corpus["chunks"]} == {1, 2}
    assert corpus["chunks"][0]["section_path"] == ["1. 시험 순서"]
    assert corpus["chunks"][1]["section_path"] == ["2. 장애 조치"]
    assert all(chunk["source_sha256"] for chunk in corpus["chunks"])
    assert all(chunk["chunk_id"].startswith("manual-chunk:") for chunk in corpus["chunks"])


def test_failed_ingest_does_not_replace_existing_corpus(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    corpus_path = runtime / "corpus.json"
    corpus_path.write_text('{"schema":"manual_corpus.v1","sentinel":true}\n', encoding="utf-8")
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "schema": "manual_source_registry.v1",
                "sources": [{"source_id": "missing", "equipment_type": "utm", "path": "missing.pdf"}],
            }
        ),
        encoding="utf-8",
    )

    result = ManualIngestor(page_extractor=lambda _path: []).ingest_registry(registry, runtime)

    assert result["ok"] is False
    assert json.loads(corpus_path.read_text(encoding="utf-8"))["sentinel"] is True


def _semantic_corpus() -> dict:
    return {
        "schema": "manual_corpus.v1",
        "sources": [{"source_id": "utm-software", "equipment_type": "utm", "title": "UTM Software Manual"}],
        "chunks": [
            {
                "chunk_id": "manual-chunk:recovery",
                "source_id": "utm-software",
                "equipment_type": "utm",
                "page": 66,
                "section_path": ["장애 조치"],
                "text": "통신 연결 실패\n원인: COM 포트 불일치\n조치: COM 번호를 변경한다.",
                "source_sha256": "sha",
            }
        ],
    }


def test_failed_semantic_rebuild_preserves_active_projection(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    active = runtime / "manual_semantic_graph.json"
    active.write_text('{"schema":"manual_semantic_graph.v1","version":"old"}\n', encoding="utf-8")

    def fake_ingest(_self, _registry, runtime_root):
        (runtime_root / "corpus.json").write_text(json.dumps(_semantic_corpus(), ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "source_count": 1, "chunk_count": 1}

    monkeypatch.setattr(ManualIngestor, "ingest_registry", fake_ingest)
    monkeypatch.setattr(
        "knowledge.manuals.service.build_semantic_graph",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("invalid support")),
    )
    service = ManualKnowledgeService(
        project_root=tmp_path,
        runtime_root=runtime,
        registry_path=tmp_path / "registry.yaml",
        graph_backend=JsonGraphBackend(tmp_path / "graph.json"),
    )

    result = service.ingest()

    assert result["ok"] is False
    assert json.loads(active.read_text(encoding="utf-8"))["version"] == "old"


def test_semantic_rebuild_persists_quality_metrics(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    def fake_ingest(_self, _registry, runtime_root):
        runtime_root.mkdir(parents=True, exist_ok=True)
        (runtime_root / "corpus.json").write_text(json.dumps(_semantic_corpus(), ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "source_count": 1, "chunk_count": 1}

    monkeypatch.setattr(ManualIngestor, "ingest_registry", fake_ingest)
    service = ManualKnowledgeService(
        project_root=tmp_path,
        runtime_root=runtime,
        registry_path=tmp_path / "registry.yaml",
        graph_backend=JsonGraphBackend(tmp_path / "graph.json"),
    )

    result = service.ingest()
    status = service.status()

    semantic = json.loads((runtime / "manual_semantic_graph.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert semantic["schema"] == "manual_semantic_graph.v1"
    assert status["semantic_node_count"] == 3
    assert status["semantic_edge_count"] >= 5
    assert status["semantic_provenance_coverage"] == 1.0
    assert status["fault_chain_completion_rate"] == 1.0
