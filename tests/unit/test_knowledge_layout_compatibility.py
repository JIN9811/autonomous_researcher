"""Curated references and learned stores remain independent across relocation."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from agents.core.knowledge.runtime_reference import EXECUTION_TOPICS, build_execution_reference
from knowledge.context_service import KnowledgeContextService
from knowledge.manuals.service import ManualKnowledgeService
from knowledge.wiki import WikiCatalog

ROOT = Path(__file__).resolve().parents[2]


def _relocated_corpus(tmp_path):
    mapping = {old: row['destination'] for old, row in json.loads(
        (ROOT / 'docs/maintenance/repository_layout_manifest.json').read_text())['entries'].items()}
    for page in (ROOT / 'docs/knowledge/wiki').glob('*.md'):
        _, front, body = page.read_text().split('---\n', 2)
        meta = json.loads(front)
        for source in meta['source_refs']:
            target = tmp_path / mapping[source]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)
        meta['source_refs'] = [mapping[source] for source in meta['source_refs']]
        meta['source_revision'] = {mapping[source]: digest for source, digest in meta['source_revision'].items()}
        assert set(meta['source_refs']) == set(meta['source_revision'])
        target = tmp_path / mapping[page.relative_to(ROOT).as_posix()]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('---\n' + json.dumps(meta) + '\n---\n' + body)
    return tmp_path / 'system/knowledge/wiki'


def _snapshot(service):
    ctx = SimpleNamespace(knowledge_service=service, active_backend='vllm', backend_fallbacks={})
    return SimpleNamespace(
        identities=[(x['record_id'], x['topic_id'], x['verified_at'], x['freshness'],
                     x['owner'], x['applicability'], x['status'], sorted(x['source_revision'].values()))
                    for x in service.wiki.query('', limit=100)['items']],
        citations=[x['citation_id'] for x in service.query(None, '', consumer='fixture', limit=100)['items']],
        execution_excerpts={owner: build_execution_reference(ctx, consumer=owner)['pack']['items']
                            for owner in EXECUTION_TOPICS})


def test_all_reviewed_identities_excerpts_and_staleness_survive_relocation(tmp_path):
    corpus = _relocated_corpus(tmp_path)
    old = KnowledgeContextService(ROOT, data_root=tmp_path / 'old-state')
    new = KnowledgeContextService(tmp_path / 'runtime', data_root=tmp_path / 'learned',
                                  wiki_corpus_root=corpus, wiki_source_root=tmp_path)
    before, after = _snapshot(old), _snapshot(new)
    assert len(before.identities) == len(before.citations) == 23
    assert before.identities == after.identities
    assert before.citations == after.citations
    # Reference-bearing metadata changes; owner text and citation identity do not.
    for snapshot in (before, after):
        snapshot.execution_excerpts = {owner: [(x['citation_id'], x['content'].encode()) for x in items]
                                       for owner, items in snapshot.execution_excerpts.items()}
    assert before.execution_excerpts == after.execution_excerpts
    assert all(before.execution_excerpts.values())
    page = new.wiki.read('bo-role')
    source = tmp_path / page['source_refs'][0]
    source.write_bytes(source.read_bytes() + b'\nchanged source byte')
    assert new.wiki.read('bo-role')['freshness'] == 'stale'
    assert new.wiki.read('bo-role')['verified_at'] == page['verified_at']
    assert new.read_context(None, 'wiki:bo-role') is None


def test_wiki_missing_explicit_corpus_never_selects_bundled_pages(tmp_path):
    assert WikiCatalog(tmp_path).count() == 0
    assert not list(tmp_path.iterdir())


def test_wiki_rejects_missing_or_conflicting_root_selection(tmp_path):
    with pytest.raises(ValueError):
        WikiCatalog()
    with pytest.raises(ValueError):
        WikiCatalog(corpus_root=tmp_path)
    with pytest.raises(ValueError):
        WikiCatalog(tmp_path, source_root=tmp_path / 'other')


def test_manual_data_alias_and_registry_relative_sources(tmp_path, monkeypatch):
    from knowledge.manuals import ingest
    registry = tmp_path / 'system/manuals/registry.yaml'
    registry.parent.mkdir(parents=True)
    source = registry.parent / 'sources/example.pdf'
    source.parent.mkdir()
    source.write_bytes(b'synthetic manual fixture')
    registry.write_text(json.dumps({'schema': 'manual_source_registry.v1', 'sources': [
        {'source_id': 'example', 'equipment_type': 'utm', 'path': 'sources/example.pdf'}]}))
    extracted = []
    def extractor(path):
        extracted.append(path)
        return ['1. Procedure\nFixture manual procedure.']
    monkeypatch.setattr(ingest, 'extract_pdf_pages', extractor)
    data = tmp_path / 'external-store/manuals'
    service = ManualKnowledgeService(project_root=tmp_path / 'runtime', manual_data_root=data,
                                     runtime_root=data, registry_path=registry)
    assert not data.exists()
    assert service.ingest()['ok']
    assert extracted == [source]
    assert (data / 'corpus.json').is_file()
    before_corpus = json.loads((data / 'corpus.json').read_text())
    relocated_registry = tmp_path / 'relocated-system/manuals/registry.yaml'
    shutil.copytree(registry.parent, relocated_registry.parent)
    relocated = ManualKnowledgeService(project_root=tmp_path / 'other-code',
        manual_data_root=tmp_path / 'other-manual-data', registry_path=relocated_registry)
    assert relocated.ingest()['ok']
    assert extracted == [source, relocated_registry.parent / 'sources/example.pdf']
    after_corpus = json.loads((relocated.manual_data_root / 'corpus.json').read_text())
    assert before_corpus['chunks'] == after_corpus['chunks']
    with pytest.raises(ValueError):
        ManualKnowledgeService(project_root=tmp_path, manual_data_root=data, runtime_root=tmp_path / 'other')


def test_source_library_and_context_markdown_use_explicit_private_roots(tmp_path):
    from knowledge.source_runtime import library_for
    from knowledge.markdown_runtime import store_for
    from utils.runtime_paths import current_paths
    paths = replace(current_paths(), repository_root=tmp_path / 'checkout',
                    run_root=tmp_path / 'unrelated/runs', memory_root=tmp_path / 'state',
                    source_inbox_root=tmp_path / 'inbox')
    library = library_for(library_root=paths.memory_root / 'knowledge/source_library', inbox_root=paths.source_inbox_root)
    assert library.root == paths.memory_root / 'knowledge/source_library'
    assert library.inbox == paths.source_inbox_root
    store = store_for(SimpleNamespace(paths=paths, artifact_run_root=str(paths.run_root)))
    assert store.root == paths.memory_root / 'knowledge/markdown'
    assert not paths.repository_root.exists()
    assert not paths.run_root.parent.exists()


@pytest.mark.asyncio
async def test_bootstrap_and_production_factories_share_explicit_knowledge_bindings(tmp_path, monkeypatch):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    from knowledge.rag import LocalRAGIndex
    from utils.runtime_paths import current_paths
    import app.main as main
    corpus = _relocated_corpus(tmp_path)
    for relative in ('project/Project_guide.txt', 'agents/specimen_design_existing_runtime_guideline.txt'):
        target = tmp_path / 'system' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'docs' / relative, target)
    paths = replace(current_paths(), system_root=tmp_path / 'system',
                    memory_root=tmp_path / 'learned', source_inbox_root=tmp_path / 'inbox',
                    run_root=tmp_path / 'unrelated/runs')
    monkeypatch.setattr(bootstrap, '_build_backend', lambda *args, **kwargs: MockLLMBackend())
    controller = bootstrap.load_runtime(paths=paths)
    ctx = controller._deps.agent_context
    assert ctx.paths is controller._deps.paths is paths
    assert ctx.knowledge_service.wiki.root == corpus
    assert ctx.knowledge_service.wiki.source_root == paths.repository_root
    assert ctx.knowledge_service.data_root == paths.memory_root / 'knowledge'
    before = SimpleNamespace(guide_chunks=[asdict(x) for x in
        LocalRAGIndex.from_file(ROOT / 'docs/project/Project_guide.txt')._chunks])
    after = SimpleNamespace(guide_chunks=[asdict(x) for x in ctx.rag._local_index._chunks])
    assert before.guide_chunks == after.guide_chunks
    assert ctx.rag._local_index.source_path == paths.system_root / 'project/Project_guide.txt'
    assert not (paths.memory_root / 'knowledge/source_library').exists()
    library = ctx.tools.resource('knowledge.sources')()
    assert library.root == paths.memory_root / 'knowledge/source_library'
    assert library.inbox == paths.source_inbox_root
    rendered = await controller._live_guideline_context(operator_message='message', goal='goal')
    assert '[source=docs/agents/specimen_design_existing_runtime_guideline.txt]\n' in rendered
    assert (ROOT / 'docs/agents/specimen_design_existing_runtime_guideline.txt').read_text().strip()[:1800] in rendered
    monkeypatch.setattr(main, 'RUNTIME_PATHS', paths)
    monkeypatch.setattr(main, 'KNOWLEDGE_MEMORY_ROOT', paths.memory_root / 'knowledge')
    monkeypatch.setattr(main, '_SOURCE_INGESTION_SERVICE', None)
    monkeypatch.setattr(main, '_KNOWLEDGE_CONTEXT_SERVICE', None)
    monkeypatch.setattr(main, 'controller', SimpleNamespace(_deps=SimpleNamespace(agent_context=SimpleNamespace())))
    assert main._source_ingestion_service().library.root == library.root
    assert main._source_ingestion_service().library.inbox == library.inbox
    assert main._knowledge_context_service().wiki.root == corpus
    manual = main._manual_knowledge_service()
    assert manual.manual_data_root == paths.memory_root / 'knowledge/manual_rag'
    assert manual.registry_path == paths.system_root / 'knowledge/manuals/registry.yaml'
