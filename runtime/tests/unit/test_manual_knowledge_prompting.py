from __future__ import annotations

from knowledge.manuals.prompting import build_manual_grounded_prompt, manual_context_audit


def _context() -> dict[str, object]:
    return {
        "schema": "manual_context.v1",
        "equipment_type": "utm",
        "purpose": "recovery",
        "context_hash": "ctx-123",
        "insufficient_evidence": False,
        "chunks": [
            {
                "chunk_id": "manual:software:p12:001",
                "text": "시험이 시작되지 않으면 연결 상태와 시험 조건을 확인한다.",
                "citation": {
                    "source_id": "software-manual",
                    "title": "Software Manual",
                    "page": 12,
                    "section_path": ["시험 시작", "오류 복구"],
                    "source_sha256": "abc",
                },
            }
        ],
        "graph": {"nodes": [], "edges": []},
    }


def test_manual_prompt_keeps_page_and_chunk_citations_without_adding_actions() -> None:
    prompt = build_manual_grounded_prompt("Return bounded recovery JSON only.", _context())

    assert "Return bounded recovery JSON only." in prompt
    assert "manual:software:p12:001" in prompt
    assert "Software Manual" in prompt
    assert '"page": 12' in prompt
    assert "Do not create or change executable actions" in prompt


def test_manual_context_audit_is_bounded_and_source_separated() -> None:
    audit = manual_context_audit(_context())

    assert audit == {
        "schema": "manual_context_audit.v1",
        "equipment_type": "utm",
        "purpose": "recovery",
        "context_hash": "ctx-123",
        "insufficient_evidence": False,
        "citations": [
            {
                "chunk_id": "manual:software:p12:001",
                "source_id": "software-manual",
                "title": "Software Manual",
                "page": 12,
                "section_path": ["시험 시작", "오류 복구"],
            }
        ],
    }
