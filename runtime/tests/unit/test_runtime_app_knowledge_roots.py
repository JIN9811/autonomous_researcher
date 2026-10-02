"""App factories retain the app's frozen binding across Knowledge helper chains."""
from dataclasses import replace
from pathlib import Path
import shutil
import json

import pytest


@pytest.fixture
def bound(tmp_path, monkeypatch):
    import app.main as main
    from utils.runtime_paths import current_paths
    root = Path(__file__).resolve().parents[2]
    paths = replace(current_paths(), repository_root=tmp_path / 'repository', runtime_root=tmp_path / 'source',
                    memory_root=tmp_path / 'private', run_root=tmp_path / 'run-data', source_inbox_root=tmp_path / 'inbox')
    shutil.copytree(root / 'knowledge/ontology', paths.runtime_root / 'knowledge/ontology')
    monkeypatch.setattr(main, 'RUNTIME_PATHS', paths)
    monkeypatch.setattr(main, 'KNOWLEDGE_MEMORY_ROOT', paths.memory_root / 'knowledge')
    monkeypatch.setattr(main, 'resolve_path', lambda value: paths.repository_root / value)
    return main, paths


def test_app_knowledge_factories_use_named_memory_run_and_runtime_ontology(bound, monkeypatch):
    main, paths = bound
    store = main._knowledge_store()
    written = store.write_run_artifacts('fixture', {'knowledge_report': {'evidence': 'same bytes'}})
    assert Path(written['knowledge_report']) == paths.run_root / 'fixture/knowledge/knowledge_report.json'
    assert store.memory_root == paths.memory_root / 'knowledge'
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '1')
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_BACKEND', 'json')
    backend = main._knowledge_graph_backend()
    backend.upsert_nodes([{'id': 'fixture', 'kind': 'Observation'}])
    assert backend.path == paths.memory_root / 'knowledge/graph_backend/knowledge_graph.json'
    service = main._knowledge_service()
    assert service.ledger.root == paths.memory_root / 'knowledge/ledger'
    assert service.registry.version_id
    assert service.repository.backend.health()['status'] == 'retired'
    assert not paths.repository_root.exists()


def test_legacy_reconciliation_explicit_store_keeps_repository_provenance(bound, monkeypatch):
    main, paths = bound
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '0')
    monkeypatch.setattr(main, '_KNOWLEDGE_RECONCILIATION_WORKER', None)
    monkeypatch.setattr(main, '_KNOWLEDGE_RECONCILIATION_SERVICE', None)
    monkeypatch.setattr(main, '_KNOWLEDGE_RECONCILIATION_KNOWLEDGE_SERVICE', None)
    worker = main._legacy_knowledge_reconciliation_worker()
    assert worker.service.project_root == paths.repository_root
    assert worker.service.store.root == paths.memory_root / 'knowledge/reconciliation'
    assert worker.service.knowledge_service.outbox.root == paths.memory_root / 'knowledge/outbox'
    with pytest.raises(Exception) as exc:
        main._knowledge_reconciliation_worker()
    assert exc.value.status_code == 410
    assert not paths.repository_root.exists()


def test_app_markdown_and_source_library_use_bound_ontology(bound, monkeypatch):
    main, paths = bound
    core = paths.runtime_root / 'knowledge/ontology/atr_core.v1.yaml'
    core.write_text(core.read_text().replace('Observation', 'BoundObservation'))
    monkeypatch.setattr(main, '_SOURCE_INGESTION_SERVICE', None)
    assert 'BoundObservation' in main._markdown_store().ontology.class_names
    service = main._source_ingestion_service()
    assert 'BoundObservation' in service.library._ontology.class_names
    assert service.library.root == paths.memory_root / 'knowledge/source_library'


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit', [None, 'memory/knowledge/graphify', '/tmp/explicit-graphify'])
async def test_legacy_graphify_absent_private_defaults_and_explicit_inputs(bound, monkeypatch, explicit):
    main, paths = bound
    captured = []
    def scan(root, **kwargs):
        captured.append((root, kwargs))
        return {'ok': True, 'node_count': 0, 'edge_count': 0}
    async def emit(**kwargs):
        pass
    monkeypatch.setattr(main, 'scan_project_graph', scan)
    monkeypatch.setattr(main.controller, 'emit_runtime_event', emit)
    await main.post_knowledge_graphify_scan({} if explicit is None else {'out_dir': explicit})
    expected = paths.memory_root / 'knowledge/graphify' if explicit is None else paths.repository_root / explicit
    assert captured[0][1]['out_dir'] == expected
    assert captured[0][0] == paths.repository_root
    response = await main.post_knowledge_graphify_import({} if explicit is None else {'graphify_json': explicit + '/project_graph.json'})
    assert str(expected / 'project_graph.json') in response['error']


def test_active_markdown_intake_uses_bound_run_root(bound, monkeypatch):
    from fastapi.testclient import TestClient
    import knowledge.markdown_runtime as markdown
    main, paths = bound
    captured = []
    def intake(root, **kwargs):
        captured.append(root)
        return {'ok': True, 'processed': 0}
    monkeypatch.setattr(markdown, 'intake_archives', intake)
    response = TestClient(main.app).post('/api/knowledge/markdown/intake', json={})
    assert response.status_code == 200
    assert captured == [paths.run_root]


def test_test_bo_settings_named_and_explicit_files(bound):
    from app.test_bo_settings import load_test_bo_defaults
    main, paths = bound
    settings = paths.memory_root / 'bo_workspace_settings.json'
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({'initial_design_size': 12}))
    assert load_test_bo_defaults(paths=paths)['initial_design_size'] == 12
