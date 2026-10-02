"""Tests for Graphify-compatible project scan/import bridge."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from knowledge.graph_backend import JsonGraphBackend
from knowledge.graphify_bridge import import_project_graph, load_graphify_graph, scan_project_graph


def _fixture_project(root: Path) -> None:
    (root / "agents" / "analysis").mkdir(parents=True)
    (root / "docs" / "runtime").mkdir(parents=True)
    (root / "graphs" / "modules" / "analysis").mkdir(parents=True)
    (root / "agents" / "analysis" / "agent.py").write_text(
        "from knowledge.stores import JsonlKnowledgeStore\n\n"
        "def run_analysis():\n"
        "    return 'guardian bo gyroid utm'\n",
        encoding="utf-8",
    )
    (root / "docs" / "runtime" / "analysis.md").write_text("Analysis agent documents UTM and BO handoff.\n", encoding="utf-8")
    (root / "graphs" / "modules" / "analysis" / "module.yaml").write_text("module:\n  id: analysis\n", encoding="utf-8")
    (root / "memory").mkdir()
    (root / "memory" / "prusa_connection.json").write_text('{"password":"do-not-scan"}', encoding="utf-8")


def test_scan_project_graph_writes_graph_report_and_excludes_secrets(tmp_path: Path) -> None:
    _fixture_project(tmp_path)

    result = scan_project_graph(tmp_path, source_paths=["agents", "docs/runtime", "graphs"], out_dir=tmp_path / "memory" / "knowledge" / "graphify")

    assert result["ok"] is True
    graph_json = Path(result["outputs"]["graph_json"])
    report = Path(result["outputs"]["graph_report"])
    assert graph_json.exists()
    assert report.exists()
    graph = json.loads(graph_json.read_text(encoding="utf-8"))
    node_ids = {node["id"] for node in graph["nodes"]}
    edge_types = {edge["type"] for edge in graph["edges"]}
    assert "file:agents/analysis/agent.py" in node_ids
    assert "agent:analysis" in node_ids
    assert "module:analysis" in node_ids
    assert "memory/prusa_connection.json" not in json.dumps(graph, ensure_ascii=False)
    assert {"IMPLEMENTS", "DOCUMENTS", "DECLARES"} & edge_types


def test_import_project_graph_to_json_backend(tmp_path: Path) -> None:
    _fixture_project(tmp_path)
    scan = scan_project_graph(tmp_path, source_paths=["agents", "docs/runtime", "graphs"], out_dir=tmp_path / "memory" / "knowledge" / "graphify")
    backend = JsonGraphBackend(tmp_path / "memory" / "knowledge" / "graph_backend" / "knowledge_graph.json")

    result = import_project_graph(backend, Path(scan["outputs"]["graph_json"]), include_runtime_memory=False)

    assert result["ok"] is True
    assert result["project_nodes"] > 0
    assert result["nodes_written"] > 0
    context = backend.query({"kind": "project_context", "target_id": "analysis", "limit": 20})
    assert any(node["id"] == "agent:analysis" or node["id"] == "file:agents/analysis/agent.py" for node in context["nodes"])


def test_load_common_graphify_link_schema(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "a", "type": "Concept", "label": "A"}, {"id": "b", "type": "Concept", "label": "B"}],
                "links": [{"source": "a", "target": "b", "relation": "connects"}],
            }
        ),
        encoding="utf-8",
    )

    graph = load_graphify_graph(graph_path)

    assert {node["id"] for node in graph["nodes"]} == {"graphify:a", "graphify:b"}
    assert graph["edges"][0]["type"] == "CONNECTS"


@pytest.mark.parametrize('external', [False, True])
def test_relocated_graph_keeps_import_identity_and_excludes_private_symlinks(tmp_path, monkeypatch, external):
    from knowledge import graphify_bridge as bridge
    runtime = tmp_path / 'runtime'
    _fixture_project(runtime)
    (runtime / 'knowledge').mkdir()
    (runtime / 'knowledge/__init__.py').write_text('"""Real import target."""\n')
    (tmp_path / 'system/runtime').mkdir(parents=True)
    (tmp_path / 'system/runtime/analysis.md').write_text('Reviewed analysis reference.')
    (tmp_path / 'workspace').mkdir()
    private = tmp_path / 'workspace/private.md'
    private.write_text('UNSCANNABLE_PRIVATE_SENTINEL')
    (runtime / 'agents/leak.md').symlink_to(private)
    (runtime / 'agents/linked').symlink_to(tmp_path / 'workspace', target_is_directory=True)
    mapping = {'agents/analysis/agent.py': 'runtime/agents/analysis/agent.py',
               'knowledge/__init__.py': 'runtime/knowledge/__init__.py',
               'docs/runtime/analysis.md': 'system/runtime/analysis.md'}
    if external:
        def extraction(project, out, files):
            # Simulate Graphify's path IDs, not the normalization implementation.
            graph = {'nodes': [{'id': 'file:' + name, 'path': name, 'type': 'CodeFile'} for name in files],
                     'links': [{'source': 'file:runtime/agents/analysis/agent.py',
                                'target': 'file:runtime/knowledge/__init__.py', 'type': 'IMPORTS'}]}
            path = out / 'external.json'
            path.write_text(json.dumps(graph))
            return {'ok': True, 'graph_json': str(path)}
        monkeypatch.setattr(bridge, '_run_external_graphify', extraction)
    result = scan_project_graph(tmp_path, runtime_root=runtime,
        corpus_paths=['runtime/agents', 'runtime/knowledge', 'system/runtime', 'workspace'],
        reference_map=mapping, out_dir=tmp_path / 'results', run_external_graphify=external)
    graph = json.loads(Path(result['outputs']['graph_json']).read_text())
    nodes = {node['id']: node for node in graph['nodes']}
    assert 'file:agents/analysis/agent.py' in nodes
    assert 'file:knowledge/__init__.py' in nodes
    assert 'file:docs/runtime/analysis.md' in nodes
    assert not any('file:runtime/' in node for node in nodes)
    assert any(edge['source'] == 'file:agents/analysis/agent.py' and
               edge['target'] == 'file:knowledge/__init__.py' and edge['type'] == 'IMPORTS'
               for edge in graph['edges'])
    assert nodes['file:knowledge/__init__.py']['properties'].get('generated_placeholder') is not True
    assert nodes['file:agents/analysis/agent.py']['properties']['path'] == 'runtime/agents/analysis/agent.py'
    assert not any(word in json.dumps(graph) for word in ('leak.md', 'linked/', 'private.md', 'UNSCANNABLE'))


@pytest.mark.parametrize('mapping', [
    {'a.py': 'runtime/a.py', 'b.py': 'runtime/a.py'},
    {'../a.py': 'runtime/a.py'}, {'a.py': '/outside/a.py'},
    {'a.py': 'runtime/a.py', 'runtime/a.py': 'runtime/b.py'},
])
def test_graph_rejects_ambiguous_or_escaping_identity_maps_before_writing(tmp_path, mapping):
    with pytest.raises(ValueError):
        scan_project_graph(tmp_path, runtime_root=tmp_path / 'runtime', corpus_paths=['runtime/agents'],
                           reference_map=mapping, out_dir=tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('corpus', [['.'], ['docs'], ['system'], ['runtime'], ['../outside']])
def test_graph_rejects_unbounded_or_escaping_corpus_before_writing(tmp_path, corpus):
    with pytest.raises(ValueError):
        scan_project_graph(tmp_path, runtime_root=tmp_path / 'runtime', corpus_paths=corpus,
                           out_dir=tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('edge_metadata', [{}, {'id': 'external-edge-identity'}])
@pytest.mark.parametrize('absolute', [False, True])
def test_external_graph_preserves_its_own_historical_node_and_edge_namespace(tmp_path, monkeypatch, edge_metadata, absolute):
    from knowledge import graphify_bridge as bridge
    (tmp_path / 'runtime/agents').mkdir(parents=True)
    (tmp_path / 'runtime/agents/a.py').write_text('import b\n')
    (tmp_path / 'runtime/agents/b.py').write_text('pass\n')
    prefix = str(tmp_path) + '/' if absolute else ''
    baseline = {'nodes': [{'id': prefix + 'agents/a.py'}, {'id': prefix + 'agents/b.py'}],
                'links': [{'source': prefix + 'agents/a.py', 'target': prefix + 'agents/b.py', 'type': 'IMPORTS', **edge_metadata}]}
    baseline_path = tmp_path / 'baseline.json'
    baseline_path.write_text(json.dumps(baseline))
    before = load_graphify_graph(baseline_path)
    def extraction(project, out, files):
        graph = {'nodes': [{'id': prefix + 'runtime/agents/a.py'}, {'id': prefix + 'runtime/agents/b.py'}],
                 'links': [{'source': prefix + 'runtime/agents/a.py', 'target': prefix + 'runtime/agents/b.py', 'type': 'IMPORTS', **edge_metadata}]}
        path = out / 'external.json'
        path.write_text(json.dumps(graph))
        return {'ok': True, 'graph_json': str(path)}
    monkeypatch.setattr(bridge, '_run_external_graphify', extraction)
    result = scan_project_graph(tmp_path, runtime_root=tmp_path / 'runtime', corpus_paths=['runtime/agents'],
        reference_map={'agents/a.py': 'runtime/agents/a.py', 'agents/b.py': 'runtime/agents/b.py'},
        out_dir=tmp_path / 'out', run_external_graphify=True)
    after = json.loads(Path(result['outputs']['graph_json']).read_text())
    assert {x['id'] for x in before['nodes']} == {x['id'] for x in after['nodes']}
    assert {(x['id'], x['source'], x['target'], x['type']) for x in before['edges']} == {
        (x['id'], x['source'], x['target'], x['type']) for x in after['edges']}


def test_normalized_external_graph_can_be_reimported_without_duplicate_namespace(tmp_path):
    path = tmp_path / 'graph.json'
    path.write_text(json.dumps({'nodes': [{'id': 'graphify:agents/a.py'}], 'edges': []}))
    assert load_graphify_graph(path)['nodes'][0]['id'] == 'graphify:agents/a.py'


def test_graph_never_enumerates_an_excluded_private_corpus(tmp_path, monkeypatch):
    private = tmp_path / 'workspace'
    private.mkdir()
    (private / 'private.txt').write_text('Private state')
    nested = tmp_path / 'agents/private'
    nested.mkdir(parents=True)
    (nested / 'private.txt').write_text('Nested private state')
    original = os.scandir
    def guarded_scan(path):
        if Path(path) in {private, nested}:
            pytest.fail('Private corpus was enumerated')
        return original(path)
    monkeypatch.setattr(os, 'scandir', guarded_scan)
    result = scan_project_graph(tmp_path, corpus_paths=['workspace', 'agents'], out_dir=tmp_path / 'out')
    graph = json.loads(Path(result['outputs']['graph_json']).read_text())
    assert not any(x['id'].startswith('file:') for x in graph['nodes'])


def test_fallback_graph_node_and_edge_identities_equal_before_and_after_move(tmp_path):
    before_root, after_root = tmp_path / 'before', tmp_path / 'after'
    _fixture_project(before_root)
    (before_root / 'knowledge').mkdir()
    (before_root / 'knowledge/__init__.py').write_text('pass\n')
    mapping = {'agents/analysis/agent.py': 'runtime/agents/analysis/agent.py',
               'knowledge/__init__.py': 'runtime/knowledge/__init__.py',
               'graphs/modules/analysis/module.yaml': 'runtime/graphs/modules/analysis/module.yaml',
               'docs/runtime/analysis.md': 'system/runtime/analysis.md'}
    for source, destination in mapping.items():
        target = after_root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(before_root / source, target)
    before = scan_project_graph(before_root, corpus_paths=list(mapping), out_dir=tmp_path / 'before-output')
    after = scan_project_graph(after_root, runtime_root=after_root / 'runtime',
        corpus_paths=list(mapping.values()), reference_map=mapping, out_dir=tmp_path / 'after-output')
    before_graph = json.loads(Path(before['outputs']['graph_json']).read_text())
    after_graph = json.loads(Path(after['outputs']['graph_json']).read_text())
    assert {x['id'] for x in before_graph['nodes']} == {x['id'] for x in after_graph['nodes']}
    assert {(x['id'], x['source'], x['target'], x['type']) for x in before_graph['edges']} == {
        (x['id'], x['source'], x['target'], x['type']) for x in after_graph['edges']}


@pytest.mark.parametrize('moved', [False, True])
def test_safe_import_placeholders_survive_without_ingesting_target_content(tmp_path, monkeypatch, moved):
    root = tmp_path / 'checkout'
    runtime = root / 'runtime' if moved else root
    (runtime / 'agents').mkdir(parents=True)
    (runtime / 'agents/a.py').write_text('import utils\nimport memory\nimport linked\n')
    for directory in ('utils', 'memory'):
        (runtime / directory).mkdir()
        (runtime / directory / '__init__.py').write_text('TARGET_CONTENT_MUST_NOT_BE_READ')
    (runtime / 'linked.py').symlink_to(runtime / 'utils/__init__.py')
    original = Path.read_bytes
    def guarded_read(path):
        if path in {runtime / 'utils/__init__.py', runtime / 'memory/__init__.py', runtime / 'linked.py'}:
            pytest.fail('Reference-only import target content was read')
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', guarded_read)
    result = scan_project_graph(root, runtime_root=runtime, corpus_paths=['runtime/agents' if moved else 'agents'],
        reference_map={'agents/a.py': 'runtime/agents/a.py', 'utils/__init__.py': 'runtime/utils/__init__.py'} if moved else {},
        out_dir=tmp_path / 'out')
    graph = json.loads(Path(result['outputs']['graph_json']).read_text())
    nodes = {x['id']: x for x in graph['nodes']}
    assert nodes['file:utils/__init__.py']['properties']['generated_placeholder'] is True
    assert any(x['source'] == 'file:agents/a.py' and x['target'] == 'file:utils/__init__.py'
               and x['type'] == 'IMPORTS' for x in graph['edges'])
    assert not any('memory/' in name or 'linked.py' in name for name in nodes)
    assert 'TARGET_CONTENT_MUST_NOT_BE_READ' not in json.dumps(graph)
