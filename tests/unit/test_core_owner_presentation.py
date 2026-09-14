"""Core owner presentation stays read-only and available outside package discovery."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from agents.core.guardian.module import CORE_MODULE as GUARDIAN_MODULE
from agents.core.knowledge.module import CORE_MODULE as KNOWLEDGE_MODULE


@pytest.mark.parametrize("module", [KNOWLEDGE_MODULE, GUARDIAN_MODULE])
def test_core_module_exposes_owner_report_and_frontend_without_activation(module):
    description = module.describe()

    assert module.project_report is not None
    assert module.frontend_root is not None
    assert module.frontend_root.is_dir()
    assert (module.frontend_root / "live_report.js").is_file()
    assert description["frontend"]["namespace"].startswith("AX4LAB")
    assert description["frontend"]["asset_url"].endswith("/live_report.js")
    assert description["configuration"]["activation_supported"] is False


def test_knowledge_projection_preserves_existing_metadata_precedence_and_shape():
    metadata = {
        "knowledge": {
            "knowledge_report": {
                "memory_intake": {"experiment_record_id": "metadata-record"},
                "evidence_quality": {"artifact_link_coverage": 0.75},
                "failure_patterns": [{"pattern_id": "failure-1"}],
            },
            "knowledge_context": {"schema": "knowledge_context.v1"},
            "evolution_proposal": {"schema": "evolution_proposal.v1", "evidence_packs": [{"target_type": "agent", "target_id": "vision"}]},
            "artifact_paths": {"knowledge_report": "knowledge/report.json"},
        }
    }
    agent_payload = {"knowledge": {"knowledge_report": {"memory_intake": {"experiment_record_id": "stale"}}}}
    before = deepcopy(metadata)

    projected = KNOWLEDGE_MODULE.project_report(metadata, agent_payload)

    assert metadata == before
    assert projected["knowledge_report"]["memory_intake"]["experiment_record_id"] == "metadata-record"
    assert projected["knowledge_context"]["schema"] == "knowledge_context.v1"
    assert projected["evolution_proposal"]["schema"] == "evolution_proposal.v1"
    assert projected["role_specific"]["memory_ledger"]["experiment_record_id"] == "metadata-record"
    assert projected["decisions"][0]["target_id"] == "vision"
    assert projected["metrics"] == {"artifact_link_coverage": 0.75}


def test_guardian_projection_is_detached_and_keeps_existing_report_sections():
    metadata = {
        "latest_guardian_decision": {"decision": "retry", "reason_code": "REVIEW"},
        "latest_guardian_report": {"risk_score": 0.7, "blocked_actions": ["printer.start"]},
        "guardian_status": {"schema": "guardian_status_report.v1", "status": "approval"},
    }
    before = deepcopy(metadata)

    projected = GUARDIAN_MODULE.project_report(metadata, {})

    assert metadata == before
    assert projected["guardian_decision"]["decision"] == "retry"
    assert projected["guardian_report"]["risk_score"] == 0.7
    assert projected["guardian_status"]["status"] == "approval"
    assert projected["decisions"] == [metadata["latest_guardian_decision"]]
    assert projected["metrics"]["risk_score"] == 0.7


def test_core_frontends_own_composition_without_pollers_or_event_registration():
    root = Path(__file__).resolve().parents[2]
    for owner in ("knowledge", "guardian"):
        source = (root / "agents" / "core" / owner / "frontend" / "live_report.js").read_text(encoding="utf-8")
        assert "function renderReport" in source
        assert "function renderDashboard" in source
        assert "function dispose" in source
        assert "setInterval(" not in source
        assert "addEventListener(" not in source


def test_reviewed_core_owner_wiki_pages_match_current_source_revisions():
    from knowledge.wiki import WikiCatalog

    catalog = WikiCatalog(Path(__file__).resolve().parents[2])
    for topic in ("knowledge-agent", "knowledge-role", "guardian-role", "agent-contracts"):
        document = catalog.read(topic)
        assert document is not None
        assert document["freshness"] == "fresh", topic
