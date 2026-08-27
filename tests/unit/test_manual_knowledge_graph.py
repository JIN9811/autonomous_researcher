from __future__ import annotations

from knowledge.manuals.graph_projection import load_manual_ontology, project_manual_graph, validate_manual_graph


def _corpus() -> dict:
    return {
        "schema": "manual_corpus.v1",
        "sources": [
            {
                "source_id": "utm-indicator",
                "equipment_type": "utm",
                "title": "Indicator Manual",
                "product": "QM100T",
                "version": "",
                "source_sha256": "abc",
            }
        ],
        "chunks": [
            {
                "chunk_id": "manual-chunk:one",
                "source_id": "utm-indicator",
                "equipment_type": "utm",
                "page": 48,
                "section_path": ["고장 및 진단"],
                "text": "원인: OVER LOAD가 걸렸다. 조치: 하중제로 후 하중을 제거한다.",
                "source_sha256": "abc",
            }
        ],
    }


def test_manual_graph_projects_utm_document_sections_faults_and_remedies() -> None:
    ontology = load_manual_ontology()
    nodes, edges = project_manual_graph(_corpus(), ontology=ontology)

    kinds = {node["kind"] for node in nodes}
    relations = {edge["type"] for edge in edges}
    assert {"EquipmentType", "ManualDocument", "ManualSection", "ManualChunk", "Fault", "Remedy"} <= kinds
    assert {"APPLIES_TO", "HAS_SECTION", "HAS_CHUNK", "HAS_CAUSE", "RESOLVED_BY", "SOURCED_FROM"} <= relations
    report = validate_manual_graph(nodes, edges, ontology=ontology)
    assert report == {"ok": True, "errors": []}


def test_manual_graph_rejects_relation_outside_manual_ontology() -> None:
    ontology = load_manual_ontology()
    nodes, edges = project_manual_graph(_corpus(), ontology=ontology)
    edges.append({"id": "bad", "source": nodes[0]["id"], "target": nodes[1]["id"], "type": "EXECUTES"})

    report = validate_manual_graph(nodes, edges, ontology=ontology)

    assert report["ok"] is False
    assert any("EXECUTES" in error for error in report["errors"])


def test_manual_graph_does_not_treat_incidental_korean_cause_word_as_fault_heading() -> None:
    corpus = _corpus()
    corpus["chunks"][0]["text"] = "설정 변경은 장비 오작동의 원인이 발생할 수 있습니다."

    nodes, _edges = project_manual_graph(corpus)

    assert "Fault" not in {node["kind"] for node in nodes}
    assert "Cause" not in {node["kind"] for node in nodes}
