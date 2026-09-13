"""Core-owned agent modules keep one implementation and their legacy imports."""

from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    ("agents.orchestrator_agent", "agents.core.orchestrator.agent", "OrchestratorAgent"),
    ("agents.orchestrator_decision", "agents.core.orchestrator.decision", None),
    ("agents.orchestrator_execution", "agents.core.orchestrator.execution", None),
    ("agents.orchestrator_structure", "agents.core.orchestrator.structure", None),
    ("agents.orchestrator_capabilities", "agents.core.orchestrator.capabilities", "OwnerCatalog"),
    ("agents.knowledge_agent", "agents.core.knowledge.agent", "KnowledgeAgent"),
    ("agents.knowledge_decision", "agents.core.knowledge.decision", None),
    ("agents.knowledge_context", "agents.core.knowledge.context", None),
    ("agents.source_curation", "agents.core.knowledge.source_curation", None),
    ("agents.guardian_agent", "agents.core.guardian.agent", "GuardianAgent"),
)


@pytest.mark.parametrize("legacy,canonical,public_symbol", MODULES)
def test_legacy_and_canonical_imports_are_the_same_mutable_module(
    legacy: str,
    canonical: str,
    public_symbol: str | None,
) -> None:
    """Would fail if a compatibility file re-exported a second module object."""
    first = importlib.import_module(legacy)
    marker = object()
    first._core_root_identity_probe = marker
    try:
        second = importlib.import_module(canonical)
        assert first is second
        assert second._core_root_identity_probe is marker
        if public_symbol:
            assert getattr(first, public_symbol) is getattr(second, public_symbol)
    finally:
        del first._core_root_identity_probe


@pytest.mark.parametrize("legacy_first", (True, False), ids=("cold-legacy-first", "cold-canonical-first"))
def test_every_mapping_preserves_identity_in_a_fresh_import_order(legacy_first: bool) -> None:
    """Would fail if either cold import order created compatibility wrapper modules."""
    pairs = [(legacy, canonical) for legacy, canonical, _ in MODULES]
    script = f"""
import importlib
pairs = {pairs!r}
first = [pair[0 if {legacy_first!r} else 1] for pair in pairs]
second = [pair[1 if {legacy_first!r} else 0] for pair in pairs]
loaded = [importlib.import_module(name) for name in first]
for pair, module, name in zip(pairs, loaded, second):
    other = importlib.import_module(name)
    assert module is other, pair
    module._core_root_identity_probe = pair
    assert other._core_root_identity_probe == pair
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


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
