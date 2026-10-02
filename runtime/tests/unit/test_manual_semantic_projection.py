from __future__ import annotations

from knowledge.manuals.graph_projection import load_manual_ontology, validate_manual_graph
from knowledge.manuals.models import SemanticEdge, SemanticNode
from knowledge.manuals.semantic_projection import build_semantic_graph, project_semantic_subgraph, validate_semantic_provenance


def _chunk(chunk_id: str, text: str, *, page: int = 66, section: str = "장애 및 조치") -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": "software-manual",
        "equipment_type": "utm",
        "page": page,
        "section_path": [section],
        "text": text,
        "source_sha256": "sha-software",
    }


def _corpus(*chunks: dict) -> dict:
    return {
        "schema": "manual_corpus.v1",
        "sources": [{"source_id": "software-manual", "equipment_type": "utm", "title": "Software Manual"}],
        "chunks": list(chunks),
    }


def _evidence_graph(*chunks: dict) -> dict:
    return {
        "schema": "manual_knowledge_graph.v1",
        "nodes": [
            {
                "id": item["chunk_id"],
                "kind": "ManualChunk",
                "label": f"p.{item['page']}",
                "properties": {"page": item["page"], "source_id": item["source_id"]},
            }
            for item in chunks
        ],
        "edges": [],
    }


def test_semantic_records_preserve_page_level_support() -> None:
    node = SemanticNode(
        node_id="manual-semantic:fault:comm-failure",
        kind="Fault",
        label="통신 연결 실패",
        equipment_type="utm",
        confidence=0.92,
        supporting_chunk_ids=("manual-chunk:software:66:1",),
        citations=({"source_id": "software", "page": 66},),
        extraction_method="deterministic",
    )
    edge = SemanticEdge(
        edge_id="manual-semantic-edge:fault-support",
        source="manual-semantic:fault:comm-failure",
        target="manual-chunk:software:66:1",
        relation="SUPPORTED_BY",
        confidence=0.92,
        supporting_chunk_ids=("manual-chunk:software:66:1",),
        citations=({"source_id": "software", "page": 66},),
        extraction_method="deterministic",
    )

    assert node.as_dict()["properties"]["citations"][0]["page"] == 66
    assert edge.as_dict()["properties"]["supporting_chunk_ids"] == ["manual-chunk:software:66:1"]


def test_semantic_provenance_rejects_non_citation_items() -> None:
    payload = {
        "nodes": [
            {
                "id": "fault:1",
                "kind": "Fault",
                "properties": {
                    "supporting_chunk_ids": ["chunk:1"],
                    "citations": ["not-a-citation"],
                },
            }
        ],
        "edges": [],
        "evidence_node_ids": ["chunk:1"],
    }

    report = validate_semantic_provenance(payload)

    assert report["ok"] is False
    assert report["errors"] == ["semantic node lacks provenance: fault:1"]


def test_supported_by_accepts_semantic_to_evidence_edges() -> None:
    report = validate_manual_graph(
        nodes=[
            {"id": "fault:1", "kind": "Fault"},
            {"id": "chunk:1", "kind": "ManualChunk"},
        ],
        edges=[
            {
                "id": "edge:1",
                "source": "fault:1",
                "target": "chunk:1",
                "type": "SUPPORTED_BY",
            }
        ],
        ontology=load_manual_ontology(),
    )

    assert report == {"ok": True, "errors": []}


def test_build_semantic_graph_creates_cited_fault_chain() -> None:
    chunk = _chunk(
        "manual-chunk:software:66:1",
        "통신 연결 실패\n원인: RS-232 케이블이 연결되지 않았다.\n조치: COM 번호를 확인하고 다시 연결한다.",
    )

    graph = build_semantic_graph(_corpus(chunk), _evidence_graph(chunk))

    kinds = {node["kind"] for node in graph["nodes"]}
    relations = {edge["type"] for edge in graph["edges"]}
    assert {"Fault", "Cause", "Remedy"} <= kinds
    assert {"HAS_CAUSE", "RESOLVED_BY", "SUPPORTED_BY"} <= relations
    assert all(node["properties"]["citations"] for node in graph["nodes"])
    assert all(edge["properties"]["supporting_chunk_ids"] for edge in graph["edges"])


def test_alias_normalization_merges_only_type_compatible_entities() -> None:
    first = _chunk("manual-chunk:one", "통신 연결 실패\n원인: COM 포트 불일치\n조치: COM 번호를 변경한다.")
    second = _chunk("manual-chunk:two", "통신  연결  실패\n원인: COM 포트 불일치\n조치: 케이블을 다시 연결한다.", page=67)

    graph = build_semantic_graph(_corpus(first, second), _evidence_graph(first, second))

    faults = [node for node in graph["nodes"] if node["kind"] == "Fault"]
    causes = [node for node in graph["nodes"] if node["kind"] == "Cause"]
    remedies = [node for node in graph["nodes"] if node["kind"] == "Remedy"]
    assert len(faults) == 1
    assert len(causes) == 1
    assert len(remedies) == 2
    assert len(faults[0]["properties"]["citations"]) == 2


def test_procedure_steps_preserve_source_order() -> None:
    chunk = _chunk(
        "manual-chunk:procedure",
        "시험 시작 절차\n1. 장비 전원을 확인한다.\n2. 시편을 장착한다.\n3. 시험 시작을 누른다.",
        page=6,
        section="시험 순서",
    )

    graph = build_semantic_graph(_corpus(chunk), _evidence_graph(chunk))

    steps = sorted(
        (node for node in graph["nodes"] if node["kind"] == "ProcedureStep"),
        key=lambda node: node["properties"]["step_index"],
    )
    precedes = {(edge["source"], edge["target"]) for edge in graph["edges"] if edge["type"] == "PRECEDES"}
    assert len(steps) == 3
    assert precedes == {(steps[0]["id"], steps[1]["id"]), (steps[1]["id"], steps[2]["id"])}


def test_same_step_label_in_different_procedures_stays_separate() -> None:
    setup = _chunk(
        "manual-chunk:setup",
        "설정 절차\n1. 연결 상태를 확인한다.\n2. 설정을 저장한다.",
        page=7,
        section="설정 절차",
    )
    run = _chunk(
        "manual-chunk:run",
        "시험 절차\n1. 연결 상태를 확인한다.\n2. 시험을 시작한다.",
        page=15,
        section="시험 절차",
    )

    graph = build_semantic_graph(_corpus(setup, run), _evidence_graph(setup, run))

    repeated = [node for node in graph["nodes"] if node["kind"] == "ProcedureStep" and node["label"] == "연결 상태를 확인한다."]
    assert len(repeated) == 2
    assert {tuple(node["properties"]["supporting_chunk_ids"]) for node in repeated} == {
        ("manual-chunk:setup",),
        ("manual-chunk:run",),
    }


def test_incidental_cause_word_does_not_create_fault() -> None:
    chunk = _chunk("manual-chunk:plain", "설정 변경은 장비 오작동의 원인이 발생할 수 있습니다.")

    graph = build_semantic_graph(_corpus(chunk), _evidence_graph(chunk))

    assert not any(node["kind"] in {"Fault", "Cause", "Remedy"} for node in graph["nodes"])


def test_query_projection_hides_chunks_and_keeps_recovery_path() -> None:
    chunk = _chunk(
        "manual-chunk:recovery",
        "통신 연결 실패\n원인: COM 포트 불일치\n조치: COM 번호를 변경한다.",
    )
    graph = build_semantic_graph(_corpus(chunk), _evidence_graph(chunk))

    projection = project_semantic_subgraph(graph, {chunk["chunk_id"]}, "recovery")

    assert all(node["kind"] != "ManualChunk" for node in projection["nodes"])
    assert {edge["type"] for edge in projection["edges"]} == {"HAS_CAUSE", "RESOLVED_BY"}
    assert projection["depth"] == 2


def test_query_projection_is_deterministic_and_bounded() -> None:
    nodes = [
        {
            "id": f"node:{index:02d}",
            "kind": "ProcedureStep",
            "label": f"Step {index:02d}",
            "properties": {
                "confidence": 0.9,
                "supporting_chunk_ids": ["chunk:seed"],
                "citations": [{"source_id": "manual", "page": 1}],
            },
        }
        for index in range(50)
    ]
    edges = [
        {
            "id": f"edge:{index:02d}",
            "source": f"node:{index:02d}",
            "target": f"node:{index + 1:02d}",
            "type": "PRECEDES",
            "properties": {"supporting_chunk_ids": ["chunk:seed"], "citations": [{"source_id": "manual", "page": 1}]},
        }
        for index in range(49)
    ]
    graph = {"schema": "manual_semantic_graph.v1", "nodes": nodes, "edges": edges}

    first = project_semantic_subgraph(graph, {"chunk:seed"}, "procedure", node_limit=10, edge_limit=6)
    second = project_semantic_subgraph(graph, {"chunk:seed"}, "procedure", node_limit=10, edge_limit=6)

    assert first == second
    assert len(first["nodes"]) == 10
    assert len(first["edges"]) <= 6
    assert first["truncated"] is True
