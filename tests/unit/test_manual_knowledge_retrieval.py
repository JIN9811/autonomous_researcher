from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge.graph_backend import JsonGraphBackend
from knowledge.manuals.graph_projection import project_manual_graph
from knowledge.manuals.semantic_projection import build_semantic_graph
from knowledge.manuals.service import ManualKnowledgeService


def _write_corpus(root: Path) -> None:
    root.mkdir(parents=True)
    corpus = {
        "schema": "manual_corpus.v1",
        "sources": [
            {"source_id": "one", "equipment_type": "utm", "title": "Indicator", "product": "QM100T", "version": ""},
            {"source_id": "two", "equipment_type": "utm", "title": "Software", "product": "Qm_Tester", "version": "17.7.0"},
            {"source_id": "printer", "equipment_type": "printer", "title": "Printer", "product": "P1", "version": "1"},
        ],
        "chunks": [
            {"chunk_id": "manual-chunk:one", "source_id": "one", "equipment_type": "utm", "page": 48, "section_path": ["고장 및 진단"], "text": "액츄에이터 정지\n원인: OVER LOAD이다.\n조치: 하중제로 후 하중을 제거한다.", "source_sha256": "a"},
            {"chunk_id": "manual-chunk:two", "source_id": "two", "equipment_type": "utm", "page": 66, "section_path": ["장애의 종류 및 조치방법"], "text": "시험 시작 실패\n원인: 인디게이터 MODE가 잘못되었다.\n조치: MODE를 AUTO 또는 PC로 선택한다.", "source_sha256": "b"},
            {"chunk_id": "manual-chunk:printer", "source_id": "printer", "equipment_type": "printer", "page": 1, "section_path": ["인쇄"], "text": "프린터 시작 절차", "source_sha256": "c"},
        ],
    }
    (root / "corpus.json").write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
    nodes, edges = project_manual_graph(corpus)
    evidence_graph = {"schema": "manual_knowledge_graph.v1", "nodes": nodes, "edges": edges}
    (root / "manual_graph.json").write_text(json.dumps(evidence_graph, ensure_ascii=False), encoding="utf-8")
    semantic_graph = build_semantic_graph(corpus, evidence_graph)
    (root / "manual_semantic_graph.json").write_text(json.dumps(semantic_graph, ensure_ascii=False), encoding="utf-8")


def test_query_filters_only_by_utm_and_keeps_product_version_as_soft_hints(tmp_path: Path) -> None:
    runtime = tmp_path / "manual_rag"
    _write_corpus(runtime)
    service = ManualKnowledgeService(
        project_root=tmp_path,
        runtime_root=runtime,
        graph_backend=JsonGraphBackend(tmp_path / "graph.json"),
    )

    result = service.query(
        {
            "equipment_type": "utm",
            "query": "시험이 시작되지 않을 때 조치",
            "purpose": "recovery",
            "top_k": 4,
            "product_hint": "unknown future UTM",
            "version_hint": "999",
        }
    )

    assert result["schema"] == "manual_context.v1"
    assert result["equipment_type"] == "utm"
    assert {item["source_id"] for item in result["chunks"]} == {"one", "two"}
    assert all(item["equipment_type"] == "utm" for item in result["chunks"])
    assert all(item["citation"]["page"] >= 1 for item in result["chunks"])
    assert "web_results" not in result


def test_recovery_query_prioritizes_fault_and_remedy_sections(tmp_path: Path) -> None:
    runtime = tmp_path / "manual_rag"
    _write_corpus(runtime)
    service = ManualKnowledgeService(
        project_root=tmp_path,
        runtime_root=runtime,
        graph_backend=JsonGraphBackend(tmp_path / "graph.json"),
    )

    result = service.query(
        {
            "equipment_type": "utm",
            "query": "통신 연결 실패로 시험이 시작되지 않을 때 복구 절차",
            "purpose": "recovery",
            "top_k": 2,
        }
    )

    assert result["chunks"][0]["chunk_id"] == "manual-chunk:two"
    assert result["chunks"][0]["citation"]["section_path"] == ["장애의 종류 및 조치방법"]


def test_query_keeps_ranked_chunks_and_adds_semantic_projection(tmp_path: Path) -> None:
    runtime = tmp_path / "manual_rag"
    _write_corpus(runtime)
    service = ManualKnowledgeService(
        project_root=tmp_path,
        runtime_root=runtime,
        graph_backend=JsonGraphBackend(tmp_path / "graph.json"),
    )

    result = service.query(
        {
            "equipment_type": "utm",
            "query": "시험 시작이 되지 않을 때 확인 절차",
            "purpose": "recovery",
            "top_k": 2,
        }
    )

    assert result["chunks"]
    assert result["semantic_projection"]["schema"] == "manual_semantic_projection.v1"
    assert all(node["kind"] != "ManualChunk" for node in result["semantic_projection"]["nodes"])


@pytest.mark.parametrize("purpose", ["skill_authoring", "procedure", "decision", "safety", "recovery"])
def test_query_accepts_allowlisted_utm_llm_purposes(tmp_path: Path, purpose: str) -> None:
    runtime = tmp_path / "manual_rag"
    _write_corpus(runtime)
    service = ManualKnowledgeService(project_root=tmp_path, runtime_root=runtime, graph_backend=JsonGraphBackend(tmp_path / "graph.json"))

    assert service.query({"equipment_type": "utm", "query": "시험", "purpose": purpose})["purpose"] == purpose


def test_query_rejects_non_utm_equipment_type(tmp_path: Path) -> None:
    runtime = tmp_path / "manual_rag"
    _write_corpus(runtime)
    service = ManualKnowledgeService(project_root=tmp_path, runtime_root=runtime, graph_backend=JsonGraphBackend(tmp_path / "graph.json"))

    with pytest.raises(ValueError, match="equipment_type must be utm"):
        service.query({"equipment_type": "printer", "query": "start", "purpose": "procedure"})
