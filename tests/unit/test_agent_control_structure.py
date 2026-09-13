"""Source-bound detail must remain distinct from executable route edits."""
import ast
from pathlib import Path

import pytest

from agents.design.agent import DesignAgent
from agents.design.execution import design_execution_catalog
from agents.orchestrator_execution import orchestrator_execution_catalog

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('catalog', [design_execution_catalog(DesignAgent()),
                                   orchestrator_execution_catalog(None, context=None, handlers=None)])
def test_catalog_exposes_resolvable_internal_relations_without_registering_extra_operations(catalog):
    public = catalog.describe()
    structure = public.get('implementation_structure')
    assert structure, 'The IDE must receive internal function/tool relationships from the owner catalog'
    assert len(public['operations']) == 4  # Presentation must not create new executable tools.
    for handler, detail in structure['operations'].items():
        assert handler in {op['handler'] for op in public['operations']}
        ids = {'$operation'} | {node['id'] for node in detail['nodes']}
        for edge in detail['edges']:
            assert edge['source'] in ids and edge['target'] in ids
        for node in detail['nodes']:
            source = node['source']
            path = ROOT / source['path']
            assert path.is_relative_to(ROOT) and not Path(source['path']).is_absolute()
            tree = ast.parse(path.read_text())
            name = source['symbol'].split('.')[-1]
            assert any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                       and item.name == name for item in ast.walk(tree)), source
    # describe() must not leak mutable catalog state into editor responses.
    structure['operations'].clear()
    assert catalog.describe()['implementation_structure']['operations']


def test_design_detail_includes_actual_inspection_feedback_and_five_area_responsibility():
    public = design_execution_catalog(DesignAgent()).describe()
    structure = public.get('implementation_structure', {})
    detail = structure.get('operations', {}).get('design.decide', {})
    assert any(edge['source'] == 'inspect' and edge['target'] == '$operation'
               and edge['kind'] == 'evidence' for edge in detail.get('edges', []))
    assert any(node['id'] == 'inspect' and node['area'] == 'low' for node in detail.get('nodes', []))
