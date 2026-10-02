"""Knowledge source selection is independent of private persistence and provenance."""
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
import json
import shutil

import pytest

from utils.runtime_paths import RuntimePaths
from knowledge.graph_backend import JsonGraphBackend, graph_backend_from_env
from knowledge.ontology.registry import OntologyRegistry
from knowledge.service import KnowledgeService

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def paths(tmp_path):
    paths = RuntimePaths(**{f.name: tmp_path / f.name for f in fields(RuntimePaths)})
    shutil.copytree(ROOT / 'knowledge/ontology', paths.runtime_root / 'knowledge/ontology')
    return paths


def _event():
    return {'run_id': 'run-layout', 'cycle_id': 'cycle-1', 'source_agent': 'knowledge_agent',
            'event_type': 'specimen.analyzed', 'occurred_at': '2026-08-08T02:00:00Z',
            'entity_refs': [{'entity_id': 'runtime:specimen:s-1', 'entity_class': 'Specimen'}]}


def test_bound_service_persists_event_graph_and_outbox_without_repository_store(paths, monkeypatch):
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '1')
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_BACKEND', 'json')
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_MAX_ATTEMPTS', '3')
    service = KnowledgeService.from_env(paths.repository_root, paths=paths)
    result = service.ingest(_event())
    assert result['ok'] and result['sync']['acknowledged'] == 1
    assert service.project_root == paths.repository_root
    assert service.ledger.root == paths.memory_root / 'knowledge/ledger'
    assert service.outbox.root == paths.memory_root / 'knowledge/outbox'
    assert Path(result['ledger_receipt']['path']).is_relative_to(service.ledger.root)
    graph = paths.memory_root / 'knowledge/graph_backend/knowledge_graph.json'
    assert graph.is_file() and json.loads(graph.read_text())['nodes']
    assert not paths.repository_root.exists()
    assert not (paths.runtime_root / 'memory').exists()
    assert service.registry == OntologyRegistry.load_default(ROOT)


def test_two_bound_services_preserve_graph_ids_and_evidence(paths, monkeypatch):
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '1')
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_BACKEND', 'json')
    second = replace(paths, memory_root=paths.memory_root.with_name('other-memory'))
    services = [KnowledgeService.from_env(p.repository_root, paths=p) for p in (paths, second)]
    results = [s.ingest(_event()) for s in services]
    assert results[0]['event_id'] == results[1]['event_id']
    assert Path(results[0]['ledger_receipt']['path']).read_bytes() == Path(results[1]['ledger_receipt']['path']).read_bytes()
    graphs = [json.loads(s.repository.backend.path.read_text()) for s in services]
    assert graphs[0]['nodes'] == graphs[1]['nodes']
    assert graphs[0]['edges'] == graphs[1]['edges']
    assert services[0].outbox.root != services[1].outbox.root


def test_registry_explicit_source_and_no_fallback(paths):
    assert OntologyRegistry.load_default(paths.repository_root, runtime_root=paths.runtime_root) == OntologyRegistry.load_default(ROOT)
    with pytest.raises(FileNotFoundError):
        OntologyRegistry.load_default(ROOT, runtime_root=paths.runtime_root / 'missing')


def test_disabled_backend_does_not_activate_store(paths, monkeypatch):
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '0')
    backend = graph_backend_from_env(paths.repository_root, paths=paths)
    assert backend.health()['status'] == 'disabled'
    assert not paths.memory_root.exists()
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '1')
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_BACKEND', 'neo4j')
    monkeypatch.delenv('ATR_NEO4J_PASSWORD', raising=False)
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_FAIL_OPEN', '1')
    assert graph_backend_from_env(paths.repository_root, paths=paths).health()['status'] == 'degraded'
    assert not paths.memory_root.exists()


def test_supplied_registry_backend_and_legacy_storage_are_preserved(paths, tmp_path):
    registry = OntologyRegistry.load_default(ROOT)
    backend = JsonGraphBackend(tmp_path / 'explicit/graph.json')
    service = KnowledgeService(paths.repository_root, backend=backend, registry=registry, paths=paths)
    assert service.registry is registry and service.repository.backend is backend
    legacy = KnowledgeService(tmp_path / 'legacy', backend=backend, registry=registry)
    assert legacy.ledger.root == tmp_path / 'legacy/memory/knowledge/ledger'


def test_source_and_markdown_factories_use_selected_ontology_without_cache_leak(paths):
    from knowledge.source_runtime import library_for
    from knowledge.markdown_runtime import store_for
    selected = paths.runtime_root / 'knowledge/ontology/atr_core.v1.yaml'
    selected.write_text(selected.read_text().replace('Observation', 'BoundObservation'))
    library = library_for(library_root=paths.memory_root / 'knowledge/source_library',
                          inbox_root=paths.source_inbox_root, runtime_root=paths.runtime_root)
    store = store_for(SimpleNamespace(paths=paths))
    assert 'BoundObservation' in library._ontology.class_names
    assert 'BoundObservation' in store.ontology.class_names
    other = replace(paths, runtime_root=ROOT)
    other_store = store_for(SimpleNamespace(paths=other))
    assert other_store is not store
    assert 'Observation' in other_store.ontology.class_names


@pytest.mark.asyncio
@pytest.mark.parametrize('binding', ['context', 'omitted'])
async def test_knowledge_agent_uses_context_stores_and_local_ontology(paths, monkeypatch, binding):
    from agents.core.knowledge.agent import KnowledgeAgent
    from tests.unit.test_knowledge_agent import _CtxStub, _state
    ctx = _CtxStub()
    ctx.paths = paths if binding == 'context' else None
    ctx.artifact_run_root = str(paths.run_root) if binding == 'context' else None
    monkeypatch.setattr('utils.runtime_paths.current_paths', lambda: paths)
    for definition in (paths.runtime_root / 'knowledge/ontology').glob('*.yaml'):
        definition.write_text(definition.read_text().replace('atr-core-1.0.0', 'bound-ontology-1'))
    result = await KnowledgeAgent().run(_state(), ctx)
    knowledge = result.data['knowledge']
    files = list((paths.run_root / 'run-knowledge/knowledge').glob('*.json'))
    assert len(files) >= 6
    assert (paths.memory_root / 'knowledge/experiment_knowledge_records.jsonl').is_file()
    ledgers = list((paths.memory_root / 'knowledge/ledger').rglob('events.jsonl'))
    assert len(ledgers) == 1
    event = json.loads(ledgers[0].read_text())
    assert event['artifact_refs'] == [{'kind': 'utm_csv', 'path': 'artifacts/equipment/run/utm.csv'}]
    assert event['ontology_version'] == 'bound-ontology-1'
    assert not paths.repository_root.exists()
    assert not (paths.runtime_root / 'memory').exists()
    intake = Path(knowledge['citations'][0]['source_ref'])
    original = intake.read_bytes()
    again = await KnowledgeAgent().run(_state(), ctx)
    assert intake.read_bytes() == original
    assert again.data['knowledge']['citations'][0]['source_ref'] == str(intake)


def test_bootstrap_lazy_library_reads_selected_ontology(paths, monkeypatch):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    monkeypatch.setattr(bootstrap, '_load_configs', lambda paths: {'system': {'system': {}}, 'models': {}, 'devices': {}, 'lerobot': {}})
    monkeypatch.setattr(bootstrap, '_build_backend', lambda *args, **kwargs: MockLLMBackend())
    guide = paths.system_root / 'project/Project_guide.txt'
    guide.parent.mkdir(parents=True)
    guide.write_text('Synthetic guide.')
    core = paths.runtime_root / 'knowledge/ontology/atr_core.v1.yaml'
    core.write_text(core.read_text().replace('Observation', 'BoundObservation'))
    controller = bootstrap.load_runtime(paths=paths)
    assert not (paths.memory_root / 'knowledge/source_library').exists()
    library = controller._deps.agent_context.tools.resource('knowledge.sources')()
    assert 'BoundObservation' in library._ontology.class_names


def test_flat_service_binding_matches_legacy_defaults(paths, tmp_path, monkeypatch):
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '1')
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_BACKEND', 'json')
    root = tmp_path / 'flat'
    shutil.copytree(ROOT / 'knowledge/ontology', root / 'knowledge/ontology')
    flat = replace(paths, repository_root=root, runtime_root=root, memory_root=root / 'memory', run_root=root / 'runs')
    old = KnowledgeService.from_env(root)
    new = KnowledgeService.from_env(root, paths=flat)
    assert old.registry == new.registry
    assert old.ledger.root == new.ledger.root == root / 'memory/knowledge/ledger'
    assert old.outbox.root == new.outbox.root == root / 'memory/knowledge/outbox'
    assert old.repository.backend.path == new.repository.backend.path
