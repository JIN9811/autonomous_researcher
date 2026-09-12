"""Provider probe reporting must not turn delivery into proof of use."""
from scripts.verify_knowledge_workspace import classify_response
import pytest


@pytest.mark.asyncio
async def test_question_probe_uses_controller_grounding_and_returns_unknown_without_evidence(tmp_path):
    from types import SimpleNamespace
    from scripts.verify_knowledge_workspace import question_probe
    from knowledge.context_service import KnowledgeContextService
    from pathlib import Path
    async def complete(*args, **kwargs):
        return SimpleNamespace(text='{"answer":"Invented claim","citation_ids":[],"owner_readback_owners":[]}')
    ctx = SimpleNamespace(complete=complete, active_backend='vllm', backend_fallbacks={'vllm':'vllm'},
        knowledge_service=KnowledgeContextService(Path(__file__).resolve().parents[2], data_root=tmp_path), knowledge_principal=None)
    result = await question_probe(ctx, 'nonexistenttokenonly')
    assert result['answer'].startswith('I can’t provide a grounded answer')
    assert result['sources'] == []


def test_probe_requires_actual_output_and_separates_citation_use():
    pack = {"authority": "reference_only", "items": [{"citation_id": "wiki:design"}]}
    assert classify_response(pack, "") == {"responded": False, "cited_ids": []}
    assert classify_response(pack, '{"reason":"Review candidate"}') == {"responded": True, "cited_ids": []}
    assert classify_response(pack, '{"reason":"See wiki:design"}') == {"responded": True, "cited_ids": ["wiki:design"]}


def test_probe_rejects_citation_prefix_and_validates_receipt_use_distinction():
    from scripts.verify_knowledge_workspace import delivery_outcome
    assert classify_response({'items': [{'citation_id': 'wiki:design'}]}, 'wiki:design-invalid')['cited_ids'] == []
    assert delivery_outcome({'stage': 'delivered', 'use_status': 'unknown', 'used_citation_ids': []}) == 'unknown'
    assert delivery_outcome({'stage': 'excluded', 'use_status': 'excluded', 'non_use_reason': 'irrelevant', 'used_citation_ids': []}) == 'excluded'
    with pytest.raises(ValueError): delivery_outcome({'stage': 'used', 'used_citation_ids': ['wiki:fake'], 'delivered_citation_ids': ['wiki:real']})
