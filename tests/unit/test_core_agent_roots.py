"""Canonical agent owners keep one import surface and stable registry identities."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
RETAINED_ROOT_FILES = {
    "__init__.py",
    "attention.py",
    "base_agent.py",
    "control_structure.py",
    "execution_graph.py",
    "module_contract.py",
    "module_discovery.py",
    "registry.py",
}
RETIRED_TO_CANONICAL = {
    "analysis_agent": "agents.analysis.agent",
    "analysis_decisions": "agents.analysis.decisions",
    "bo_agent": "agents.bo.agent",
    "bo_decision": "agents.bo.decision",
    "design_agent": "agents.design.agent",
    "design_decision": "agents.design.decision",
    "equipment_agent": "agents.equipment.agent",
    "equipment_decision": "agents.equipment.decision",
    "equipment_workflow": "agents.equipment.workflow",
    "guardian_agent": "agents.core.guardian.agent",
    "knowledge_agent": "agents.core.knowledge.agent",
    "knowledge_context": "agents.core.knowledge.context",
    "knowledge_decision": "agents.core.knowledge.decision",
    "manipulation_agent": "agents.manipulation.agent",
    "manipulation_decision": "agents.manipulation.decision",
    "orchestrator_agent": "agents.core.orchestrator.agent",
    "orchestrator_capabilities": "agents.core.orchestrator.capabilities",
    "orchestrator_decision": "agents.core.orchestrator.decision",
    "orchestrator_execution": "agents.core.orchestrator.execution",
    "orchestrator_structure": "agents.core.orchestrator.structure",
    "source_curation": "agents.core.knowledge.source_curation",
    "specimen_agent": "agents.specimen.agent",
    "specimen_decision": "agents.specimen.decision",
    "vision_agent": "agents.vision.agent",
    "vision_decision": "agents.vision.decision",
}
AGENT_CLASSES = (
    ("agents.analysis.agent", "AnalysisAgent", "analysis_agent"),
    ("agents.bo.agent", "BOAgent", "bo_agent"),
    ("agents.design.agent", "DesignAgent", "design_agent"),
    ("agents.equipment.agent", "LabEquipmentAgent", "equipment_agent"),
    ("agents.core.guardian.agent", "GuardianAgent", "guardian_agent"),
    ("agents.core.knowledge.agent", "KnowledgeAgent", "knowledge_agent"),
    ("agents.manipulation.agent", "ManipulationAgent", "manipulation_agent"),
    ("agents.core.orchestrator.agent", "OrchestratorAgent", "orchestrator_agent"),
    ("agents.specimen.agent", "SpecimenMakingAgent", "specimen_agent"),
    ("agents.vision.agent", "VisionAgent", "vision_agent"),
)
def test_agent_root_contains_only_shared_runtime_files() -> None:
    """Would fail if a retired wrapper remained or a shared root file was removed."""
    assert {path.name for path in (ROOT / "agents").glob("*.py")} == RETAINED_ROOT_FILES


def test_all_retired_modules_have_canonical_imports() -> None:
    """Would fail if any owner module were unavailable after wrapper retirement."""
    assert len(RETIRED_TO_CANONICAL) == 25
    for module_name in RETIRED_TO_CANONICAL.values():
        assert importlib.import_module(module_name).__name__ == module_name


def test_canonical_agent_classes_keep_registry_identities() -> None:
    """Would fail if caller migration changed a runtime agent ID or class owner."""
    from agents.registry import AgentRegistry

    registry = AgentRegistry()
    for module_name, class_name, agent_id in AGENT_CLASSES:
        agent_class = getattr(importlib.import_module(module_name), class_name)
        assert agent_class.__module__ == module_name
        registry.register(agent_class())
        assert registry.get(agent_id).__class__ is agent_class
    assert registry.names() == sorted(agent_id for _, _, agent_id in AGENT_CLASSES)


def test_maintained_python_uses_no_retired_agent_imports() -> None:
    """Would fail if a maintained caller still depended on a removed root module."""
    retired_imports = {f"agents.{stem}" for stem in RETIRED_TO_CANONICAL}
    completed = subprocess.run(
        ["git", "ls-files", "-z", "*.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths = [
        ROOT / item.decode("utf-8")
        for item in completed.stdout.split(b"\0")
        if item and b"oldversion" not in item
    ]
    stale: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        stale.extend(
            f"{relative}: {retired_import}"
            for retired_import in retired_imports
            if retired_import in text
        )
        if "from agents import" in text:
            tree = ast.parse(text, filename=str(relative))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "agents":
                    for alias in node.names:
                        if alias.name in RETIRED_TO_CANONICAL:
                            stale.append(f"{relative}:{node.lineno}: from agents import {alias.name}")
    assert stale == []


@pytest.mark.asyncio
async def test_core_owner_defaults_still_resolve_the_repository_root(monkeypatch, tmp_path: Path) -> None:
    """Would fail if the deeper canonical nesting changed default or explicit storage roots."""
    from agents.core.knowledge import agent as knowledge
    from agents.core.orchestrator.capabilities import OwnerCatalog
    from agents.registry import AgentRegistry
    from graphs.schema import GraphConfig, GraphNode
    from orchestrator.state import OrchestratorState

    graph = GraphConfig(id="core-root", name="Core root", entry_node="owner", nodes=[
        GraphNode(id="owner", label="Owner", handler="agent.missing"),
    ])
    assert OwnerCatalog(AgentRegistry(), graph).graph_root == (ROOT / "graphs").resolve()

    seen: list[Path] = []

    class StopAfterRoot(RuntimeError):
        pass

    def capture(project_root: Path):
        seen.append(Path(project_root))
        raise StopAfterRoot

    monkeypatch.setattr(knowledge.JsonlKnowledgeStore, "default", capture)
    state = OrchestratorState(run_id="core-root", experiment_id="core-root")
    with pytest.raises(StopAfterRoot):
        await knowledge.KnowledgeAgent().run(state, SimpleNamespace(artifact_run_root=None))
    assert seen.pop() == ROOT

    artifact_root = tmp_path / "runs"
    with pytest.raises(StopAfterRoot):
        await knowledge.KnowledgeAgent().run(
            state,
            SimpleNamespace(artifact_run_root=str(artifact_root)),
        )
    assert seen.pop() == tmp_path.resolve()


def test_knowledge_local_event_loads_ontology_from_repository_root(monkeypatch, tmp_path: Path) -> None:
    """Would fail if canonical nesting redirected ontology lookup into agents/."""
    from agents.core.knowledge import agent as knowledge
    from knowledge.schemas import ExperimentKnowledgeRecord
    from orchestrator.state import OrchestratorState

    seen: list[Path] = []

    def capture(project_root: Path):
        seen.append(Path(project_root))
        raise RuntimeError("stop after ontology root")

    monkeypatch.setattr(knowledge.OntologyRegistry, "load_default", capture)
    result = knowledge._ingest_local_event(
        project_root=tmp_path,
        state=OrchestratorState(run_id="core-root", experiment_id="core-root"),
        experiment_record=ExperimentKnowledgeRecord(
            record_id="record",
            run_id="core-root",
            experiment_id="core-root",
            summary="controlled fixture",
        ),
        artifact_refs=[],
        occurred_at="2026-09-14T00:00:00Z",
    )
    assert result["status"] == "degraded"
    assert seen == [ROOT]


def test_core_agents_keep_registry_ids_and_are_not_specialist_packages() -> None:
    """Would fail if the folder move changed owner IDs or joined package discovery."""
    from agents.core.guardian.agent import GuardianAgent
    from agents.core.knowledge.agent import KnowledgeAgent
    from agents.core.orchestrator.agent import OrchestratorAgent
    from agents.module_discovery import discover_agent_modules
    from agents.registry import AgentRegistry

    registry = AgentRegistry()
    for agent in (OrchestratorAgent(), KnowledgeAgent(), GuardianAgent()):
        registry.register(agent)
    assert registry.names() == ["guardian_agent", "knowledge_agent", "orchestrator_agent"]

    discovered = discover_agent_modules()
    assert not {"orchestrator", "knowledge", "guardian"} & {module.module_id for module in discovered}
    assert all(module.agent_name not in registry.names() for module in discovered)
