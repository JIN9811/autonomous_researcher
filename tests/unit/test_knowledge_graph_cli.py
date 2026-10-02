"""CLI defaults bind named stores; explicit operator paths remain repository-relative."""
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import sys

import pytest

from scripts import knowledge_graph_cli as cli
from utils.runtime_paths import RuntimePaths


@pytest.fixture
def paths(tmp_path):
    return RuntimePaths(**{f.name: tmp_path / f.name for f in fields(RuntimePaths)})


@pytest.mark.parametrize('explicit', [None, 'memory/knowledge/graph_backend/knowledge_graph.json', 'custom.json'])
def test_cli_health_default_and_explicit_paths(paths, monkeypatch, capsys, explicit):
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '1')
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_BACKEND', 'json')
    argv = ['knowledge_graph_cli'] + ([] if explicit is None else ['--json-path', explicit]) + ['health']
    monkeypatch.setattr(sys, 'argv', argv)
    assert cli.main(paths=paths) == 0
    result = json.loads(capsys.readouterr().out)
    expected = paths.memory_root / 'knowledge/graph_backend/knowledge_graph.json' if explicit is None else paths.repository_root / explicit
    assert result['path'] == str(expected)


def test_cli_explicit_project_root_retains_legacy_defaults(paths, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '1')
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_BACKEND', 'json')
    root = tmp_path / 'operator'
    monkeypatch.setattr(sys, 'argv', ['cli', '--project-root', str(root), 'health'])
    assert cli.main(paths=paths) == 0
    assert json.loads(capsys.readouterr().out)['path'] == str(root / 'memory/knowledge/graph_backend/knowledge_graph.json')


@pytest.mark.parametrize('explicit', [None, 'custom', '/tmp/operator-neo4j'])
def test_cli_volume_paths_preserve_memory_family_and_docker_arguments(paths, monkeypatch, explicit):
    calls = []
    def run(cmd, *, check):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(cli, '_run', run)
    args = SimpleNamespace(data_dir=explicit, logs_dir=explicit, container='fixture', image='neo4j:5-community',
                           http_port=17474, bolt_port=17687, password='fixture-secret', wait=False)
    result = cli._neo4j_start(paths.repository_root, args, paths=paths)
    data = paths.memory_root / 'knowledge/neo4j/data' if explicit is None else paths.repository_root / explicit
    logs = paths.memory_root / 'knowledge/neo4j/logs' if explicit is None else paths.repository_root / explicit
    assert result['data_dir'] == str(data) and result['logs_dir'] == str(logs)
    assert calls[-1] == ['docker', 'run', '-d', '--name', 'fixture', '-p', '17474:7474', '-p', '17687:7687',
                         '-e', 'NEO4J_AUTH=neo4j/fixture-secret', '-e', 'NEO4J_server_memory_heap_initial__size=512m',
                         '-e', 'NEO4J_server_memory_heap_max__size=2G', '-e', 'NEO4J_server_memory_pagecache_size=1G',
                         '-v', f'{data}:/data', '-v', f'{logs}:/logs', 'neo4j:5-community']
    assert data.is_dir() and logs.is_dir()
    assert not paths.log_root.exists()


def test_cli_import_reads_bound_memory_and_preserves_graph_identities(paths, monkeypatch, capsys):
    from knowledge.stores import JsonlKnowledgeStore
    from tests.unit.test_knowledge_graph_backend import _records
    experiment, *_ = _records()
    store = JsonlKnowledgeStore(memory_root=paths.memory_root / 'knowledge', run_root=paths.run_root)
    store.append_experiment_record(experiment)
    evidence = (store.memory_root / 'experiment_knowledge_records.jsonl').read_bytes()
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '1')
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_BACKEND', 'json')
    monkeypatch.setattr(sys, 'argv', ['cli', 'import', '--limit', '1'])
    assert cli.main(paths=paths) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['records'] == 1
    graph = json.loads((paths.memory_root / 'knowledge/graph_backend/knowledge_graph.json').read_text())
    assert 'experiment:exp-graph-1' in {n['id'] for n in graph['nodes']}
    assert evidence == (store.memory_root / 'experiment_knowledge_records.jsonl').read_bytes()
    assert not paths.repository_root.exists() and not paths.runtime_root.exists()


def test_cli_flat_default_equals_explicit_legacy_default(paths, tmp_path, monkeypatch):
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_ENABLED', '1')
    monkeypatch.setenv('ATR_KNOWLEDGE_GRAPH_BACKEND', 'json')
    flat = replace(paths, repository_root=tmp_path, runtime_root=tmp_path,
                   memory_root=tmp_path / 'memory', run_root=tmp_path / 'runs')
    implicit = cli._backend(tmp_path, None, paths=flat)
    explicit = cli._backend(tmp_path, 'memory/knowledge/graph_backend/knowledge_graph.json')
    assert implicit.path == explicit.path
